"""Running commands on LUMI and opening tunnels to it, with your own SSH key.

Everything goes through the ``ssh`` program that comes with macOS, Linux and Windows 10
and later, using your own key (GAGNVIST_SSH_KEY in .env). The key never leaves your
computer, and no one else's key is ever needed.

If your key has a passphrase, ssh asks for it every time it connects. Add the key to
your SSH agent once a day (see docs/lumi.md) and it stops asking.
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from gagnvist.config import ConfigError, Settings

_SSH_FAILED = 255  # the exit status of ssh's own errors, as opposed to the command's


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
        if "Permission denied" in errors:
            return (
                f"LUMI did not accept the SSH key {self.ssh_key} for the user "
                f"{self.username!r}: check GAGNVIST_LUMI_USERNAME and GAGNVIST_SSH_KEY in "
                ".env. A key you have just added in MyAccessID can take a few hours to "
                "reach LUMI."
            )
        if "UNPROTECTED PRIVATE KEY FILE" in errors:
            return (
                f"ssh refuses to use {self.ssh_key} because others may read it. On macOS or "
                f"Linux: chmod 600 {self.ssh_key}. On Windows: in the file's Properties, "
                "Security, leave only your own account."
            )
        if "Host key verification failed" in errors:
            return (
                f"ssh could not verify the identity of {self.host}; connect once yourself "
                f"with `ssh -i {self.ssh_key} {self.username}@{self.host}` and accept "
                "LUMI's host key (see docs/lumi.md)"
            )
        if "Could not resolve hostname" in errors:
            return f"{self.host} could not be found: are you connected to the internet?"
        return f"ssh could not connect to {self.host}: {errors[-600:] or 'no details'}"


def _ssh_program() -> str:
    program = shutil.which("ssh")
    if program is None:
        raise LumiError(
            "the ssh program was not found. On Windows, add it under Settings > Apps > "
            "Optional features > OpenSSH Client; on Linux, install the openssh-client package."
        )
    return program
