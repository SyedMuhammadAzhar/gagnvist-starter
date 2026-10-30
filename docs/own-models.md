# Models of your own, step by step

The starter kit answers with two shared models (a chat model and an embedding model)
that the organizers run on LUMI. You can replace either with a model of your own choice,
or with a fine-tuned one, without changing any code: the kit reads which model to use,
where, and with which key, from `.env`. This page walks through every step as one
participant did it on 30 October 2026, with the commands, what they print, how long
they took, and what to check. [lumi.md](lumi.md) explains the same commands one by one;
[re-embedding.md](re-embedding.md) explains the vector index. On JURECA every step is
the same with `jureca` in place of `lumi`; [jureca.md, section 8](jureca.md#8-the-lumi-guides-read-for-jureca)
translates the names, paths, ports and GPU sizes used below.

Before you start: `gagnvist lumi check` says "All set", and `gagnvist lumi connect`
(the tunnel to the shared models) is open in a terminal of its own.

## What changes where

| You want | On LUMI | In `.env` | Then |
|---|---|---|---|
| another chat model | `gagnvist lumi download`, `gagnvist lumi start chat` | `GAGNVIST_CHAT_MODEL`, `GAGNVIST_CHAT_URL`, `GAGNVIST_CHAT_KEY` | `gagnvist try-models`, `gagnvist ask`, `gagnvist evaluate` |
| another embedding model | `gagnvist lumi download`, `gagnvist lumi start embeddings` | `GAGNVIST_EMBEDDINGS_MODEL`, `GAGNVIST_EMBEDDINGS_URL`, `GAGNVIST_EMBEDDINGS_KEY`, and `GAGNVIST_SEARCH_INDEX` | `gagnvist build-vectors`, then `try-models`, `ask`, `evaluate` |
| a fine-tuned chat model | `gagnvist lumi finetune`, then `gagnvist lumi start chat ... --adapter` | `GAGNVIST_CHAT_MODEL` (the run's name), `_URL`, `_KEY` | `try-models`, `ask`, `evaluate` |

The three lines for a server are printed by `gagnvist lumi connect --job JOB`: copy them
into `.env` as they are. Nothing in the code needs to change. (`src/gagnvist/config.py`
reads these names; `ModelClient.from_settings` in `src/gagnvist/models/client.py`
builds the two connections from them. The one exception is an embedding model that
wants a word in front of every text, see [step 2](#2-another-embedding-model).)

Every server of your own is a Slurm job under your own account, with its own random
key, reached through a tunnel of its own: chat servers on port 8801 of your computer,
embedding servers on 8802. So you keep up to three terminals open: the shared tunnel,
your server's tunnel, and your work.

## 1. Another chat model

**Download it** from Hugging Face into your folder on LUMI (once; it stays there):

```bash
gagnvist lumi download Qwen/Qwen2.5-0.5B-Instruct
```

It printed the progress of each file, then "Downloaded Qwen/Qwen2.5-0.5B-Instruct to
/scratch/project_462001820/syemuhaz/gagnvist/models/Qwen2.5-0.5B-Instruct" and the
two ways to serve it. The 0.5B model (about 1 GB, 10 files) took 13 seconds; a 7B model
(15 GB) takes a few minutes. Only the files vLLM needs are downloaded: when a repository
has its weights both as safetensors and in PyTorch's older `.bin` format, the older
format is left out. A model that needs a licence accepted on Hugging Face also needs your
token on LUMI: [lumi.md, section 6](lumi.md#6-models-of-your-own).

**Start a server** for it:

```bash
gagnvist lumi start chat Qwen2.5-0.5B-Instruct --partition dev-g --hours 1
```

"Submitted job 23292687: a chat server for Qwen2.5-0.5B-Instruct ... In its 1 h it uses
at most 0.5 GPU-hours of the hackathon's budget." `--partition dev-g` is for a quick
test only: it usually starts at once, but allows 3 hours at most; leave it out for real
work (`small-g`, up to 12 hours, default 4). How many GPU chips:

| Model size (16-bit) | `--gpus` | Why |
|---|---|---|
| up to about 14B parameters | 1 (default) | one chip has 64 GB |
| 27B to 32B | 2 | the model is split evenly between the chips |
| 70B | 4 | the most a job may ask for |

Every chip costs 0.5 GPU-hours per hour while the job runs, busy or idle.

**Watch it load:**

```bash
gagnvist lumi jobs
```

```text
JOB        NAME                   STATE       NODE         TIME LEFT
23292687   gagnvist-chat          RUNNING     nid005002    59:50
```

RUNNING means the job has a GPU and is loading the model; READY means the server
answers. The 0.5B model was READY 89 seconds after `start`; a 7B model takes a few
minutes. If the state stays PENDING, LUMI has no free chip yet; `gagnvist lumi log JOB`
shows the job's messages if it ends on its own.

**Connect to it** (a new terminal; leave it open while you use the model):

```bash
gagnvist lumi connect --job 23292687
```

```text
Your chat server 'Qwen2.5-0.5B-Instruct' (job 23292687) answers at http://127.0.0.1:8801/v1 while the tunnel is open.
To use it, add these lines to .env (and remove them to go back to the shared one):

    GAGNVIST_CHAT_MODEL=Qwen2.5-0.5B-Instruct
    GAGNVIST_CHAT_URL=http://127.0.0.1:8801/v1
    GAGNVIST_CHAT_KEY=...

Opening a tunnel: 127.0.0.1:8801 -> nid005002:...
Connected: http://127.0.0.1:8801/v1 serves Qwen2.5-0.5B-Instruct
```

Put the three lines into `.env`. The key is made for this job alone: every time you
start a server again, replace the three lines with the new ones.

**Check which models answer now:**

```bash
gagnvist try-models
```

```text
Chat model Qwen2.5-0.5B-Instruct answered in 2.9 s: Háls á! (Hello!)
Embedding model bge-m3 answered in 0.2 s: 1024 numbers per text; ...
```

The first word after "Chat model" is the model that answered: your own. The embedding
model is still the shared one, through the shared tunnel. Now `gagnvist ask` and
`gagnvist evaluate` use your chat model; evaluate after every change.

**Stop it** when you are done (a running server costs the same whether anyone uses it
or not), and close its tunnel with Ctrl+C:

```bash
gagnvist lumi stop 23292687
```

To go back to the shared chat model, remove the three `GAGNVIST_CHAT_*` lines from
`.env`.

## 2. Another embedding model

An embedding model turns the question and every table's card into vectors; the search
compares them. Vectors from two models cannot be compared, so a new embedding model
also means a new vector index (a minute or two to build).

**Download and start it**, as for a chat model, but as an `embeddings` server:

```bash
gagnvist lumi download intfloat/multilingual-e5-small
gagnvist lumi start embeddings multilingual-e5-small --partition dev-g --hours 1
gagnvist lumi jobs                       # READY after 83 seconds for this 118M model
gagnvist lumi connect --job 23292658     # a new terminal; prints the three lines below
```

The e5-small download took 2 minutes 42 seconds for 469 MB (and 6 minutes the first
time, when Hugging Face was slow for one file; LUMI's side is quick). The repository
holds the weights twice over, as safetensors and as `.bin`; the download takes the
safetensors only.

**Point the kit to it**, in `.env`: the three lines `connect` printed, and a new folder
for the new index. Keep the shipped index in `index/` as it is, so that removing the
lines brings the shared model back:

```bash
GAGNVIST_EMBEDDINGS_MODEL=multilingual-e5-small
GAGNVIST_EMBEDDINGS_URL=http://127.0.0.1:8802/v1
GAGNVIST_EMBEDDINGS_KEY=...
GAGNVIST_SEARCH_INDEX=local/index-e5small
```

`gagnvist try-models` now says "Embedding model multilingual-e5-small answered in 0.7 s:
384 numbers per text; 'Mannfjöldi á Íslandi' and 'Population of Iceland' have similarity
0.89". Without the `GAGNVIST_SEARCH_INDEX` line, `gagnvist ask` refuses, rightly:

```text
error: the vector index in .../index was made with the embedding model 'bge-m3', but the
settings use 'multilingual-e5-small': add GAGNVIST_SEARCH_INDEX=local/index-mine (or
another new folder) to .env, and run `gagnvist build-vectors` to fill it
```

**Build the new index**, through your server:

```bash
gagnvist build-vectors
```

"Embedded 3,772 cards with multilingual-e5-small into .../local/index-e5small", after
1 minute 27 seconds with e5-small. (If the folder already holds an index,
`build-vectors` refuses; add `--replace` to build it again, or name another folder.)
From here on `gagnvist find-tables`, `ask` and `evaluate` search with your model:
`find-tables "How many people lived in Reykjavík on 1 January 2026?"` put MAN03270
first with e5-small, and `evaluate --only population-reykjavik` gave 1 of 2, the same
as the shared bge-m3.

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
([lumi.md, section 7](lumi.md#7-fine-tuning) has the form). Twenty examples made from
the easy evaluation questions served here as a test; a few hundred good ones are what
makes a difference.

```bash
gagnvist lumi finetune Qwen2.5-0.5B-Instruct train.jsonl --name journey-v1 --partition dev-g --hours 1
```

The file is checked on your computer first ("on 20 conversations"), then uploaded, and
the job submitted: "Submitted job 23292784: fine-tuning Qwen2.5-0.5B-Instruct on 20
conversations (journey-v1)". With the 0.5B model and 20 examples it took 95 seconds
from submission to a saved adapter; `gagnvist lumi log 23292784` showed, after LUMI's
module messages, "20 conversations; training on the GPU", "trainable params: 8,798,208
|| all params: 502,830,976", "epoch 1 step 3/3: loss 2.3103" and "Finished: the adapter
is in .../finetune/journey-v1/adapter".

You may have two jobs at a time (running or waiting). A job you have just stopped no
longer counts, so `finetune` or `start` right after `stop` is accepted.

**Serve it**, with the run's name as the model name:

```bash
gagnvist lumi start chat Qwen2.5-0.5B-Instruct --adapter journey-v1 --partition dev-g --hours 1
gagnvist lumi jobs                       # READY after 110 seconds here
gagnvist lumi connect --job 23292797     # prints GAGNVIST_CHAT_MODEL=journey-v1, _URL, _KEY
```

Put the three lines into `.env` (replacing those of any earlier chat server).
`gagnvist try-models` then names `journey-v1` as the chat model; `ask` answered with
the terse style of the twenty examples, which is what fine-tuning does. Measure with
`gagnvist evaluate`, on questions the model was not trained on.

## 4. Housekeeping

```bash
gagnvist lumi jobs                       # your jobs: PENDING, RUNNING, READY
gagnvist lumi stop JOB                   # end a job, and its cost
gagnvist lumi models                     # your models and fine-tuning runs on LUMI, with sizes
gagnvist lumi delete model NAME          # remove a model you downloaded
gagnvist lumi delete run NAME            # remove a fine-tuning run (its data and adapter)
```

`delete` only touches your own folder on LUMI (`/scratch/<project>/<username>/gagnvist/`),
and refuses to remove a model or adapter that a running server of yours serves: stop the
job first. A deleted model can be downloaded again. The project's disk space is shared
by everyone, so delete what you no longer use.

The organizers see every job of the project, and can end a gagnvist job that should not
run (one left running by mistake, for example). Its log then ends with "The organizers
stopped this job."; your files are not touched. Only you can delete your files, so the
organizers may ask you to run `gagnvist lumi delete`.

## What it took

All of the above, run once with tiny models on `dev-g` (which had free chips):

| Step | Time |
|---|---|
| `lumi download`, 1 GB in 10 files | 13 s |
| `lumi download`, e5-small, 469 MB | 2 min 42 s (6 min once, when Hugging Face was slow) |
| `lumi start` until READY, 118M and 0.5B models | 80 to 110 s |
| `lumi connect --job` until "Connected" | about 10 s |
| `build-vectors`, 3,772 cards with e5-small | 1 min 27 s |
| `lumi finetune`, 20 examples, 0.5B model | 95 s from submission to adapter |
| GPU-hours for the whole walk-through | about 0.15 |

A 7B model takes a few minutes more at each step (download, loading, training), and
fine-tuning on hundreds of examples takes longer in proportion.

## If something is not right

| Message | What to do |
|---|---|
| `try-models` names the shared models, not yours | The three lines are not in `.env`, or `.env` is in another folder than the one you run the commands in. |
| `the vector index in ... was made with the embedding model 'bge-m3', but the settings use ...` | Add `GAGNVIST_SEARCH_INDEX=local/<a new folder>` to `.env` and run `gagnvist build-vectors`. |
| `... already holds a vector index` | Name another folder in `GAGNVIST_SEARCH_INDEX`, or add `--replace`. |
| `your job N serves 'X': stop it first` | `gagnvist lumi stop N`, then delete. |
| `there is no model 'X' on LUMI` | `gagnvist lumi models` lists the exact names. |
| `the connection ... broke off` right after `connect --job` | The job ended (its time was up, or it was stopped): `gagnvist lumi jobs`, `gagnvist lumi log JOB`. |
| The server job ends at once | `gagnvist lumi log JOB`: usually the model does not fit (`--gpus 2`, or a smaller `--context`), or the folder is not a complete model. |
| `job ... is still waiting for a GPU` | LUMI is busy. For a quick test, `--partition dev-g --hours 1`. |
| The log ends with `The organizers stopped this job.` | The organizers ended the job; ask them if you do not know why. |
