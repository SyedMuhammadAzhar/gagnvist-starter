# Using JURECA

[JURECA](https://apps.fz-juelich.de/jsc/hps/jureca/) is the supercomputer of the Jülich
Supercomputing Centre (JSC) in Jülich, Germany, where the hackathon's models run. You
reach it from your own computer with **your own SSH key**: every participant has an
account of their own, and nobody ever shares an SSH key, not with teammates and not with
the organizers. (Your *team key* is different: you and your teammate share it.)

Everything below goes through the `gagnvist jureca` commands, which only run `ssh` for
you. You never need to log in to JURECA yourself, except once at the start, and to store
a Hugging Face token if you want a gated model (section 7).

- [1. Your JURECA account](#1-your-jureca-account)
- [2. Your settings](#2-your-settings)
- [3. Log in once by hand](#3-log-in-once-by-hand)
- [4. Your passphrase](#4-your-passphrase)
- [5. Check your setup](#5-check-your-setup)
- [6. The shared models](#6-the-shared-models)
- [7. Models of your own](#7-models-of-your-own)
- [8. Fine-tuning](#8-fine-tuning)
- [9. Rules, limits and costs](#9-rules-limits-and-costs)
- [10. Troubleshooting](#10-troubleshooting)

## 1. Your JURECA account

Accounts are managed in [JuDoor](https://judoor.fz-juelich.de/), JSC's portal:

1. **Register** in JuDoor.
2. **Join the hackathon's project.** The organizers tell you its name (it is
   `[jureca] project` in `gagnvist.toml`); in JuDoor, ask to join it, and the
   project's manager approves you. JuDoor shows your JURECA username.
3. **Add your SSH key** for JURECA in JuDoor (*Manage SSH-keys*, next to JURECA in the
   project's list of systems). JURECA only accepts a key from the networks its `from=`
   clause names, so paste your **public** key (the file ending in `.pub`) with that
   clause in front of it:

   ```text
   from="130.208.0.0/16" ssh-ed25519 AAAAC3Nz... you@laptop
   ```

   The clause must cover the address you connect from: the range the organizers
   announce for the venue (at the University of Iceland that is `130.208.0.0/16`,
   RHnet, the Icelandic university network) and, to work from home as well, your home
   network's range, separated by a comma. Find your address by asking a search engine
   "what is my IP". **From any other network the key is simply refused** (`Permission
   denied (publickey)`), so list every network you will actually use. A new key works
   within 15 minutes. The starter kit connects to JURECA over IPv4 only, so the clause
   needs only IPv4 ranges; when you log in by hand, use `ssh -4` (section 3), because a
   computer that has IPv6 would otherwise reach JURECA from an IPv6 address, which the
   clause does not name, and be refused.
4. **Only for models of your own** (section 7), two more things, which the shared
   models do not need:
   - **Container access.** In JuDoor: *Software* → *Request access to restricted
     software* → *Access to other restricted software* → *Container Runtime Engine* →
     *Get Access*, and accept the Service Level Description. This puts your account in
     the `container` group, which `gagnvist jureca download` and your own jobs need;
     JSC says it can take some hours to come through.
   - **The project's GPU budget.** A JuDoor project has separate budgets for CPU and
     GPU time (`JURECA-DC_CPU` and `JURECA-DC_GPU`), and the project manager chooses
     which of them each member may use. Without the GPU budget, Slurm refuses every
     GPU job (`Invalid account or account/partition combination specified`): ask the
     organizers to have it added to your membership.

Your username, the path to your **private** key (the file without `.pub`) and your
team's key go in `.env` (section 2): the setup guide for [Mac](setup-mac.md) or
[Windows](setup-windows.md) shows how, step by step.

<details>
<summary>No SSH key yet, or a PuTTY key?</summary>

Make a key pair, and choose a passphrase when it asks for one:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_jureca
```

On Windows, in PowerShell: `mkdir $HOME\.ssh -Force`, then
`ssh-keygen -t ed25519 -f $HOME\.ssh\id_ed25519_jureca`. Register the **public** key
(the file ending in `.pub`) in JuDoor, with the `from=` clause in front of it, as above;
never send anyone the private key.

A key made with PuTTY (`.ppk`) must first be exported: in PuTTYgen, load it and choose
*Conversions*, *Export OpenSSH key*.

</details>

## 2. Your settings

In `.env`, in the starter kit's folder (copy `example.env` to `.env` and fill it in):

```bash
GAGNVIST_JURECA_USERNAME=your_jureca_username
GAGNVIST_JURECA_SSH_KEY=~/.ssh/id_ed25519_jureca
GAGNVIST_TEAM_KEY=paste-your-team-key-here
```

`.env` stays on your computer: git ignores it, so it is never committed or pushed. The
tunnel to the shared models uses port 8775 on your computer; if another program already
uses it, add `GAGNVIST_JURECA_LOCAL_PORT=8790` (or another free port) to `.env`.

## 3. Log in once by hand

```bash
ssh -4 -i ~/.ssh/id_ed25519_jureca your_jureca_username@jureca.fz-juelich.de
```

`-4` makes ssh connect over IPv4, the addresses your key's `from=` clause names (the
starter kit always does). The first time, ssh shows JURECA's *host key fingerprint* and
asks whether to trust it. Check that it matches the fingerprint JuDoor shows next to the
key upload form for JURECA; at the time of writing:

| Key type | Fingerprint |
|---|---|
| ED25519 | `SHA256:IDGkpGi9hxyNBixHDLEXYjLeGLrfNIiuTpcVXu0Lzcc` |
| ECDSA | `SHA256:uqstKzrRZlKMAEOrhy0cMUL7IL3VlqTyei+0mIZ5w5A` |

Then type `yes`, enter your key's passphrase, and once you are logged in, type `exit`.
This protects you from connecting to an impostor.

**A one-time code.** If your JuDoor account has multi-factor authentication enabled,
JURECA asks for a six-digit code from your authenticator app after your key, at every
login. On macOS and Linux the starter kit opens one connection to JURECA and sends every
command and tunnel through it (ssh's *ControlMaster*; it keeps a small socket file in
`~/.ssh/`), so you type the code once; the connection closes after 10 hours without use,
and the next command asks for a code again. Windows' OpenSSH cannot do this, so there
every `gagnvist jureca` command asks for the code, and so does the tunnel each time it
reconnects.

## 4. Your passphrase

ssh asks for your key's passphrase every time it connects to JURECA: for every
`gagnvist jureca` command, and again whenever the tunnel reconnects. Your SSH agent can
remember the unlocked key instead, and `gagnvist jureca check` and
`gagnvist jureca connect` offer to give it the key when it does not hold it yet:

```text
Your SSH key has a passphrase, which ssh asks for every time it connects.
The SSH agent can remember it for a while, so that ssh stops asking.
For how long? For example 2h, 12h or 2d (at most 7d).
Press Enter for 12h, or type 0 to be asked every time: 2d
Enter passphrase for /Users/you/.ssh/id_ed25519_jureca:
Identity added: /Users/you/.ssh/id_ed25519_jureca (you@laptop)
Lifetime set to 172800 seconds
The SSH agent remembers your key for 2d: until then, ssh no longer asks for the passphrase. To make it forget sooner: ssh-add -d /Users/you/.ssh/id_ed25519_jureca
```

You type the passphrase into `ssh-add`, OpenSSH's own program: the starter kit never
sees it. When the time is up, the agent forgets the key, and the next `check` or
`connect` asks again.

- **Windows**: its SSH agent cannot forget a key by itself, so it asks *Remember it?
  [Y/n]* instead, and keeps the key until you remove it, also after a restart. The agent
  must be started once, as administrator ([setup-windows.md, step 2](setup-windows.md#2-start-the-ssh-agent-once-as-administrator)).
- **Linux**: most desktops run an agent; in a terminal without one, start it with
  `eval "$(ssh-agent)"`.
- **To forget your key now** (always on a shared computer): `ssh-add -d` and the path to
  your key; `ssh-add -D` forgets every key.
- **Without an agent** everything still works: ssh asks for the passphrase each time it
  connects, also when the tunnel reconnects, in the terminal where
  `gagnvist jureca connect` runs.

## 5. Check your setup

```bash
gagnvist jureca check
```

It logs in, and tells you whether your account is in the hackathon's project, whether
the shared models are running, and, if they are, whether they accept your team key:

```text
Logging in to jureca.fz-juelich.de as your_jureca_username with the key /Users/you/.ssh/id_ed25519_jureca ...
  You are logged in as your_jureca_username.
  You are a member of the project training2654.
  The shared models are running (on jrc0406).
  Your team key works.
All set. Next: gagnvist jureca connect
```

A line beginning with `PROBLEM` must be fixed first; a line beginning with `NOTE`
concerns models of your own only (the container group, the GPU budget, or the
container the organizers put in the project), and the shared models work anyway. If it
reports a problem, see [Troubleshooting](#10-troubleshooting).

## 6. The shared models

The organizers run a chat model and an embedding model for everyone. To use them,
open a tunnel from your computer to JURECA and **leave that terminal open**:

```bash
gagnvist jureca connect
```

```text
Opening a tunnel: 127.0.0.1:8775 -> jrc0406i:4000 on JURECA
Connected: http://127.0.0.1:8775/v1 serves qwen2.5-7b, bge-m3.
The tunnel stays open until you press Ctrl+C.
```

Work in a second terminal: `gagnvist try-models`, `gagnvist ask "..."`, and so on.
If your laptop sleeps, the tunnel reconnects by itself. If the organizers restart the
shared models, perhaps on another node, the tunnel notices within a minute or two and
follows them; meanwhile commands say that the connection broke off.

The tunnel uses port 8775 on your computer. If another program already uses it, add
`GAGNVIST_JURECA_LOCAL_PORT=8790` (or another free port) to `.env`.

The shared models only answer requests that carry your team key, and you cannot stop
or change them: only the organizers can. They are the same for every team, and their
job costs the same whether you use it or not, so use them as much as you like: that
adds nothing to the hackathon's compute bill. They need neither the `container` group
nor a GPU budget of your own: being a member of the project, with your key, is enough.

## 7. Models of your own

You can also run a model of your own choice, as a job under your own account.
([own-models.md](own-models.md) walks through all of it step by step, with what each
command prints.) This needs the two things from section 1, step 4: the `container`
group and the project's GPU budget. `gagnvist jureca check` tells you if your account
lacks either.

**Download it** (once) from [Hugging Face](https://huggingface.co/models) into your
folder on JURECA, `/p/project1/<project>/<username>/gagnvist/models/`:

```bash
gagnvist jureca download Qwen/Qwen2.5-7B-Instruct
```

The download runs on a login node (the compute nodes have no internet), inside the
project's container, which is why it needs the `container` group. Only the files vLLM
needs are downloaded: other formats of the weights are left out, and so is PyTorch's
older `.bin` format when the repository also has the weights as safetensors. An
interrupted download continues when you run the command again.

Some models need a licence accepted on their Hugging Face page first ("gated"
models, such as Llama). For those, JURECA also needs your Hugging Face
[access token](https://huggingface.co/settings/tokens): log in to JURECA as in
[section 3](#3-log-in-once-by-hand), run the two commands below, paste the token, and
press Enter and then Ctrl+D. Models without a licence step are simpler.

```bash
mkdir -p ~/.cache/huggingface
(umask 077; cat > ~/.cache/huggingface/token)
```

**Start a server** for it. It waits for a free node, then loads the model, which takes
a few minutes:

```bash
gagnvist jureca start chat Qwen2.5-7B-Instruct
gagnvist jureca jobs                     # READY once the model is loaded
gagnvist jureca log 1234567              # the job's log, if something goes wrong
```

**A job always gets a whole node**, with four NVIDIA A100 GPUs of 40 GB each, whether
you ask for `--gpus 1`, `2` or `4` (default 1), and it costs the same either way: 128
core-hours per hour. A 7B model in 16-bit (about 15 GB of weights) fits on one GPU, a
14B model (about 28 GB) fits with less room for long conversations, and a 32B model
needs two or four; the model is split evenly between the GPUs it is given. `--gpus 4`
gives a model the node's whole memory at no extra cost, but a model can only be split
between as many GPUs as its number of attention heads divides by, which a few small
models cannot be split four ways; the job's log says so, and `--gpus 1` or `2` then
works. The other options: `--hours 6` (default 4; 6 is the most), `--context 16384`
(the longest conversation, in tokens; default 8192), and `--partition dc-gpu-devel
--hours 2` for a quick test (dc-gpu-devel often starts sooner, but allows at most 2
hours; JSC keeps it for debugging and short tests, not for real work).

The server answers only requests that carry its key, a random key made for that job
alone: a gatekeeper in front of vLLM checks every request before it gets through.

**Connect to it** when it is READY. The command prints the lines to add to `.env`,
and keeps a tunnel open like `gagnvist jureca connect` does:

```bash
gagnvist jureca connect --job 1234567
```

```bash
GAGNVIST_CHAT_MODEL=Qwen2.5-7B-Instruct
GAGNVIST_CHAT_URL=http://127.0.0.1:8811/v1
GAGNVIST_CHAT_KEY=...
```

The key is a new one, made for this job alone. To go back to the shared chat model,
remove the three lines again.

Keep `gagnvist jureca connect` open in its own terminal as well: `ask` still uses the
shared embedding model (and, with an embedding server of your own, the shared chat
model). That is three terminals: the shared tunnel, your server's tunnel, and your
work. If port 8811 is taken on your computer, `connect --job 1234567 --port 8813`
uses another.

Embedding models work the same way, downloaded first and served on port 8812:

```bash
gagnvist jureca download intfloat/multilingual-e5-large
gagnvist jureca start embeddings multilingual-e5-large
gagnvist jureca connect --job 1234568    # prints GAGNVIST_EMBEDDINGS_MODEL, _URL, _KEY
```

A new embedding model needs a new vector index (`gagnvist build-vectors`, see
[re-embedding.md](re-embedding.md)), since vectors from two models cannot be compared.

**Stop it** as soon as you are done, since a running server costs the same whether
anyone uses it or not:

```bash
gagnvist jureca stop 1234567
```

A teammate's model can be served by giving its full path, for example
`gagnvist jureca start chat /p/project1/<project>/<teammate>/gagnvist/models/<name>`.

**Your files on JURECA**: `gagnvist jureca models` lists your models and fine-tuning
runs with their sizes; `gagnvist jureca delete model <name>` and `gagnvist jureca
delete run <name>` remove one (only in your own folder, and not while a running server
of yours serves it). The project's disk space is shared by everyone: delete what you no
longer use. A deleted model can be downloaded again. Fetch models with
`gagnvist jureca download` rather than copying them there yourself: `download` writes a
`.download-complete` file when it has finished, without which `gagnvist jureca models`
shows the folder as "download not finished" and `start` refuses it, also by its full
path (a folder outside your models folder, such as a teammate's, is taken by its full
path as long as it holds a `config.json`). If you did copy a complete model there
yourself, create that file: `touch <the model folder>/.download-complete` on JURECA.

## 8. Fine-tuning

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
gagnvist jureca finetune Qwen2.5-7B-Instruct train.jsonl --name numbers-v1
gagnvist jureca log 1234568              # how the training is going (run it again for more)
```

Options: `--epochs 2` (passes over the data; default 1), `--rank 32` (LoRA rank: 8,
16, 32 or 64; bigger learns more but needs more data; default 16), `--learning-rate`
(default 0.0002), `--hours` (default 2, at most 6), `--partition dc-gpu-devel` for a
short test.

Fine-tuning needs a training library (peft) that the project's container does not
have. The organizers add it once, in the project; until then the command says so
(`fine-tuning is not available on JURECA yet: ...`) and submits nothing.

When it has finished, serve the model together with the adapter, and use the
adapter's name as the model name:

```bash
gagnvist jureca start chat Qwen2.5-7B-Instruct --adapter numbers-v1
gagnvist jureca connect --job <job id>   # prints GAGNVIST_CHAT_MODEL=numbers-v1 and the rest
```

## 9. Rules, limits and costs

- **Limits** that the starter kit sets, so that no team can use up the budget: at most 2
  jobs at a time for each person (so 4 for a team of two), at most 6 hours per job (2
  hours on `dc-gpu-devel`). A job counts while it waits or runs; one you have just
  stopped no longer does, so the next `start` or `finetune` is accepted at once.
- **Cost**: every job is billed for its whole node, 128 core-hours per hour, busy or
  idle, until it ends, however many of its four GPUs it uses. `gagnvist jureca start`
  tells you the most a job can cost. Stop what you do not use.
- **`dc-gpu-devel` is for quick tests.** JSC keeps it for debugging and short tests, at
  most 2 hours per job.
- **No internet on the compute nodes.** Everything a job needs must be downloaded
  first, on a login node: `gagnvist jureca download` does that.
- **Login nodes are shared** by every user of JURECA: use them for the commands, not
  for computing.
- **You can only stop your own jobs.** Slurm, JURECA's job system, refuses to cancel
  anybody else's, including the shared models. The organizers can end a gagnvist job of
  anyone's, though (one left running by mistake, for example): the job ends itself when
  a file named after it appears in the organizers' folder of stop files, and its log
  ends with "The organizers stopped this job." Your files are not touched.
- **What others can see.** Everyone on JURECA can see the names and nodes of all jobs.
  Your models and adapters, under `/p/project1/<project>/<username>/gagnvist/`, can be
  read by the other members of the project (your teammates, and the other teams) but
  changed only by you. Your job logs and the keys of your servers are in `~/.gagnvist/`
  in your home folder, which only you can read.

## 10. Troubleshooting

| Message | What to do |
|---------|------------|
| `JURECA did not accept the SSH key` / `Permission denied (publickey)` | Check `GAGNVIST_JURECA_USERNAME` and `GAGNVIST_JURECA_SSH_KEY` in `.env`. Is your current network in the key's `from=` clause ("what is my IP")? Logging in by hand, did you use `ssh -4` (section 3)? A key added in the last 15 minutes may not work yet. |
| `JURECA accepted your key, then asked for a one-time code` / `Permission denied (keyboard-interactive)` | Your account has multi-factor authentication: log in once by hand (section 3), or run `gagnvist jureca check` in a terminal, and type the code from your authenticator app. |
| `jureca.fz-juelich.de could not be found: are you connected to the internet?` | Check your network connection. |
| `set ... in .env` | Copy `example.env` to `.env`, in the starter kit's folder, and fill in its values. |
| `.env, line ...: expected NAME=value` | A line of `.env` is misspelt: compare it with `example.env`. |
| `ssh refuses to use ... because others may read it` / `UNPROTECTED PRIVATE KEY FILE` | On macOS or Linux: `chmod 600 ~/.ssh/id_ed25519_jureca`. On Windows, in PowerShell: `icacls $HOME\.ssh\id_ed25519_jureca /inheritance:r /grant:r "$(whoami):R"`. |
| `ssh cannot read the key` | `GAGNVIST_JURECA_SSH_KEY` must be the private key (not the `.pub` file), in OpenSSH format (a PuTTY `.ppk` key must be exported first, see [section 1](#1-your-jureca-account)). |
| `refused the key` / `GAGNVIST_TEAM_KEY ... has N characters` | Copy your team key into `.env` again: 48 letters and digits, without quote marks or spaces. The tunnel can stay open. |
| `.env is saved as UTF-16` / `is not saved as UTF-8` | Save `.env` again with the encoding UTF-8 (Notepad: *File*, *Save as*, *Encoding*). |
| `found .env.txt but no .env` | Rename the file to `.env`. |
| `running scripts is disabled` (PowerShell) | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned -Force`, then activate again. |
| `gagnvist: command not found` / `command not found: gagnvist` / `not recognized` | Activate the environment in this terminal: `source .venv/bin/activate` (Windows: `.venv\Scripts\activate`). |
| `the connection ... broke off` | The shared models may have been restarted: `gagnvist jureca connect` follows them within a minute or two; if not, stop it with Ctrl+C and start it again. |
| `channel 1: open failed: connect failed: Connection refused` (in the `jureca connect` terminal) | Nothing to do: the shared models were being restarted, and the tunnel waits for them. Ask again once they answer. |
| `the model server cannot answer yet` / `still loading` | The shared models are starting, or one was restarted after a crash; that takes one or two minutes. Ask again in a minute. |
| `the model server is busy` | The shared models have too many requests from your team in progress; wait, or send fewer at a time from your own code. |
| `too deep for Windows` | Clone the starter kit again into a short folder, such as `C:\gagnvist-starter`, and set it up there ([setup-windows.md](setup-windows.md), steps 3 to 6). A folder that is set up cannot simply be moved: its `.venv` remembers where it was. |
| `could not verify the identity of jureca.fz-juelich.de` | Log in once by hand (section 3). |
| `No SSH agent runs in this terminal` / `Windows' SSH agent ... is not running` | macOS and Linux: `eval "$(ssh-agent)"` in that terminal. Windows: start the agent once as administrator ([setup-windows.md, step 2](setup-windows.md#2-start-the-ssh-agent-once-as-administrator)). Or do nothing: ssh then asks for your passphrase each time. |
| `Your key was not remembered` | A mistyped passphrase: run `gagnvist jureca check` again. If `ssh-add` said the agent refused, your agent cannot forget a key by itself: `ssh-add` and the path to your key make it remember the key until you remove it. |
| `the ssh program was not found` | Windows 11: *Settings*, *System*, *Optional features*, *View features*, then *OpenSSH Client*. Windows 10: *Settings*, *Apps*, *Optional features*, *Add a feature*, then *OpenSSH Client*. Linux: install `openssh-client`. |
| `kex_exchange_identification` / `Connection reset by peer` / `Connection closed by ... port 22` | The login node dropped the connection, for example when many people connect at the same moment: run the command again in a few seconds. (Once its tunnel is open, `gagnvist jureca connect` reconnects by itself.) |
| `your account is not (yet) a member of the project` | Ask to join the project in JuDoor, and wait for the manager's approval; ask the organizers if it does not come. |
| `the project folder ... cannot be seen` | Tell the organizers. |
| `NOTE: your account is not in the group 'container' yet` / `is not in group container` (apptainer, in a job's log) | Request the *Container Runtime Engine* in JuDoor (section 1, step 4); `download` and your own jobs need it; the shared models work meanwhile. |
| `NOTE: your account cannot use the GPU partitions of ... yet` / `Slurm refused the job: your account cannot use that partition` | Your membership lacks the project's GPU budget (section 1, step 4): ask the organizers; the shared models work meanwhile. |
| `NOTE: the container for jobs of your own is not there (yet)` | The organizers have not put the container on JURECA yet: `download`, `start` and `finetune` wait for it; the shared models work anyway. |
| `fine-tuning is not available on JURECA yet` | The organizers have not added the training library (section 8); ask them. |
| `the shared models are not running right now` | Tell the organizers. |
| `port 8775 on this computer is already in use` | The message says whether it is a tunnel left open (and how to stop it) or another program. Or add `GAGNVIST_JURECA_LOCAL_PORT=8790` to `.env`. |
| `this computer does not let programs use port ...` | Windows reserves that port: add `GAGNVIST_JURECA_LOCAL_PORT=8790` (or another port) to `.env`. |
| `job ... is still waiting for a GPU` | JURECA is busy; the job starts when a node is free. For a quick test only, `--partition dc-gpu-devel --hours 2` (or fewer hours) often starts sooner. |
| `job ... is still loading its model` | Wait a minute. If it takes longer than about ten minutes, look at `gagnvist jureca log JOB`. |
| A server job ends at once | `gagnvist jureca log JOB` shows why: often the model does not fit (try `--gpus 2` or `4`, or a shorter `--context`), or it cannot be split between that many GPUs (fewer `--gpus`), or the folder is not a complete model, or apptainer refuses because your account is not in the `container` group yet. |
| `you already have 2 gagnvist jobs` | `gagnvist jureca jobs`, then `gagnvist jureca stop JOB` for one you do not need (a stopped job no longer counts). |
| `your job ... serves '...': stop it first` | A running server of yours uses the model or adapter you want to delete: `gagnvist jureca stop JOB`, then delete. |
| `... was not found on JURECA` / `there is no model '...' on JURECA` / `there is no run '...'` | `gagnvist jureca models` lists the exact names. |
| `the download of ... did not finish` | Run `gagnvist jureca download` again for that model; it continues where it stopped. |
| A job's log ends with `The organizers stopped this job.` | The organizers ended it (see section 9); ask them if you do not know why. |
| `... is not a folder of yours` | Someone else created or replaced a folder where your files belong. Tell the organizers; nothing was run or stored there. |
| `Slurm, JURECA's job system, did not answer` | JURECA is busy; try again in a minute. |
| `Slurm refused the job: ...` (anything else) | The rest of the line is Slurm's own message; ask the organizers if it is not clear. |
| `is not valid TOML` | `gagnvist.toml` was changed by mistake: `git checkout gagnvist.toml` brings back the original. |
