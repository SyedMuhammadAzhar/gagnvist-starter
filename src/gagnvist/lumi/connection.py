"""Running commands on LUMI and opening tunnels to it, with your own SSH key.

Everything goes through the ``ssh`` program that comes with macOS, Linux and Windows 10
and later, using your own key (GAGNVIST_SSH_KEY in .env). The key never leaves your
computer, and no one else's key is ever needed.

If your key has a passphrase, ssh asks for it every time it connects, unless your SSH
agent holds the key: `gagnvist lumi check` and `connect` offer to give it the key, for
as long as you choose (see :mod:`gagnvist.lumi.agent`).
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from gagnvist.config import ConfigError, Settings

_SSH_FAILED = 255  # the exit status of ssh's own errors, as opposed to the command's


def quoted(path: Path | str) -> str:
    """A path to paste into a terminal: in double quotes if it has a space (which works
    in PowerShell, Command Prompt and macOS/Linux shells alike)."""
    text = str(path)
    return f'"{text}"' if any(c.isspace() for c in text) else text


class LumiError(Exception):
    """LUMI could not be reached, or a command there failed."""


@dataclass(frozen=True)
class Lumi:
    """Your account on LUMI."""

    username: str
    host: str
    ssh_key: Path

    @classmethod
    def from_settings(cls, settings: Settings) -> Lumi:
        settings.require_lumi_access()
        if settings.lumi.ssh_key is None:  # reported by require_lumi_access already
            raise ConfigError("set GAGNVIST_SSH_KEY in .env")
        return cls(settings.lumi.username, settings.lumi.host, settings.lumi.ssh_key)

    def run(self, script: str, *, stdin: bytes | None = None, show_output: bool = False) -> str:
        """Run a bash script on a LUMI login node and return what it printed.

        The script runs in a login shell (``bash -l``), as if you had logged in yourself,
        so LUMI's usual commands (sbatch, squeue, module, singularity) are available.
        With ``show_output`` the output goes straight to your terminal instead, which
        suits long commands such as downloads, and nothing is returned.
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
            raise LumiError(f"a command on LUMI failed: {(errors or output)[-600:]}")
        return output

    def open_tunnel(self, local_port: int, node: str, remote_port: int) -> subprocess.Popen[bytes]:
        """Start a tunnel: connections to ``local_port`` on this computer (and only from
        this computer) are carried through ssh to ``remote_port`` on the LUMI node."""
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
            *options,
            f"{self.username}@{self.host}",
        ]

    def _explain_ssh_failure(self, errors: str) -> str:
        # ssh prints the reason a key could not be used before its final "Permission
        # denied", so the reasons are looked for first.
        if "UNPROTECTED PRIVATE KEY FILE" in errors or "bad permissions" in errors:
            return (
                f"ssh refuses to use {self.ssh_key} because others may read it. On macOS or "
                f"Linux: chmod 600 {quoted(self.ssh_key)}. On Windows, in PowerShell: "
                f'icacls "{self.ssh_key}" /inheritance:r /grant:r "$(whoami):R"'
            )
        if "invalid format" in errors or "error in libcrypto" in errors:
            return (
                f"ssh cannot read the key {self.ssh_key}: GAGNVIST_SSH_KEY must point to the "
                "private key in OpenSSH format (not the .pub file; a PuTTY .ppk key must first "
                "be exported from PuTTYgen with Conversions, Export OpenSSH key)"
            )
        if "incorrect passphrase" in errors:
            return f"the passphrase for {self.ssh_key} was not right; try again"
        if "Permission denied" in errors:
            return (
                f"LUMI did not accept the SSH key {self.ssh_key} for the user "
                f"{self.username!r}: check GAGNVIST_LUMI_USERNAME and GAGNVIST_SSH_KEY in "
                ".env. A key you have just added in MyCSC can take a couple of hours to "
                "reach LUMI."
            )
        if "Host key verification failed" in errors:
            return (
                f"ssh could not verify the identity of {self.host}; connect once yourself "
                f"with `ssh -i {quoted(self.ssh_key)} {self.username}@{self.host}` and accept "
                "LUMI's host key (see docs/lumi.md)"
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
