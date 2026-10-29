"""Remembering the passphrase of your SSH key for a while, so that ssh stops asking.

ssh asks for your key's passphrase every time it connects to LUMI: for every
``gagnvist lumi`` command, and again whenever the tunnel reconnects. The SSH agent that
comes with macOS, Linux and Windows can hold the unlocked key instead, and
``gagnvist lumi check`` and ``connect`` offer to give it the key (:func:`remember_key`):

- on macOS and Linux for as long as you choose (``ssh-add -t``); then the agent forgets
  it, and ssh asks again;
- on Windows until you remove it (``ssh-add -d``), since Windows' agent cannot forget a
  key by itself.

You type the passphrase into ssh-add, never into this program.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from gagnvist.lumi.connection import LumiError, openssh_program, quoted

DEFAULT_TIME = "12h"
LONGEST_MINUTES = 7 * 24 * 60  # a week
_TIME = re.compile(r"(?:\d+[mhd])+")  # 30m, 2h, 2d, 1h30m: as ssh-add -t reads them
_PART = re.compile(r"(\d+)([mhd])")
_MINUTES = {"m": 1, "h": 60, "d": 24 * 60}
_NO_AGENT = 2  # the exit status of `ssh-add -l` when there is no agent to ask


def remember_key(
    ssh_key: Path, *, ask: Callable[[str], str] = input, time_limits: bool | None = None
) -> None:
    """Offer to give your key to the SSH agent, if the key has a passphrase and the
    agent does not hold it yet.

    It asks only in a terminal, and does nothing when something is missing: then ssh
    asks for the passphrase, as before. ``time_limits``: whether the agent can forget a
    key after a while (by default, everywhere but on Windows).
    """
    if not _interactive():
        return
    if time_limits is None:
        time_limits = os.name != "nt"
    try:
        ssh_add = openssh_program("ssh-add")
        ssh_keygen = openssh_program("ssh-keygen")
    except LumiError:
        return  # ssh explains what is missing, once it is needed
    fingerprint = _fingerprint(ssh_keygen, ssh_key)
    if fingerprint is None or not _has_passphrase(ssh_keygen, ssh_key):
        return
    held = _run([ssh_add, "-l"])
    if held.returncode == _NO_AGENT:
        _explain_missing_agent()
        return
    if fingerprint in held.stdout:
        return  # the agent holds it already

    print("Your SSH key has a passphrase, which ssh asks for every time it connects to LUMI.")
    if time_limits:
        life = _ask_time(ask)
        if life is None:
            print("Then ssh asks for it each time.")
            return
        command = [ssh_add, "-t", life, str(ssh_key)]
    else:
        if not _ask_yes(ask, "The SSH agent can remember it until you remove it. Remember it?"):
            print("Then ssh asks for it each time.")
            return
        command = [ssh_add, str(ssh_key)]

    # ssh-add asks for the passphrase itself, in this terminal (its prompt is on stderr,
    # so nothing is captured here).
    try:
        added = subprocess.run(command, check=False).returncode == 0
    except OSError:
        added = False
    if not added:
        print(
            "Your key was not remembered (see the message above), so ssh asks for the "
            "passphrase when it connects."
        )
        if time_limits:
            print(
                "If the agent refused, it cannot forget a key by itself: `ssh-add "
                f"{quoted(ssh_key)}` makes it remember the key until "
                f"`ssh-add -d {quoted(ssh_key)}`."
            )
    elif time_limits:
        print(
            f"The SSH agent remembers your key for {life}: until then, ssh no longer asks "
            f"for the passphrase. To make it forget sooner: ssh-add -d {quoted(ssh_key)}"
        )
    else:
        print(
            "The SSH agent remembers your key until you remove it, also after a restart: "
            f"ssh-add -d {quoted(ssh_key)}"
        )


def minutes(text: str) -> int | None:
    """The length of a time such as 30m, 2h, 2d or 1h30m, in minutes; None if it is not
    one."""
    if not _TIME.fullmatch(text):
        return None
    return sum(int(number) * _MINUTES[unit] for number, unit in _PART.findall(text))


def _ask_time(ask: Callable[[str], str]) -> str | None:
    prompt = (
        "The SSH agent can remember it for a while, so that ssh stops asking.\n"
        "For how long? For example 2h, 12h or 2d (at most 7d).\n"
        f"Press Enter for {DEFAULT_TIME}, or type 0 to be asked every time: "
    )
    for _ in range(3):
        try:
            answer = ask(prompt).strip().lower().replace(" ", "")
        except EOFError:
            return None
        if answer in ("0", "n", "no"):
            return None
        life = answer or DEFAULT_TIME
        length = minutes(life)
        if length is not None and 0 < length <= LONGEST_MINUTES:
            return life
        prompt = "Type a time such as 30m, 2h, 12h or 2d, at most 7d (or 0 for none): "
    return None


def _ask_yes(ask: Callable[[str], str], question: str) -> bool:
    try:
        answer = ask(f"{question} [Y/n] ").strip().lower()
    except EOFError:
        return False
    return answer in ("", "y", "yes", "j", "já", "ja")


def _explain_missing_agent() -> None:
    if os.name == "nt":
        print(
            "Tip: ssh asks for your passphrase every time it connects. Windows' SSH agent "
            "can remember it, but it is not running: start it once as administrator (see "
            "docs/setup-windows.md, step 2)."
        )
    else:
        print(
            "Tip: ssh asks for your passphrase every time it connects. No SSH agent runs "
            'in this terminal to remember it; start one with: eval "$(ssh-agent)"'
        )


def _fingerprint(ssh_keygen: str, ssh_key: Path) -> str | None:
    """The key's fingerprint, as `ssh-add -l` lists it (read without the passphrase)."""
    result = _run([ssh_keygen, "-l", "-f", str(ssh_key)])
    words = result.stdout.split()
    return words[1] if result.returncode == 0 and len(words) > 1 else None


def _has_passphrase(ssh_keygen: str, ssh_key: Path) -> bool:
    """Whether the key is locked: ssh-keygen cannot open it with an empty passphrase.
    A key that ssh refuses for its file permissions is not offered: ssh explains that
    itself, and how to fix it, when it connects."""
    result = _run([ssh_keygen, "-y", "-P", "", "-f", str(ssh_key)])
    if result.returncode == 0:
        return False
    errors = result.stderr.lower()
    return not any(sign in errors for sign in ("unprotected private key", "bad permissions"))


def _interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return subprocess.CompletedProcess(command, 1, "", "")
