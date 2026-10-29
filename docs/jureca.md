# Using JURECA

The hackathon's models run on LUMI. When the organizers say so, the same two models
also run on [JURECA](https://apps.fz-juelich.de/jsc/hps/jureca/), the supercomputer of
the Jülich Supercomputing Centre in Germany, so that one can stand in for the other. Everything
you can do on LUMI you can do on JURECA, with the same commands: `gagnvist jureca
check`, `gagnvist jureca connect`, `gagnvist jureca start ...`, and so on. This guide
covers what is different; [docs/lumi.md](lumi.md) explains the rest.

As on LUMI, you reach the shared models through a tunnel from your own account, so
you need a JURECA account too. Nobody ever shares an SSH key, and the private key never
leaves your computer.

- [1. Your JURECA account](#1-your-jureca-account)
- [2. Your settings](#2-your-settings)
- [3. Log in once by hand](#3-log-in-once-by-hand)
- [4. The shared models](#4-the-shared-models)
- [5. Models of your own](#5-models-of-your-own)
- [6. Rules, limits and costs](#6-rules-limits-and-costs)
- [7. Troubleshooting](#7-troubleshooting)

## 1. Your JURECA account

Accounts are managed in [JuDoor](https://judoor.fz-juelich.de/), JSC's portal:

1. **Register** in JuDoor.
2. **Join the hackathon's project.** The organizers tell you its name (it is
   `[jureca] project` in `gagnvist.toml`); in JuDoor, ask to join it, and the
   project's manager approves you.
3. **Add your SSH key** for JURECA in JuDoor (the key upload form for JURECA, on the
   project's page). JURECA only accepts a key from the networks its `from=` clause
   names, so paste the key with that clause in front of it:

   ```text
   from="130.208.0.0/16" ssh-ed25519 AAAAC3Nz... you@laptop
   ```

   The clause must cover the address you connect from: the range the organizers
   announce for the venue (at the University of Iceland that is `130.208.0.0/16`,
   RHnet, the Icelandic university network) and, to work from home as well, your home
   network's range, separated by a comma. Find your address by asking a search engine
   "what is my IP". **From any other network the key is simply refused** (`Permission
   denied (publickey)`), so list every network you will actually use. Make an ed25519
   key if you have none (`ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_jureca`, with a
   passphrase). A new key works after about 15 minutes.
4. **Only for models of your own** (section 5), two more things, which the shared
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

## 2. Your settings

Add to `.env`, next to the LUMI lines:

```bash
GAGNVIST_JURECA_USERNAME=your_jureca_username
GAGNVIST_JURECA_SSH_KEY=~/.ssh/id_ed25519_jureca
```

The team key is the same as for LUMI. Whose shared models the commands use is
`GAGNVIST_CLUSTER` in `.env`: `lumi` unless you set it, or `jureca`. One command at a
time can be sent to the other supercomputer with `--cluster`:

```bash
gagnvist ask --cluster jureca "How many people live in Reykjavík?"
gagnvist evaluate --cluster jureca
```

Both tunnels can be open at the same time (LUMI's on port 8765, JURECA's on 8775), so
switching is one word.

## 3. Log in once by hand

```bash
ssh -i ~/.ssh/id_ed25519_jureca your_jureca_username@jureca.fz-juelich.de
```

The first time, ssh shows JURECA's host key fingerprint and asks whether to trust it.
Check that it matches the fingerprint JuDoor shows next to the key upload form for
JURECA; at the time of writing:

| Key type | Fingerprint |
|---|---|
| ED25519 | `SHA256:IDGkpGi9hxyNBixHDLEXYjLeGLrfNIiuTpcVXu0Lzcc` |
| ECDSA | `SHA256:uqstKzrRZlKMAEOrhy0cMUL7IL3VlqTyei+0mIZ5w5A` |

Then type `yes`, enter your key's passphrase, and once you are logged in, type `exit`.

**A one-time code.** If your JuDoor account has multi-factor authentication enabled,
JURECA asks for a six-digit code from your authenticator app after your key, at every
login. The starter kit opens one connection to JURECA and sends every command and
tunnel through it for 10 hours, so you type the code once per day (ssh's
*ControlMaster*; it keeps a small socket file in `~/.ssh/`). Windows' OpenSSH cannot
do this, so there every `gagnvist jureca` command asks for the code.

## 4. The shared models

```bash
gagnvist jureca check                    # logged in? in the project? team key accepted?
gagnvist jureca connect                  # the tunnel; leave this window open
```

`connect` prints the same lines as on LUMI (`Opening a tunnel: 127.0.0.1:8775 -> ...
on JURECA`, then `Connected: http://127.0.0.1:8775/v1 serves qwen2.5-7b, bge-m3.`)
and stays open until you press Ctrl+C. Then, in a second window, with `GAGNVIST_CLUSTER=jureca` in `.env` or `--cluster
jureca` on each command: `gagnvist try-models`, `gagnvist ask "..."`,
`gagnvist evaluate`. The models are the same as on LUMI, under the same names, so the
vector index that comes with the starter kit works with both. The shared models need
neither the `container` group nor a GPU budget of your own: being a member of the
project, with your key, is enough.

## 5. Models of your own

As on LUMI ([docs/lumi.md, section 6](lumi.md#6-models-of-your-own)): download a
model once, start a server for it, connect to it, stop it.

```bash
gagnvist jureca download Qwen/Qwen2.5-7B-Instruct
gagnvist jureca start chat Qwen2.5-7B-Instruct --hours 2
gagnvist jureca jobs                     # READY once the model is loaded
gagnvist jureca connect --job 1234567    # prints the lines for .env
gagnvist jureca stop 1234567
```

What is different:

- **A job always gets a whole node**, with four NVIDIA A100 GPUs, whether you ask for
  `--gpus 1`, `2` or `4`. It costs the same either way: 128 core-hours per hour.
- **Two jobs at a time** for each person, as on LUMI — a chat model and an embedding
  model — but each is a whole node, so two cost 256 core-hours per hour. At most 6
  hours per job, or 2 on `dc-gpu-devel` (`--partition dc-gpu-devel`), which often
  starts sooner and is meant for short tests (JURECA itself allows 2 running jobs
  there).
- **Downloads happen on a login node**, as on LUMI, because the compute nodes have no
  internet. Your models go to `/p/project1/<project>/<username>/gagnvist/models/`;
  `gagnvist jureca download` prints the path.
- **Downloading and running containers needs the *Container Runtime Engine* access,
  and a GPU job needs the project's GPU budget** (section 1, step 4). `gagnvist jureca
  check` tells you if your account lacks either. Without the GPU budget, `start` is
  refused by Slurm and says so; without container access, `download` fails and a job
  stops at once (`gagnvist jureca log JOB` shows apptainer's refusal).
- Fine-tuning (`gagnvist jureca finetune`) works the same way; the adapter is served
  with `gagnvist jureca start chat <model> --adapter <run>`.

Tunnels to your own servers on JURECA use ports 8811 (chat) and 8812 (embeddings) on
your computer, so that they can be open next to LUMI's (8801, 8802).

## 6. Rules, limits and costs

- **Cost:** a job is billed for its whole node, 128 core-hours per hour, busy or idle,
  until it ends, however many of its GPUs it uses. Stop what you do not use.
- **Limits** that the starter kit sets, so that no team can use up the budget: at most 2
  jobs at a time for each person, at most 6 hours per job (2 on `dc-gpu-devel`).
- **`dc-gpu-devel` is for tests.** JSC keeps it for debugging and short tests, at most
  2 hours per job.
- **No internet on the compute nodes.** Everything a job needs must be downloaded
  first, on a login node.
- **Login nodes are shared** by every user of JURECA: use them for the commands, not
  for computing.
- **What others can see.** Everyone on JURECA can see the names and nodes of all jobs.
  Your models and adapters, in your folder in the project, can be read by the other
  members of the project but changed only by you; the keys of your servers are in
  `~/.gagnvist/` in your home folder, which only you can read.

## 7. Troubleshooting

| Message | What to do |
|---------|------------|
| `JURECA did not accept the SSH key` / `Permission denied (publickey)` | Check `GAGNVIST_JURECA_USERNAME` and `GAGNVIST_JURECA_SSH_KEY` in `.env`. Is your current network in the key's `from=` clause ("what is my IP")? A key added in the last 15 minutes may not work yet. |
| `JURECA accepted your key, then asked for a one-time code` / `Permission denied (keyboard-interactive)` | Your account has multi-factor authentication: log in once by hand (section 3), or run `gagnvist jureca check` in a terminal, and type the code from your authenticator app. |
| `your account is not (yet) a member of the project` | Ask to join the project in JuDoor, and wait for the manager's approval; ask the organizers if it does not come. |
| `NOTE: your account is not in the group 'container' yet` / `not authorized to use apptainer` | Request the *Container Runtime Engine* in JuDoor (section 1, step 4); `download` and your own jobs need it; the shared models work meanwhile. |
| `NOTE: your account cannot use the GPU partitions of ... yet` / `Slurm refused the job: your account cannot use that partition` | Your membership lacks the project's GPU budget (section 1, step 4): ask the organizers; the shared models work meanwhile. |
| `could not verify the identity of jureca.fz-juelich.de` | Log in once by hand (section 3). |
| `port 8775 on this computer is already in use` | Add `GAGNVIST_JURECA_LOCAL_PORT=8791` (or another free port) to `.env`. |
| `the shared models are not running right now` | Tell the organizers; meanwhile use LUMI's (`gagnvist lumi connect`, and `--cluster lumi` or `GAGNVIST_CLUSTER=lumi`). |
| `job ... is still waiting for a GPU` | JURECA is busy; `--partition dc-gpu-devel --hours 2` (or fewer) often starts sooner, for a test. |

Anything about ssh, keys, `.env` or the tunnel that is not here: the
[LUMI troubleshooting table](lumi.md#9-troubleshooting) applies to JURECA too.
