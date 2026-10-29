# Setting up on a Mac

From nothing to your first answer, step by step: about 20 minutes, plus a download of
about 300 MB. Do steps 1 to 6 before the hackathon if you can.

**Have ready:** your LUMI username, the SSH key you use for LUMI, your team's key (from
the organizers), and a GitHub account with access to this repository.

Every command below goes into the **Terminal** app: press `Cmd+Space`, type
`Terminal`, and press Enter. Copy each command, paste it, and press Enter.

- [1. Install Python and git](#1-install-python-and-git)
- [2. Download the starter kit](#2-download-the-starter-kit)
- [3. Install it](#3-install-it)
- [4. Fill in your settings](#4-fill-in-your-settings)
- [5. Unpack the data](#5-unpack-the-data)
- [6. Log in to LUMI once by hand](#6-log-in-to-lumi-once-by-hand)
- [7. Connect to the shared models](#7-connect-to-the-shared-models)
- [8. Ask your first question](#8-ask-your-first-question)
- [Every day after that](#every-day-after-that)
- [If something goes wrong](#if-something-goes-wrong)

## 1. Install Python and git

On a new Mac, the first `python3` or `git` command may open a window offering to install
the *command line developer tools*: click **Install**, wait until it is done, and run the
command again.

**Python 3.11 or newer.** Check which one you have:

```bash
python3 --version
```

If it says 3.10 or lower (the Python that comes with macOS is 3.9), install the newest
from [python.org/downloads](https://www.python.org/downloads/): run the installer, then
**close Terminal and open it again**, and check once more. (With Homebrew,
`brew install python` works too.)

**git.** Check it:

```bash
git --version
```

## 2. Download the starter kit

First accept the invitation to the repository that GitHub sent you by e-mail (it
expires after 7 days). Then clone it into your home folder, not into Desktop or Documents
if iCloud syncs them: iCloud would upload the 5.7 GB of data.

```bash
cd ~
git clone https://github.com/SyedMuhammadAzhar/gagnvist-starter.git
cd gagnvist-starter
```

While the repository is private, git asks for your GitHub username and a password. The
password is a **personal access token**, not your GitHub password: make one at
[github.com/settings/tokens](https://github.com/settings/tokens) (*Generate new token
(classic)*, tick *repo*), and paste it when git asks. macOS remembers it.

## 3. Install it

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Your prompt now begins with `(.venv)`: the starter kit's own Python environment is
active in this window. Check that it works:

```bash
gagnvist --help
```

## 4. Fill in your settings

Make your own settings file from the example, and open it in TextEdit:

```bash
cp example.env .env
open -e .env
```

Replace the three example values after the `=` signs (paste them rather than typing:
TextEdit may "correct" what you type), then save (`Cmd+S`) and close TextEdit. If you
prefer the Terminal, `nano .env` works too (save with `Ctrl+O`, Enter, then `Ctrl+X`):

```bash
GAGNVIST_LUMI_USERNAME=your_lumi_username
GAGNVIST_SSH_KEY=~/.ssh/id_ed25519_lumi
GAGNVIST_TEAM_KEY=paste-your-team-key-here
```

| Line | Put there |
|---|---|
| `GAGNVIST_LUMI_USERNAME` | your LUMI username, from the e-mail LUMI sent you |
| `GAGNVIST_SSH_KEY` | the path to the SSH key you use for LUMI: the file **without** `.pub`. `ls ~/.ssh` lists your keys; yours may be called `id_ed25519_lumi`, `id_ed25519` or something else. |
| `GAGNVIST_TEAM_KEY` | your team's key from the organizers: 48 letters and digits, copied exactly, without quote marks or spaces. Your teammate puts the same key in their own `.env`. |

`.env` stays on your computer: git ignores it, so it is never committed or pushed.
(Finder hides files whose names begin with a dot; `Cmd+Shift+.` shows them.)

## 5. Unpack the data

The data comes with the repository: Statistics Iceland's tables in both languages.
Unpack it and index it (a minute or two, and 5.7 GB; `get-data` shows how far it has
come):

```bash
gagnvist get-data
gagnvist build-index
```

## 6. Log in to LUMI once by hand

So that your Mac learns LUMI's identity. Use your own key file and username (here and
below, `~/.ssh/id_ed25519_lumi` stands for your key's file):

```bash
ssh -i ~/.ssh/id_ed25519_lumi your_lumi_username@lumi.csc.fi
```

ssh shows LUMI's *fingerprint* and asks whether to trust it. Check that it is one of
[LUMI's published fingerprints](https://docs.lumi-supercomputer.eu/firststeps/loggingin/):

| Key type | Fingerprint |
|---|---|
| ED25519 | `SHA256:qCFZThjRw8nf0CiZ9rU7b6Zirjq8slAIl5r0xWaVoD0` |
| ECDSA | `SHA256:hY4mnRCYb8bRchTnVcFo7SqoHHHEsUh9Ym38F4sHN1Y` |
| RSA | `SHA256:ypbqdMWtk9ZdXEROkeEpv+3PCEXWjPLGI79IXGHe9ac` |

Then type `yes`, enter your key's passphrase, and once you are logged in, type `exit`.

If you have logged in to LUMI from this Mac before, skip this step.

## 7. Connect to the shared models

First check that everything is in place:

```bash
gagnvist lumi check
```

If your key has a passphrase, it first asks how long to remember it:

```text
Your SSH key has a passphrase, which ssh asks for every time it connects to LUMI.
The SSH agent can remember it for a while, so that ssh stops asking.
For how long? For example 2h, 12h or 2d (at most 7d).
Press Enter for 12h, or type 0 to be asked every time:
```

Type a time, such as `2d` for two days, press Enter, and type your passphrase
once. Until that time is up, nothing asks for it again. (On a shared
computer, choose a short time.)

When it says **All set**, open the tunnel to LUMI, and **leave this window open**:

```bash
gagnvist lumi connect
```

## 8. Ask your first question

Open a **second** Terminal window (`Cmd+N`), and in it:

```bash
cd ~/gagnvist-starter
source .venv/bin/activate
gagnvist ask "How many people live in Reykjavík?"
```

```text
In 2026, the total population of Reykjavík is 139,804.

Source: Statistics Iceland, table MAN03270 "Population in Reykjavík by districts, sex and age 1 January 1998-2026" ...
```

Questions in Icelandic are answered in Icelandic. You are set up: the
[README](../README.md#making-it-better) tells you where to go from here.

## Every day after that

Two Terminal windows:

```bash
# window 1: the tunnel; leave it open
cd ~/gagnvist-starter
source .venv/bin/activate
gagnvist lumi connect
```

```bash
# window 2: your work
cd ~/gagnvist-starter
source .venv/bin/activate
gagnvist ask "..."
```

- Every new window needs `source .venv/bin/activate` again, or `gagnvist` is not found.
- When the time you chose for your passphrase is up, `gagnvist lumi connect` asks again.
- If your Mac sleeps, or the organizers restart the shared models, the tunnel
  reconnects by itself.
- When the organizers announce an update: commit your own changes first (`git add -A`,
  then `git commit -m "our changes"`), then `git pull --no-rebase --no-edit` and
  `pip install -e .`

## If something goes wrong

| Message | What to do |
|---|---|
| `python3 --version` says 3.9 | Install Python from python.org (step 1), then open a new Terminal window. |
| `remote: Repository not found` (step 2) | Accept the invitation that GitHub e-mailed you (it expires after 7 days; ask the organizers for a new one). If git signs in as another GitHub account, delete the `github.com` entry in the *Keychain Access* app, then clone again. |
| `xcrun: error: invalid active developer path` | Run `xcode-select --install`, and try again when it is done. |
| `command not found: gagnvist` | Activate the environment in this window: `cd ~/gagnvist-starter` and `source .venv/bin/activate`. |
| `ssh refuses to use ... because others may read it` / `UNPROTECTED PRIVATE KEY FILE` | `chmod 600 ~/.ssh/id_ed25519_lumi` (your key's file). |
| `Permission denied (publickey)` (step 6) | Check the username and the key file. A key added in MyCSC in the last couple of hours may not have reached LUMI yet. |
| `requires a different Python: 3.9.6 not in '>=3.11'` | `.venv` was made with the old Python: install Python from python.org (step 1), open a new Terminal window, then `cd ~/gagnvist-starter`, `rm -rf .venv`, and step 3 again. |
| `LUMI did not accept the SSH key` | Check the username and key path in `.env`. A key added in MyCSC in the last couple of hours may not have reached LUMI yet. |
| `Connection timed out` (step 6) | The network blocks ssh (port 22): try another one, such as your phone's hotspot. |
| `port 8765 on this computer is already in use` | Add `GAGNVIST_LOCAL_PORT=8790` to `.env`. |
| `the shared models are not running right now` | Tell the organizers. |

Anything else: the full list in [docs/lumi.md](lumi.md#9-troubleshooting).
