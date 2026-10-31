# Models of your own, step by step

The starter kit answers with two shared models (a chat model and an embedding model)
that the organizers run on JURECA. You can replace either with a model of your own
choice, or with a fine-tuned one, without changing any code: the kit reads which model
to use, where, and with which key, from `.env`. This page walks through every step in
order, with the commands, what they print, and what to check. [jureca.md](jureca.md)
explains the same commands one by one; [re-embedding.md](re-embedding.md) explains the
vector index.

Before you start: `gagnvist jureca check` says "All set" without a `NOTE` about the
`container` group or the GPU partitions (models of your own need both:
[jureca.md, section 1](jureca.md#1-your-jureca-account), step 4), and
`gagnvist jureca connect` (the tunnel to the shared models) is open in a terminal of
its own.

## What changes where

| You want | On JURECA | In `.env` | Then |
|---|---|---|---|
| another chat model | `gagnvist jureca download`, `gagnvist jureca start chat` | `GAGNVIST_CHAT_MODEL`, `GAGNVIST_CHAT_URL`, `GAGNVIST_CHAT_KEY` | `gagnvist try-models`, `gagnvist ask`, `gagnvist evaluate` |
| another embedding model | `gagnvist jureca download`, `gagnvist jureca start embeddings` | `GAGNVIST_EMBEDDINGS_MODEL`, `GAGNVIST_EMBEDDINGS_URL`, `GAGNVIST_EMBEDDINGS_KEY`, and `GAGNVIST_SEARCH_INDEX` | `gagnvist build-vectors`, then `try-models`, `ask`, `evaluate` |
| a fine-tuned chat model | `gagnvist jureca finetune`, then `gagnvist jureca start chat ... --adapter` | `GAGNVIST_CHAT_MODEL` (the run's name), `_URL`, `_KEY` | `try-models`, `ask`, `evaluate` |

The three lines for a server are printed by `gagnvist jureca connect --job JOB`: copy
them into `.env` as they are. Nothing in the code needs to change.
(`src/gagnvist/config.py` reads these names; `ModelClient.from_settings` in
`src/gagnvist/models/client.py` builds the two connections from them. The one exception
is an embedding model that wants a word in front of every text, see
[step 2](#2-another-embedding-model).)

Every server of your own is a Slurm job under your own account, with its own random
key, reached through a tunnel of its own: chat servers on port 8811 of your computer,
embedding servers on 8812. So you keep up to three terminals open: the shared tunnel,
your server's tunnel, and your work.

## 1. Another chat model

**Download it** from Hugging Face into your folder on JURECA (once; it stays there):

```bash
gagnvist jureca download Qwen/Qwen2.5-0.5B-Instruct
```

It prints the progress of each file, then where the model is and how to serve it:

```text
Downloaded Qwen/Qwen2.5-0.5B-Instruct to /p/project1/<project>/<you>/gagnvist/models/Qwen2.5-0.5B-Instruct
The model is in /p/project1/<project>/<you>/gagnvist/models/Qwen2.5-0.5B-Instruct on JURECA.
Serve it:  gagnvist jureca start chat Qwen2.5-0.5B-Instruct         (a chat model)
           gagnvist jureca start embeddings Qwen2.5-0.5B-Instruct   (an embedding model)
```

The 0.5B model is about 1 GB in 10 files; a 7B model is about 15 GB, and takes longer
in proportion, mostly depending on how fast Hugging Face delivers. Only the files vLLM
needs are downloaded: when a repository has its weights both as safetensors and in
PyTorch's older `.bin` format, the older format is left out. A model that needs a
licence accepted on Hugging Face also needs your token on JURECA:
[jureca.md, section 7](jureca.md#7-models-of-your-own).

**Start a server** for it:

```bash
gagnvist jureca start chat Qwen2.5-0.5B-Instruct --partition dc-gpu-devel --hours 1
```

```text
Submitted job 1234567: a chat server for Qwen2.5-0.5B-Instruct.
It may wait for a free GPU first, and then needs a few minutes to load the model.
Follow it:      gagnvist jureca jobs   (its log: gagnvist jureca log 1234567)
When it is READY:  gagnvist jureca connect --job 1234567
In its 1 h it uses at most 128 core-hours of the hackathon's budget: a whole node, 128 core-hours per hour, however many GPUs it asks for.
Stop it as soon as you are done:  gagnvist jureca stop 1234567
```

`--partition dc-gpu-devel` is for a quick test only: it often starts sooner, but allows
2 hours at most; leave it out for real work (`dc-gpu`, up to 6 hours, default 4). A job
always gets a whole node with four A100 GPUs of 40 GB each, and costs 128 core-hours
per hour whatever it asks for; `--gpus` only says between how many of them the model is
split:

| Model size (16-bit) | `--gpus` | Why |
|---|---|---|
| up to about 14B parameters | 1 (default) | one GPU has 40 GB; a 14B model's 28 GB of weights leave less room for long conversations |
| about 30B | 2 or 4 | the model is split evenly between the GPUs |
| bigger | 4 | the whole node; a 70B model in 16-bit (140 GB of weights) leaves the four GPUs little room, so choose a smaller one |

`--gpus 4` costs nothing extra and gives any model more memory, but a model can only be
split between as many GPUs as its number of attention heads divides by: a few small
models cannot be split four ways, and the job then ends at once with that in its log.

**Watch it load:**

```bash
gagnvist jureca jobs
```

```text
JOB        NAME                   STATE       NODE         TIME LEFT
1234567    gagnvist-chat          RUNNING     jrc0406      59:50
A server is READY once it has loaded its model: gagnvist jureca connect --job JOB
```

RUNNING means the job has its node and is loading the model; READY means the server
answers. A small model is ready within a few minutes, a 7B model takes a few more. If
the state stays PENDING, JURECA has no free node yet; `gagnvist jureca log JOB` shows
the job's messages if it ends on its own.

**Connect to it** (a new terminal; leave it open while you use the model):

```bash
gagnvist jureca connect --job 1234567
```

```text
Your chat server 'Qwen2.5-0.5B-Instruct' (job 1234567) answers at http://127.0.0.1:8811/v1 while the tunnel is open.
To use it, add these lines to .env (and remove them to go back to the shared one):

    GAGNVIST_CHAT_MODEL=Qwen2.5-0.5B-Instruct
    GAGNVIST_CHAT_URL=http://127.0.0.1:8811/v1
    GAGNVIST_CHAT_KEY=...

Opening a tunnel: 127.0.0.1:8811 -> jrc0406i:... on JURECA
Connected: http://127.0.0.1:8811/v1 serves Qwen2.5-0.5B-Instruct.
The tunnel stays open until you press Ctrl+C.
```

Put the three lines into `.env`. The key is made for this job alone: every time you
start a server again, replace the three lines with the new ones.

**Check which models answer now:**

```bash
gagnvist try-models
```

```text
Chat model Qwen2.5-0.5B-Instruct answered in ... s: ...
Embedding model bge-m3 answered in ... s: 1024 numbers per text; ...
```

The first word after "Chat model" is the model that answered: your own. The embedding
model is still the shared one, through the shared tunnel. Now `gagnvist ask` and
`gagnvist evaluate` use your chat model; evaluate after every change.

**Stop it** when you are done (a running server costs the same whether anyone uses it
or not), and close its tunnel with Ctrl+C:

```bash
gagnvist jureca stop 1234567
```

To go back to the shared chat model, remove the three `GAGNVIST_CHAT_*` lines from
`.env`.

## 2. Another embedding model

An embedding model turns the question and every table's card into vectors; the search
compares them. Vectors from two models cannot be compared, so a new embedding model
also means a new vector index (a minute or two to build).

**Download and start it**, as for a chat model, but as an `embeddings` server:

```bash
gagnvist jureca download intfloat/multilingual-e5-small
gagnvist jureca start embeddings multilingual-e5-small --partition dc-gpu-devel --hours 1
gagnvist jureca jobs                     # READY once the model is loaded
gagnvist jureca connect --job 1234568    # a new terminal; prints the three lines below
```

The e5-small repository holds its weights twice over, as safetensors and as `.bin`; the
download takes the safetensors only (469 MB).

**Point the kit to it**, in `.env`: the three lines `connect` printed, and a new folder
for the new index. Keep the shipped index in `index/` as it is, so that removing the
lines brings the shared model back:

```bash
GAGNVIST_EMBEDDINGS_MODEL=multilingual-e5-small
GAGNVIST_EMBEDDINGS_URL=http://127.0.0.1:8812/v1
GAGNVIST_EMBEDDINGS_KEY=...
GAGNVIST_SEARCH_INDEX=local/index-e5small
```

`gagnvist try-models` now says "Embedding model multilingual-e5-small answered in ... s:
384 numbers per text; ...". Without the `GAGNVIST_SEARCH_INDEX` line, `gagnvist ask`
refuses, rightly:

```text
error: the vector index in .../index was made with the embedding model 'bge-m3', but the
settings use 'multilingual-e5-small': add GAGNVIST_SEARCH_INDEX=local/index-mine (or
another new folder) to .env, and run `gagnvist build-vectors` to fill it
```

**Build the new index**, through your server:

```bash
gagnvist build-vectors
```

"Embedded 3,772 cards with multilingual-e5-small into .../local/index-e5small", after a
minute or two. (If the folder already holds an index, `build-vectors` refuses; add
`--replace` to build it again, or name another folder.) From here on
`gagnvist find-tables`, `ask` and `evaluate` search with your model; compare
`gagnvist evaluate` with and without the four lines in `.env`.

**Prefixes.** Some embedding models expect a word in front of every text: the e5
models want `query: ` before a question and `passage: ` before a document (their page
on Hugging Face says so; bge-m3 wants none). The kit sends the texts as they are, which
works but gives up some quality. To add them, change `card_text` in
`src/gagnvist/search/vector_search.py` (the cards) and `find_tables` in
`src/gagnvist/answering/find_tables.py` (the question), then build new cards and a new
index: [re-embedding.md](re-embedding.md) has the steps (`GAGNVIST_SEARCH_CARDS`,
`gagnvist build-cards`, `gagnvist build-vectors`).

**Back to the shared model:** remove the four lines from `.env`, stop the server, close
its tunnel. The index in `local/index-e5small` stays on your computer for next time.

## 3. Fine-tuning

Fine-tuning teaches a chat model your own examples, as a small adapter (tens of
megabytes) served together with the model. The examples are a JSON Lines file, one
conversation per line, ending with the answer the model should learn to give
([jureca.md, section 8](jureca.md#8-fine-tuning) has the form). Twenty examples made
from the easy evaluation questions are enough for a test; a few hundred good ones are
what makes a difference.

Fine-tuning needs a training library (peft) that the organizers put in the project
once; until they have, the command says so (`fine-tuning is not available on JURECA
yet: ...`) and submits nothing.

```bash
gagnvist jureca finetune Qwen2.5-0.5B-Instruct train.jsonl --name journey-v1 --partition dc-gpu-devel --hours 1
```

The file is checked on your computer first, then uploaded, and the job submitted:

```text
Submitted job 1234569: fine-tuning Qwen2.5-0.5B-Instruct on 20 conversations (journey-v1).
Follow it:  gagnvist jureca log 1234569
When it has finished:  gagnvist jureca start chat Qwen2.5-0.5B-Instruct --adapter journey-v1
In its 1 h it uses at most 128 core-hours of the hackathon's budget: a whole node, 128 core-hours per hour, however many GPUs it asks for.
Stop it as soon as you are done:  gagnvist jureca stop 1234569
```

`gagnvist jureca log 1234569` shows, after Slurm's and the container's own messages,
"20 conversations; training on the GPU", the loss after each step ("epoch 1 step 3/3:
loss ..."), and at the end "Finished: the adapter is in .../finetune/journey-v1/adapter".
A 0.5B model and 20 examples take a few minutes in all; hundreds of examples and a 7B
model take longer in proportion.

You may have two jobs at a time (running or waiting). A job you have just stopped no
longer counts, so `finetune` or `start` right after `stop` is accepted.

**Serve it**, with the run's name as the model name:

```bash
gagnvist jureca start chat Qwen2.5-0.5B-Instruct --adapter journey-v1 --partition dc-gpu-devel --hours 1
gagnvist jureca jobs                     # READY once the model is loaded
gagnvist jureca connect --job 1234570    # prints GAGNVIST_CHAT_MODEL=journey-v1, _URL, _KEY
```

Put the three lines into `.env` (replacing those of any earlier chat server).
`gagnvist try-models` then names `journey-v1` as the chat model; `ask` answers in the
style of the examples, which is what fine-tuning does. Measure with
`gagnvist evaluate`, on questions the model was not trained on.

## 4. Housekeeping

```bash
gagnvist jureca jobs                     # your jobs: PENDING, RUNNING, READY
gagnvist jureca stop JOB                 # end a job, and its cost
gagnvist jureca models                   # your models and fine-tuning runs on JURECA, with sizes
gagnvist jureca delete model NAME        # remove a model you downloaded
gagnvist jureca delete run NAME          # remove a fine-tuning run (its data and adapter)
```

`delete` only touches your own folder on JURECA
(`/p/project1/<project>/<username>/gagnvist/`), and refuses to remove a model or adapter
that a running server of yours serves: stop the job first. A deleted model can be
downloaded again. The project's disk space is shared by everyone, so delete what you no
longer use.

The organizers see every job of the project, and can end a gagnvist job that should not
run (one left running by mistake, for example). Its log then ends with "The organizers
stopped this job."; your files are not touched. Only you can delete your files, so the
organizers may ask you to run `gagnvist jureca delete`.

## What it costs

Every job is billed for its whole node, 128 core-hours per hour, from the moment it
starts until it ends, busy or idle. The walk-through above submits four jobs of 1 hour
each (a chat server, an embedding server, a fine-tuning run and a server for the
adapter), so it can use up to 512 core-hours, and much less if you stop every job as
soon as you are done with it. `gagnvist jureca start` and `finetune` print the most a
job can cost before it runs.

## If something is not right

| Message | What to do |
|---|---|
| `try-models` names the shared models, not yours | The three lines are not in `.env`, or `.env` is in another folder than the one you run the commands in. |
| `the vector index in ... was made with the embedding model 'bge-m3', but the settings use ...` | Add `GAGNVIST_SEARCH_INDEX=local/<a new folder>` to `.env` and run `gagnvist build-vectors`. |
| `... already holds a vector index` | Name another folder in `GAGNVIST_SEARCH_INDEX`, or add `--replace`. |
| `your job N serves 'X': stop it first` | `gagnvist jureca stop N`, then delete. |
| `X was not found on JURECA` / `there is no model 'X' on JURECA` | `gagnvist jureca models` lists the exact names. |
| `the connection ... broke off` right after `connect --job` | The job ended (its time was up, or it was stopped): `gagnvist jureca jobs`, `gagnvist jureca log JOB`. |
| The server job ends at once | `gagnvist jureca log JOB`: usually the model does not fit (`--gpus 2` or `4`, or a smaller `--context`), cannot be split between that many GPUs (fewer `--gpus`), or the folder is not a complete model; or apptainer refuses because your account is not in the `container` group yet. |
| `job ... is still waiting for a GPU` | JURECA is busy. For a quick test, `--partition dc-gpu-devel --hours 1`. |
| `Slurm refused the job: your account cannot use that partition` | Your membership lacks the project's GPU budget: ask the organizers ([jureca.md, section 1](jureca.md#1-your-jureca-account), step 4). |
| `fine-tuning is not available on JURECA yet` | The organizers have not put the training library in the project yet; ask them. |
| The log ends with `The organizers stopped this job.` | The organizers ended the job; ask them if you do not know why. |
