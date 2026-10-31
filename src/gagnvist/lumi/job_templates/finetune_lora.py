"""Fine-tune a chat model with LoRA on a file of conversations.

This script runs on the supercomputer, inside the job's container, as part of the job
that `gagnvist jureca finetune` submits (see finetune.sbatch). It uses only PyTorch,
Transformers and PEFT (which the organizers add where the container lacks it).

Every line of the data file is one conversation that ends with the answer the model
should learn to give:

    {"messages": [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]}

A "system" message may come first. The model learns from the last (assistant) message
only; the messages before it are the context. LoRA trains a few million extra
parameters instead of the whole model, so one GPU chip is enough for a 7B model, and
the result (the adapter) is small.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import time
from pathlib import Path

import torch
import transformers
from packaging.version import Version
from peft import LoraConfig, get_peft_model
from transformers import AutoModelForCausalLM, AutoTokenizer

IGNORED = -100  # label of a token the model does not learn from


def main() -> None:
    args = parse_arguments()
    random.seed(0)
    torch.manual_seed(0)
    device = "cuda" if torch.cuda.is_available() else "cpu"

    tokenizer = AutoTokenizer.from_pretrained(args.model)
    if not tokenizer.chat_template:
        raise SystemExit(f"{args.model} has no chat template: fine-tune a chat (instruct) model")
    examples = read_examples(Path(args.data), tokenizer, args.max_length)
    where = "the GPU" if device == "cuda" else "the CPU (slow: no GPU was found)"
    print(f"{len(examples)} conversations; training on {where}", flush=True)

    model = load_model(args.model, device)
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    model.config.use_cache = False  # caching is for generating text, not for training
    model = get_peft_model(
        model,
        LoraConfig(
            r=args.rank,
            lora_alpha=2 * args.rank,
            lora_dropout=0.05,
            target_modules="all-linear",
            task_type="CAUSAL_LM",
        ),
    )
    model.print_trainable_parameters()

    train(model, examples, args, device)
    model.save_pretrained(args.output)
    tokenizer.save_pretrained(args.output)
    print(f"adapter saved in {args.output}", flush=True)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--model", required=True, help="folder of the model to fine-tune")
    parser.add_argument("--data", required=True, help="JSON Lines file of conversations")
    parser.add_argument("--output", required=True, help="folder to save the adapter in")
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--rank", type=int, default=16, help="LoRA rank: bigger learns more")
    parser.add_argument("--learning-rate", type=float, default=2e-4)
    parser.add_argument("--batch-size", type=int, default=8, help="conversations per step")
    parser.add_argument("--max-length", type=int, default=2048, help="longest conversation, tokens")
    return parser.parse_args()


def read_examples(path: Path, tokenizer, max_length: int) -> list[tuple[list[int], list[int]]]:
    """Every conversation as (token ids, labels); labels mark the answer's tokens only."""
    examples = []
    with path.open(encoding="utf-8-sig") as lines:
        for number, line in enumerate(lines, 1):
            if not line.strip():
                continue
            messages = json.loads(line)["messages"]
            if not messages or messages[-1]["role"] != "assistant":
                raise ValueError(f"{path} line {number}: the last message must be the answer")
            examples.append(encode(messages, tokenizer, max_length))
    if not examples:
        raise ValueError(f"{path} holds no conversations")
    return examples


def encode(
    messages: list[dict[str, str]], tokenizer, max_length: int
) -> tuple[list[int], list[int]]:
    """Token ids of the whole conversation, and labels that hide everything but the answer."""
    context = tokenizer.apply_chat_template(
        messages[:-1], tokenize=False, add_generation_prompt=True
    )
    whole = tokenizer.apply_chat_template(messages, tokenize=False)
    if not whole.startswith(context):
        raise ValueError(
            "the model's chat template changes earlier messages; cannot mark the answer"
        )
    context_ids = tokenizer(context, add_special_tokens=False)["input_ids"]
    answer_ids = tokenizer(whole[len(context) :], add_special_tokens=False)["input_ids"]
    ids = (context_ids + answer_ids)[:max_length]
    labels = ([IGNORED] * len(context_ids) + answer_ids)[:max_length]
    return ids, labels


def load_model(folder: str, device: str):
    """The model in bfloat16, the number format A100 and MI250X GPUs compute fastest in (on a
    computer without a GPU, where this script is only tried out, in float32)."""
    dtype = torch.bfloat16 if device == "cuda" else torch.float32
    # Transformers 4.56 renamed the option torch_dtype to dtype.
    option = "dtype" if Version(transformers.__version__) >= Version("4.56") else "torch_dtype"
    model = AutoModelForCausalLM.from_pretrained(folder, **{option: dtype})
    return model.to(device)


def train(model, examples, args: argparse.Namespace, device: str) -> None:
    """Plain gradient descent: one conversation at a time, one optimizer step per batch."""
    parameters = [p for p in model.parameters() if p.requires_grad]
    optimizer = torch.optim.AdamW(parameters, lr=args.learning_rate, weight_decay=0.0)
    steps = args.epochs * math.ceil(len(examples) / args.batch_size)
    warmup = max(1, steps // 20)
    schedule = torch.optim.lr_scheduler.LambdaLR(
        optimizer, lambda step: min(1.0, (step + 1) / warmup) * max(0.0, 1 - step / steps)
    )
    model.train()
    step, started = 0, time.time()
    for epoch in range(1, args.epochs + 1):
        order = random.sample(range(len(examples)), len(examples))
        for start in range(0, len(order), args.batch_size):
            batch = order[start : start + args.batch_size]
            tokens = sum(sum(1 for label in examples[i][1] if label != IGNORED) for i in batch)
            total = 0.0
            for i in batch:
                ids, labels = examples[i]
                input_ids = torch.tensor([ids], device=device)
                label_ids = torch.tensor([labels], device=device)
                logits = model(input_ids=input_ids).logits[0, :-1].float()
                targets = label_ids[0, 1:]
                loss = torch.nn.functional.cross_entropy(
                    logits, targets, ignore_index=IGNORED, reduction="sum"
                ) / max(1, tokens)  # the average over all answer tokens of the batch
                loss.backward()
                total += loss.item()
            torch.nn.utils.clip_grad_norm_(parameters, 1.0)
            optimizer.step()
            schedule.step()
            optimizer.zero_grad()
            step += 1
            if step % 10 == 0 or step == steps:
                minutes = (time.time() - started) / 60
                print(
                    f"epoch {epoch} step {step}/{steps}: loss {total:.4f} ({minutes:.1f} min)",
                    flush=True,
                )


if __name__ == "__main__":
    main()
