"""Running commands on a supercomputer and opening tunnels to it, with your own SSH key.

Everything goes through the ``ssh`` program that comes with macOS, Linux and Windows 10
and later, using your own key (GAGNVIST_SSH_KEY in .env). The key never leaves your
computer, and no one else's key is ever needed.

If your key has a passphrase, ssh asks for it every time it connects, unless your SSH
agent holds the key: `gagnvist lumi check` and `connect` offer to give it the key, for
as long as you choose (see :mod:`gagnvist.lumi.agent`).

This was written for LUMI, and works the same for JURECA: a :class:`Lumi` knows which
supercomputer it logs in to (its ``cluster``, see :mod:`gagnvist.clusters`). JURECA may
ask for a one-time code at each login; there, the first connection is kept open and
every later command and tunnel goes through it (ssh's ControlMaster), on macOS and
Linux, so that the code is typed once.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from gagnvist.clusters import LUMI, Cluster
from gagnvist.config import ConfigError, Settings

_SSH_FAILED = 255  # the exit status of ssh's own errors, as opposed to the command's
CONNECTION_KEPT = "10h"  # how long a reused connection stays open after its last use


def quoted(path: Path | str) -> str:
    """A path to paste into a terminal: in double quotes if it has a space (which works
    in PowerShell, Command Prompt and macOS/Linux shells alike)."""
    text = str(path)
    return f'"{text}"' if any(c.isspace() for c in text) else text


class LumiError(Exception):
    """The supercomputer could not be reached, or a command there failed."""


@dataclass(frozen=True)
class Lumi:
    """Your account on a supercomputer: LUMI unless ``cluster`` says JURECA."""

    username: str
    host: str
    ssh_key: Path
    cluster: Cluster = LUMI

    @classmethod
    def from_settings(cls, settings: Settings, cluster: str = LUMI.name) -> Lumi:
        """Your account on the supercomputer called ``cluster`` ("lumi" or "jureca")."""
        settings.require_access(cluster)
        account = settings.cluster(cluster)
        if account.ssh_key is None:  # reported by require_access already
            raise ConfigError(f"set {account.profile.ssh_key_setting} in .env")
        return cls(account.username, account.host, account.ssh_key, account.profile)

    @property
    def label(self) -> str:
        """The supercomputer's name, for messages."""
        return self.cluster.label

    def run(self, script: str, *, stdin: bytes | None = None, show_output: bool = False) -> str:
        """Run a bash script on a login node and return what it printed.

        The script runs in a login shell (``bash -l``), as if you had logged in yourself,
        so the usual commands (sbatch, squeue, module, the container runtime) are
        available. With ``show_output`` the output goes straight to your terminal
        instead, which suits long commands such as downloads, and nothing is returned.
        """
        command = [*self._ssh(), "bash -lc " + shlex.quote(script)]
        # Without data to send, ssh gets no standard input at all, so it cannot swallow
        # input meant for something else. (A passphrase is asked on the terminal itself.)
        no_input = subprocess.DEVNULL if stdin is None else None
        if show_output:
            completed = subprocess.run(command, input=stdin, stdin=no_input, check=False)
            output, errors = "", "see the messages above"
        else:
            result = subprocess.run(
                command, input=stdin, stdin=no_input, capture_output=True, check=False
            )
            completed = result
            output = result.stdout.decode("utf-8", errors="replace")
            errors = result.stderr.decode("utf-8", errors="replace").strip()
        if completed.returncode == _SSH_FAILED:
            raise LumiError(self._explain_ssh_failure(errors))
        if completed.returncode != 0:
            raise LumiError(f"a command on {self.label} failed: {(errors or output)[-600:]}")
        return output

    def open_tunnel(self, local_port: int, node: str, remote_port: int) -> subprocess.Popen[bytes]:
        """Start a tunnel: connections to ``local_port`` on this computer (and only from
        this computer) are carried through ssh to ``remote_port`` on the node."""
        forward = f"127.0.0.1:{local_port}:{node}:{remote_port}"
        command = self._ssh("-N", "-o", "ExitOnForwardFailure=yes", "-L", forward)
        return subprocess.Popen(command, stdin=subprocess.DEVNULL)

    def _ssh(self, *options: str) -> list[str]:
        return [
            _ssh_program(),
            *("-i", str(self.ssh_key)),
            *("-o", "IdentitiesOnly=yes"),  # offer only this key, not every key ssh knows
            *("-o", "ConnectTimeout=30"),
            *("-o", "ServerAliveInterval=30"),  # notice a dead connection in about 90 s
            *self._reuse_connection(),
            *options,
            f"{self.username}@{self.host}",
        ]

    def _reuse_connection(self) -> list[str]:
        """ssh options that keep the first connection open and send every later command
        and tunnel through it, where the supercomputer asks for a one-time code at each
        login. Windows' OpenSSH cannot do this, so there every connection logs in anew."""
        if not self.cluster.multiplex or os.name == "nt":
            return []
        folder = Path.home() / ".ssh"
        folder.mkdir(mode=0o700, exist_ok=True)
        return [
            *("-o", "ControlMaster=auto"),
            *("-o", f"ControlPath={folder / 'gagnvist-%C'}"),  # %C: a hash of host and user
            *("-o", f"ControlPersist={CONNECTION_KEPT}"),
        ]

    def _explain_ssh_failure(self, errors: str) -> str:
        # ssh prints the reason a key could not be used before its final "Permission
        # denied", so the reasons are looked for first.
        facts = self.cluster
        if "UNPROTECTED PRIVATE KEY FILE" in errors or "bad permissions" in errors:
            return (
                f"ssh refuses to use {self.ssh_key} because others may read it. On macOS or "
                f"Linux: chmod 600 {quoted(self.ssh_key)}. On Windows, in PowerShell: "
                f'icacls "{self.ssh_key}" /inheritance:r /grant:r "$(whoami):R"'
            )
        if "invalid format" in errors or "error in libcrypto" in errors:
            return (
                f"ssh cannot read the key {self.ssh_key}: {facts.ssh_key_setting} must point "
                "to the private key in OpenSSH format (not the .pub file; a PuTTY .ppk key "
                "must first be exported from PuTTYgen with Conversions, Export OpenSSH key)"
            )
        if "incorrect passphrase" in errors:
            return f"the passphrase for {self.ssh_key} was not right; try again"
        if "Permission denied (keyboard-interactive)" in errors:
            return (
                f"{facts.label} accepted your key, then asked for a one-time code (the "
                "multi-factor authentication of your account), which could not be typed "
                f"here. Log in once yourself with `ssh -i {quoted(self.ssh_key)} "
                f"{self.username}@{self.host}` and type the code; see {facts.docs}."
            )
        if "Permission denied" in errors:
            return (
                f"{facts.label} did not accept the SSH key {self.ssh_key} for the user "
                f"{self.username!r}: check {facts.username_setting} and "
                f"{facts.ssh_key_setting} in .env. {facts.key_hint}"
            )
        if "Host key verification failed" in errors:
            return (
                f"ssh could not verify the identity of {self.host}; connect once yourself "
                f"with `ssh -i {quoted(self.ssh_key)} {self.username}@{self.host}` and accept "
                f"{facts.host_key_hint}"
            )
        if "Could not resolve hostname" in errors:
            return f"{self.host} could not be found: are you connected to the internet?"
        return f"ssh could not connect to {self.host}: {errors[-600:] or 'no details'}"


def _ssh_program() -> str:
    return openssh_program("ssh")


def _windows_openssh(name: str) -> str | None:
    windows = os.environ.get("SYSTEMROOT", r"C:\Windows")
    # 32-bit Python on 64-bit Windows sees System32 redirected, and finds it in Sysnative
    for folder in ("System32", "Sysnative"):
        candidate = Path(windows, folder, "OpenSSH", f"{name}.exe")
        if candidate.is_file():
            return str(candidate)
    return None


def openssh_program(name: str) -> str:
    """The path of one of OpenSSH's programs: ssh, ssh-add or ssh-keygen.

    On Windows, the OpenSSH that comes with Windows is used whenever it is there, even in
    a terminal (such as Git Bash) that finds another ssh first: only Windows' own
    ssh-add reaches Windows' SSH agent, which its ssh uses too.
    """
    program = _windows_openssh(name) if os.name == "nt" else None
    program = program or shutil.which(name)
    if program is None:
        raise LumiError(
            f"the {name} program was not found. On Windows 11, add it under Settings > "
            "System > Optional features > View features > OpenSSH Client (Windows 10: "
            "Settings > Apps > Optional features > Add a feature); on Linux, install the "
            "openssh-client package."
        )
    return program
