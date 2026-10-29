# Setting up on Windows

From nothing to your first answer, step by step: about 20 minutes, plus a download of
about 300 MB. Do steps 1 to 7 before the hackathon if you can. Windows 10 or 11.

**Have ready:** your LUMI username, the SSH key you use for LUMI, your team's key (from
the organizers), and a GitHub account with access to this repository.

Every command below goes into **PowerShell**: open the Start menu, type `PowerShell`,
and click *Windows PowerShell*. Copy each command, paste it (right-click pastes), and
press Enter. Use PowerShell: the commands below are written for it, and Git Bash or
Command Prompt would need different ones.

- [1. Install Python, git and OpenSSH](#1-install-python-git-and-openssh)
- [2. Start the SSH agent (once, as administrator)](#2-start-the-ssh-agent-once-as-administrator)
- [3. Download the starter kit](#3-download-the-starter-kit)
- [4. Install it](#4-install-it)
- [5. Fill in your settings](#5-fill-in-your-settings)
- [6. Unpack the data](#6-unpack-the-data)
- [7. Log in to LUMI once by hand](#7-log-in-to-lumi-once-by-hand)
- [8. Connect to the shared models](#8-connect-to-the-shared-models)
- [9. Ask your first question](#9-ask-your-first-question)
- [Every day after that](#every-day-after-that)
- [If something goes wrong](#if-something-goes-wrong)

## 1. Install Python, git and OpenSSH

**Python 3.11 or newer**: on [python.org/downloads/windows](https://www.python.org/downloads/windows/),
click **Windows installer (64-bit)** under the newest Python 3 release (on a laptop with
an ARM processor, such as a Snapdragon, **Windows installer (ARM64)**). Run it with its
default settings. Then close PowerShell, open it again, and check:

```powershell
py --version
```

It must say 3.11 or newer: if it shows an older Python, install the newest as above. (If
`py` asks to finish setting itself up the first time, accept what it proposes.)

**git**: install [Git for Windows](https://git-scm.com/download/win) with its default
settings. Then, in a new PowerShell window:

```powershell
git --version
```

**OpenSSH** comes with Windows 10 and 11. Check it:

```powershell
ssh -V
```

It prints the version, for example `OpenSSH_for_Windows_8.1` or
`OpenSSH_for_Windows_9.5`.

If PowerShell says `ssh` is not recognized, add it:

- Windows 11: *Settings*, *System*, *Optional features*, *View features*, search for
  **OpenSSH Client**, select it, then *Next* and *Add*.
- Windows 10: *Settings*, *Apps*, *Optional features*, *Add a feature*, then
  **OpenSSH Client**, *Install*.

**UTF-8 for your own code** (recommended): run this once.

```powershell
setx PYTHONUTF8 1
```

From the next PowerShell window on, Python reads and writes files as UTF-8 by default,
as it does on a Mac or Linux, so your own scripts read the Icelandic letters in the
cards and data correctly.

## 2. Start the SSH agent (once, as administrator)

The SSH agent remembers your key's passphrase, so that you do not type it at every
connection. Windows ships it switched off. Open the Start menu, type `PowerShell`,
right-click *Windows PowerShell*, choose **Run as administrator**, and run:

```powershell
Get-Service ssh-agent | Set-Service -StartupType Automatic
Start-Service ssh-agent
```

Close that window; from now on the agent starts with Windows. (Without administrator
rights, skip this step: everything still works, but ssh asks for your passphrase each
time it connects.)

## 3. Download the starter kit

First accept the invitation to the repository that GitHub sent you by e-mail (it
expires after 7 days). Then clone it into a short folder that OneDrive does not sync (it
often syncs Documents and Desktop, and would upload the 5.7 GB of data; long folder paths
also break the data files):

```powershell
cd C:\
git clone https://github.com/SyedMuhammadAzhar/gagnvist-starter.git
cd C:\gagnvist-starter
```

While the repository is private, a browser window opens the first time: sign in to
GitHub with the account the organizers added.

## 4. Install it

```powershell
py -m venv .venv
.venv\Scripts\python -m pip install -e .
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned -Force
.venv\Scripts\activate
```

The first line makes the starter kit's own Python environment, the second installs the
starter kit into it, the third lets PowerShell run the script that activates it (Windows
blocks such scripts until you allow them; this allows them for your user only), and the
fourth activates it. Your prompt now begins with `(.venv)`: the environment is active in
this window. Check that it works:

```powershell
gagnvist --help
```

## 5. Fill in your settings

Make your own settings file from the example, and open it in Notepad:

```powershell
copy example.env .env
notepad .env
```

Replace the three example values after the `=` signs, then save (`Ctrl+S`) and close
Notepad:

```bash
GAGNVIST_LUMI_USERNAME=your_lumi_username
GAGNVIST_SSH_KEY=~/.ssh/id_ed25519_lumi
GAGNVIST_TEAM_KEY=paste-your-team-key-here
```

| Line | Put there |
|---|---|
| `GAGNVIST_LUMI_USERNAME` | your LUMI username, from the e-mail LUMI sent you |
| `GAGNVIST_SSH_KEY` | the path to the SSH key you use for LUMI: the file **without** `.pub`, for example `C:\Users\you\.ssh\id_ed25519_lumi` or `~/.ssh/id_ed25519_lumi`. `dir $HOME\.ssh` lists your keys; yours may have another name. |
| `GAGNVIST_TEAM_KEY` | your team's key from the organizers: 48 letters and digits, copied exactly, without quote marks or spaces. Your teammate puts the same key in their own `.env`. |

`.env` stays on your computer: git ignores it, so it is never committed or pushed.

A key made with PuTTY (a `.ppk` file) must first be converted: in PuTTYgen, load it and
choose *Conversions*, *Export OpenSSH key*, and use the exported file.

## 6. Unpack the data

The data comes with the repository: Statistics Iceland's tables in both languages.
Unpack it and index it. It takes 5.7 GB and a few minutes (Windows' virus scanner looks
at every file); `get-data` shows how far it has come:

```powershell
gagnvist get-data
gagnvist build-index
```

## 7. Log in to LUMI once by hand

So that your computer learns LUMI's identity. Use your own key file and username (here
and below, `$HOME\.ssh\id_ed25519_lumi` stands for your key's file):

```powershell
ssh -i $HOME\.ssh\id_ed25519_lumi your_lumi_username@lumi.csc.fi
```

ssh shows LUMI's *fingerprint* and asks whether to trust it. Check that it is one of
[LUMI's published fingerprints](https://docs.lumi-supercomputer.eu/firststeps/loggingin/)
(Windows 10 usually shows the ECDSA one):

| Key type | Fingerprint |
|---|---|
| ED25519 | `SHA256:qCFZThjRw8nf0CiZ9rU7b6Zirjq8slAIl5r0xWaVoD0` |
| ECDSA | `SHA256:hY4mnRCYb8bRchTnVcFo7SqoHHHEsUh9Ym38F4sHN1Y` |
| RSA | `SHA256:ypbqdMWtk9ZdXEROkeEpv+3PCEXWjPLGI79IXGHe9ac` |

Then type `yes`, enter your key's passphrase, and once you are logged in, type `exit`.

If you have logged in to LUMI from this computer before, skip this step.

## 8. Connect to the shared models

First check that everything is in place:

```powershell
gagnvist lumi check
```

If your key has a passphrase, it first offers to remember it:

```text
Your SSH key has a passphrase, which ssh asks for every time it connects to LUMI.
The SSH agent can remember it until you remove it. Remember it? [Y/n]
```

Press Enter, and type your passphrase once. Windows' agent then keeps the key, also
after a restart, until you remove it: at the end of the hackathon, and always on a
shared computer, run `ssh-add -d $HOME\.ssh\id_ed25519_lumi` (your key's file).

When it says **All set**, open the tunnel to LUMI, and **leave this window open**:

```powershell
gagnvist lumi connect
```

## 9. Ask your first question

Open a **second** PowerShell window, and in it:

```powershell
cd C:\gagnvist-starter
.venv\Scripts\activate
gagnvist ask "How many people live in Reykjavík?"
```

```text
In 2026, the total population of Reykjavík is 139,804.

Source: Statistics Iceland, table MAN03270 "Population in Reykjavík by districts, sex and age 1 January 1998-2026" ...
```

Questions in Icelandic are answered in Icelandic. You are set up: the
[README](../README.md#making-it-better) tells you where to go from here.

## Every day after that

Two PowerShell windows:

```powershell
# window 1: the tunnel; leave it open
cd C:\gagnvist-starter
.venv\Scripts\activate
gagnvist lumi connect
```

```powershell
# window 2: your work
cd C:\gagnvist-starter
.venv\Scripts\activate
gagnvist ask "..."
```

- Every new window needs `.venv\Scripts\activate` again, or `gagnvist` is not found.
- If your computer sleeps, or the organizers restart the shared models, the tunnel
  reconnects by itself.
- When the organizers announce an update: commit your own changes first (`git add -A`,
  then `git commit -m "our changes"`), then `git pull --no-rebase --no-edit` and
  `.venv\Scripts\python -m pip install -e .`

## If something goes wrong

| Message | What to do |
|---|---|
| `py` is not recognized | Install Python from python.org (step 1), then open a new PowerShell window. |
| `remote: Repository not found` (step 3) | Accept the invitation that GitHub e-mailed you (it expires after 7 days; ask the organizers for a new one). Signed in to GitHub with another account? In *Control Panel*, *Credential Manager*, *Windows Credentials*, remove `git:https://github.com`, then clone again and sign in with the invited account. |
| `Access to the path ... is denied` when cloning into `C:\` | Clone into your user folder instead: `cd $HOME` before `git clone`, and use `$HOME\gagnvist-starter` wherever this guide says `C:\gagnvist-starter`. |
| `requires a different Python: 3.10` (or older) | Install Python 3.11 or newer (step 1), remove the old environment with `Remove-Item -Recurse -Force .venv`, and do step 4 again. |
| `running scripts is disabled on this system` | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned -Force`, then `.venv\Scripts\activate` (step 4). |
| `gagnvist` is not recognized | Activate the environment in this window: `cd C:\gagnvist-starter` and `.venv\Scripts\activate`. If the prompt already begins with `(.venv)`: `.venv\Scripts\python -m pip install -e .` |
| `An Application Control policy has blocked this file` | Windows' Smart App Control blocks the `gagnvist` command: type `python -m gagnvist` instead of `gagnvist`, for example `python -m gagnvist ask "..."`. |
| `ssh` is not recognized / `the ssh program was not found` | Add *OpenSSH Client* under *Optional features* (step 1). |
| `Windows' SSH agent ... is not running` | Start it once as administrator (step 2). |
| `found .env.txt but no .env` | Rename the file to `.env` (step 5). |
| `ssh refuses to use ... because others may read it` / `UNPROTECTED PRIVATE KEY FILE` | `icacls $HOME\.ssh\id_ed25519_lumi /inheritance:r /grant:r "$(whoami):R"` (your key's file). |
| `Connection timed out` (step 7) | The network blocks ssh (port 22): try another one, such as your phone's hotspot. |
| `Permission denied (publickey)` (step 7) | Check the username and the key file. A key added in MyCSC in the last couple of hours may not have reached LUMI yet. |
| `LUMI did not accept the SSH key` | Check the username and key path in `.env`. A key added in MyCSC in the last couple of hours may not have reached LUMI yet. |
| `too deep for Windows` | Clone the starter kit again into `C:\gagnvist-starter` and do steps 3 to 6 there. (A folder that is set up cannot simply be moved: its `.venv` remembers where it was.) |
| `port 8765 ... is already in use` / `does not let programs use port` | Add `GAGNVIST_LOCAL_PORT=8790` to `.env`. |
| `the shared models are not running right now` | Tell the organizers. |
| A window stops printing, or a command seems stuck, after you clicked in it | Clicking in a PowerShell window selects text and pauses the program: press `Esc` to let it go on. (Windows Terminal does not do this.) |

Anything else: the full list in [docs/lumi.md](lumi.md#9-troubleshooting).
