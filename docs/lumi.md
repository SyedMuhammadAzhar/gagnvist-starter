# Using LUMI

LUMI is the supercomputer in Kajaani, Finland, where the hackathon's models run. You
reach it from your own computer with **your own SSH key**: every participant has an
account of their own, and nobody ever shares a key, not with teammates and not with
the organizers.

Everything below goes through the `gagnvist lumi` commands, which only run `ssh` for
you. You never need to log in to LUMI yourself, except once at the start.

- [1. Your LUMI account](#1-your-lumi-account)
- [2. Log in once by hand](#2-log-in-once-by-hand)
- [3. Type your passphrase once a day](#3-type-your-passphrase-once-a-day)
- [4. Check your setup](#4-check-your-setup)
- [5. The shared models](#5-the-shared-models)
- [6. Models of your own](#6-models-of-your-own)
- [7. Fine-tuning](#7-fine-tuning)
- [8. Rules, limits and costs](#8-rules-limits-and-costs)
- [9. Troubleshooting](#9-troubleshooting)

## 1. Your LUMI account

The organizers invite you to the hackathon's LUMI project. To accept:

1. Make a key pair (press Enter to accept the file name, and choose a passphrase):

   ```bash
   ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_lumi
   ```

   On Windows, in PowerShell: `mkdir $HOME\.ssh -Force`, then
   `ssh-keygen -t ed25519 -f $HOME\.ssh\id_ed25519_lumi`. A key made with PuTTY
   (`.ppk`) must first be exported: in PuTTYgen, load it and choose *Conversions*,
   *Export OpenSSH key*.

2. Register the **public** key (the file ending in `.pub`) in your
   [MyAccessID profile](https://mms.myaccessid.org/): *Settings*, *SSH keys*,
   *New key*. Never send anyone the private key (the file without `.pub`).

3. Wait for the e-mail with your LUMI username. A new key can take a couple of hours
   to reach LUMI.

Then copy `example.env` to `.env`, in the starter kit's folder, and fill it in: your
username from the e-mail, the path to your private key (on Windows, for example
`C:\Users\you\.ssh\id_ed25519_lumi`), and the key your team was given:

```bash
GAGNVIST_LUMI_USERNAME=your_lumi_username
GAGNVIST_SSH_KEY=~/.ssh/id_ed25519_lumi
GAGNVIST_TEAM_KEY=...
```

`.env` stays on your computer: git ignores it, so it is never committed or pushed.

## 2. Log in once by hand

```bash
ssh -i ~/.ssh/id_ed25519_lumi your_lumi_username@lumi.csc.fi
```

The first time, ssh shows LUMI's *host key fingerprint* and asks whether to trust it.
Check that it matches one of the fingerprints
[published by LUMI](https://docs.lumi-supercomputer.eu/firststeps/loggingin/) (for
the ED25519 key: `SHA256:qCFZThjRw8nf0CiZ9rU7b6Zirjq8slAIl5r0xWaVoD0`), type `yes`,
and then `exit`. This protects you from connecting to an impostor.

## 3. Type your passphrase once a day

Every `gagnvist lumi` command connects with ssh, and ssh asks for your key's
passphrase each time. Give the key to your SSH agent once and it stops asking:

| System  | Command |
|---------|---------|
| macOS   | `ssh-add --apple-use-keychain ~/.ssh/id_ed25519_lumi` |
| Linux   | `ssh-add ~/.ssh/id_ed25519_lumi` (if it says there is no agent: `eval "$(ssh-agent)"` first) |
| Windows | `ssh-add $HOME\.ssh\id_ed25519_lumi` (the first time, start the agent in PowerShell *as administrator*: `Get-Service ssh-agent \| Set-Service -StartupType Automatic; Start-Service ssh-agent`) |

Without an agent (on Windows it needs administrator rights once), everything still
works: ssh asks for the passphrase each time it connects, also when the tunnel
reconnects, in the terminal where `gagnvist lumi connect` runs.

## 4. Check your setup

```bash
gagnvist lumi check
```

It logs in, and tells you whether your account is in the hackathon's project, whether
the shared models are running, and, if they are, whether they accept your team key. If
it reports a problem, see [Troubleshooting](#9-troubleshooting).

## 5. The shared models

The organizers run a chat model and an embedding model for everyone. To use them,
open a tunnel from your computer to LUMI and **leave that terminal open**:

```bash
gagnvist lumi connect
```

```text
Opening a tunnel: 127.0.0.1:8765 -> nid005123:4000 on LUMI
Connected: http://127.0.0.1:8765/v1 serves qwen2.5-7b, bge-m3.
The tunnel stays open until you press Ctrl+C.
```

Work in a second terminal: `gagnvist try-models`, `gagnvist ask "..."`, and so on.
If your laptop sleeps, the tunnel reconnects by itself. If the organizers restart the
shared models, perhaps on another node, the tunnel notices within about two minutes and
follows them; meanwhile commands say that the connection broke off.

The tunnel uses port 8765 on your computer. If another program already uses it (the
Anki add-on AnkiConnect does, for example), add `GAGNVIST_LOCAL_PORT=8790` (or another
free port) to `.env`.

The shared models only answer requests that carry your team key, and you cannot stop
or change them: only the organizers can. They are the same for every team, so you can
use them as much as you like without touching your team's GPU budget.

## 6. Models of your own

You can also run a model of your own choice, as a job under your own account.

**Download it** (once) from [Hugging Face](https://huggingface.co/models) into your
folder on LUMI, `/scratch/<project>/<username>/gagnvist/models/`:

```bash
gagnvist lumi download Qwen/Qwen2.5-7B-Instruct
```

Some models need a licence accepted on their Hugging Face page first ("gated"
models, such as Llama). For those, LUMI also needs your Hugging Face
[access token](https://huggingface.co/settings/tokens): log in to LUMI as in
[step 2](#2-log-in-once-by-hand), run the two commands below, paste the token, and
press Enter and then Ctrl+D. Models without a licence step are simpler.

```bash
mkdir -p ~/.cache/huggingface
(umask 077; cat > ~/.cache/huggingface/token)
```

**Start a server** for it. It waits for a free GPU, then loads the model, which takes
a few minutes:

```bash
gagnvist lumi start chat Qwen2.5-7B-Instruct
gagnvist lumi jobs                       # READY once the model is loaded
gagnvist lumi log 1234567                # the job's log, if something goes wrong
```

Options: `--gpus 2` or `--gpus 4` for a model that does not fit on one GPU chip (each
has 64 GB: enough for a 7B or 14B model in 16-bit; a 32B model needs 2 or 4; the model
is split evenly between them), `--hours 8` (default 4), `--context 16384` (the longest
conversation, in tokens; default 8192), and `--partition dev-g` for a quick test (it
starts sooner but allows at most 3 hours).

The server answers only requests that carry its key, a random key made for that job
alone: a gatekeeper in front of vLLM checks every request before it gets through.

**Connect to it** when it is READY. The command prints the lines to add to `.env`,
and keeps a tunnel open like `gagnvist lumi connect` does:

```bash
gagnvist lumi connect --job 1234567
```

```bash
GAGNVIST_CHAT_MODEL=Qwen2.5-7B-Instruct
GAGNVIST_CHAT_URL=http://127.0.0.1:8801/v1
GAGNVIST_CHAT_KEY=...
```

The key is a new one, made for this job alone. To go back to the shared chat model,
remove the three lines again.

Embedding models work the same way: `gagnvist lumi start embeddings bge-m3`, and then
`GAGNVIST_EMBEDDINGS_MODEL`, `GAGNVIST_EMBEDDINGS_URL` and `GAGNVIST_EMBEDDINGS_KEY` in
`.env`. A new embedding model needs a new vector index (`gagnvist build-vectors`, see
[re-embedding.md](re-embedding.md)), since vectors from two models cannot be compared.

**Stop it** as soon as you are done, since a running server costs the same whether
anyone uses it or not:

```bash
gagnvist lumi stop 1234567
```

A teammate's model can be served by giving its full path, for example
`gagnvist lumi start chat /scratch/<project>/<teammate>/gagnvist/models/<name>`.

## 7. Fine-tuning

You can teach a model your own examples with LoRA, which trains a small *adapter*
(tens of megabytes) instead of the whole model. Write the examples as a
[JSON Lines](https://jsonlines.org/) file: one conversation per line, ending with the
answer the model should learn to give.

```json
{"messages": [{"role": "user", "content": "How many people lived in Iceland in 2024?"}, {"role": "assistant", "content": "In 2024, 383726 people lived in Iceland."}]}
```

A `system` message may come first. The model learns from the last message only; the
ones before it are the context. A few hundred good examples go a long way.

```bash
gagnvist lumi finetune Qwen2.5-7B-Instruct train.jsonl --name numbers-v1
gagnvist lumi log 1234568                # follow the training
```

Options: `--epochs 2` (passes over the data; default 1), `--rank 32` (LoRA rank, 8 to
64: bigger learns more but needs more data; default 16), `--learning-rate`, `--hours`.

When it has finished, serve the model together with the adapter, and use the
adapter's name as the model name:

```bash
gagnvist lumi start chat Qwen2.5-7B-Instruct --adapter numbers-v1
gagnvist lumi connect --job <job id>     # prints GAGNVIST_CHAT_MODEL=numbers-v1 and the rest
```

## 8. Rules, limits and costs

- **Limits** (so that no team can use up the budget): at most 2 jobs at a time, at most
  4 GPU chips per job, at most 12 hours per job (3 hours on `dev-g`).
- **Cost**: every GPU chip costs 0.5 GPU-hours per hour, busy or idle, until its job
  ends. `gagnvist lumi start` tells you the most a job can cost. Stop what you do not
  use.
- **You can only stop your own jobs.** Slurm, LUMI's job system, refuses to cancel
  anybody else's, including the shared models.
- **What others can see.** Everyone on LUMI can see the names, sizes and nodes of all
  jobs. Your models, training data and adapters, under
  `/scratch/<project>/<username>/gagnvist/`, can be read by the other members of the
  project (your teammates, and the other teams) but changed only by you. Your job logs
  and the keys of your servers are in `~/.gagnvist/` in your home folder, which only
  you can read.

## 9. Troubleshooting

| Message | What to do |
|---------|------------|
| `LUMI did not accept the SSH key` | Check `GAGNVIST_LUMI_USERNAME` and `GAGNVIST_SSH_KEY` in `.env`. A key added to MyAccessID in the last few hours may not have reached LUMI yet. |
| `set ... in .env` | Copy `example.env` to `.env`, in the starter kit's folder, and fill in its values. |
| `.env, line ...: expected NAME=value` | A line of `.env` is misspelt: compare it with `example.env`. |
| `ssh refuses to use ... because others may read it` | On macOS or Linux: `chmod 600 ~/.ssh/id_ed25519_lumi`. On Windows, in PowerShell: `icacls $HOME\.ssh\id_ed25519_lumi /inheritance:r /grant:r "$($env:USERNAME):R"`. |
| `ssh cannot read the key` | `GAGNVIST_SSH_KEY` must be the private key (not the `.pub` file), in OpenSSH format (a PuTTY `.ppk` key must be exported first, see [step 1](#1-your-lumi-account)). |
| `refused the key` / `GAGNVIST_TEAM_KEY ... has N characters` | Copy your team key into `.env` again: 48 letters and digits, without quote marks or spaces. The tunnel can stay open. |
| `.env is saved as UTF-16` / `is not saved as UTF-8` | Save `.env` again with the encoding UTF-8 (Notepad: *File*, *Save as*, *Encoding*). |
| `found .env.txt but no .env` | Rename the file to `.env`. |
| `running scripts is disabled` (PowerShell) | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, then activate again. |
| `gagnvist: command not found` / `not recognized` | Activate the environment in this terminal: `source .venv/bin/activate` (Windows: `.venv\Scripts\activate`). |
| `the connection ... broke off` | The shared models may have been restarted: `gagnvist lumi connect` follows them within a couple of minutes; if not, stop it with Ctrl+C and start it again. |
| `channel 1: open failed: connect failed: Connection refused` (in the `lumi connect` terminal) | Nothing to do: the shared models were being restarted, and the tunnel waits for them. Ask again once they answer. |
| `the model server cannot answer yet` / `still loading` | The shared models are starting, or one was restarted after a crash; that takes one or two minutes. Ask again in a minute. |
| `the model server is busy` | Your team already has 8 requests in progress; wait, or send fewer at a time from your own code. |
| `too deep for Windows` | Move the starter kit to a short folder, such as `C:\gagnvist-starter`, and run `gagnvist get-data` again. |
| `could not verify the identity of lumi.csc.fi` | Log in once by hand ([step 2](#2-log-in-once-by-hand)). |
| `the ssh program was not found` | Windows: *Settings*, *Apps*, *Optional features*, add *OpenSSH Client*. Linux: install `openssh-client`. |
| `your account is not (yet) a member of the project` | Accept the invitation to the project; ask the organizers if it does not arrive. |
| `the shared models are not running right now` | Tell the organizers. |
| `port 8765 on this computer is already in use` | The message says whether it is a tunnel left open (and how to stop it) or another program. Or add `GAGNVIST_LOCAL_PORT=8790` to `.env`. |
| `this computer does not let programs use port ...` | Windows reserves that port: add `GAGNVIST_LOCAL_PORT=8790` (or another port) to `.env`. |
| `job ... is still waiting for a GPU` | LUMI is busy; it starts when a GPU is free. `--partition dev-g` starts sooner for jobs of at most 3 hours. |
| `job ... is still loading its model` | Wait a minute. If it takes longer than about ten minutes, look at `gagnvist lumi log JOB`. |
| A server job ends at once | `gagnvist lumi log JOB` shows why: often the model does not fit (try `--gpus 2` or a shorter `--context`), or the folder is not a complete model. |
| `you already have 2 gagnvist jobs` | `gagnvist lumi jobs`, then `gagnvist lumi stop JOB` for one you do not need. |
| `... is not a folder of yours` | Someone else created or replaced a folder where your files belong. Tell the organizers; nothing was run or stored there. |
| `Slurm, LUMI's job system, did not answer` | LUMI is busy; try again in a minute. |
| `is not valid TOML` | `gagnvist.toml` was changed by mistake: `git checkout gagnvist.toml` brings back the original. |
