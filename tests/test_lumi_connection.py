"""Running commands on LUMI through ssh (answered here by a fake ssh)."""

import json
import os
from pathlib import Path

import pytest
from fake_lumi import make_recording_ssh, needs_posix

from gagnvist.lumi.connection import Lumi, LumiError, _windows_openssh

pytestmark = needs_posix


@pytest.fixture(scope="module")
def recording_ssh(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return make_recording_ssh(tmp_path_factory.mktemp("recording-ssh"))


@pytest.fixture
def lumi(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recording_ssh: Path) -> Lumi:
    monkeypatch.setenv("PATH", f"{recording_ssh}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_SSH_RECORD", str(tmp_path / "ssh-arguments.json"))
    return Lumi("testuser", "lumi.example", tmp_path / "my key")


def ssh_arguments(tmp_path: Path) -> list[str]:
    arguments: list[str] = json.loads((tmp_path / "ssh-arguments.json").read_text(encoding="utf-8"))
    return arguments


def test_commands_go_through_your_own_key_and_a_login_shell(lumi: Lumi, tmp_path: Path) -> None:
    lumi.run("squeue --me -o '%i %j'")
    arguments = ssh_arguments(tmp_path)
    assert arguments[:2] == ["-i", str(tmp_path / "my key")]
    assert "IdentitiesOnly=yes" in arguments
    assert arguments[-2] == "testuser@lumi.example"
    assert arguments[-1] == "bash -lc 'squeue --me -o '\"'\"'%i %j'\"'\"''"


def test_a_tunnel_listens_on_this_computer_only(
    lumi: Lumi, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lumi.open_tunnel(8765, "nid005001", 4000).wait()
    arguments = ssh_arguments(tmp_path)
    assert arguments[arguments.index("-L") + 1] == "127.0.0.1:8765:nid005001:4000"
    assert "-N" in arguments and "ExitOnForwardFailure=yes" in arguments


@pytest.mark.parametrize(
    ("error", "explanation"),
    [
        ("testuser@lumi.example: Permission denied (publickey).", "did not accept the SSH key"),
        ("WARNING: UNPROTECTED PRIVATE KEY FILE!", "chmod 600"),
        # as ssh really prints them: the reason first, then "Permission denied"
        (
            'Load key "k": bad permissions\ntestuser@lumi.example: Permission denied (publickey).',
            "icacls",
        ),
        (
            'Load key "k": invalid format\ntestuser@lumi.example: Permission denied (publickey).',
            "OpenSSH format",
        ),
        ('Load key "k": incorrect passphrase supplied to decrypt private key', "passphrase"),
        ("Host key verification failed.", "accept LUMI's host key"),
        ("ssh: Could not resolve hostname lumi.example", "connected to the internet"),
        ("ssh: connect to host lumi.example port 22: Operation timed out", "timed out"),
    ],
)
def test_ssh_failures_are_explained(
    lumi: Lumi, monkeypatch: pytest.MonkeyPatch, error: str, explanation: str
) -> None:
    monkeypatch.setenv("FAKE_SSH_STATUS", "255")
    monkeypatch.setenv("FAKE_SSH_ERROR", error)
    with pytest.raises(LumiError, match=explanation):
        lumi.run("true")


def test_a_failed_command_on_lumi_shows_its_message(
    lumi: Lumi, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_SSH_STATUS", "1")
    monkeypatch.setenv("FAKE_SSH_ERROR", "sbatch: error: Invalid account or account/partition")
    with pytest.raises(LumiError, match="Invalid account"):
        lumi.run("sbatch")


def test_a_missing_ssh_program_is_explained(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))  # a folder without ssh
    with pytest.raises(LumiError, match="OpenSSH Client"):
        Lumi("testuser", "lumi.example", tmp_path / "key").run("true")


@pytest.mark.parametrize("folder", ["System32", "Sysnative"])
def test_on_windows_its_own_openssh_is_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, folder: str
) -> None:
    program = tmp_path / folder / "OpenSSH" / "ssh-add.exe"
    program.parent.mkdir(parents=True)
    program.write_bytes(b"")
    monkeypatch.setenv("SYSTEMROOT", str(tmp_path))
    assert _windows_openssh("ssh-add") == str(program)
    assert _windows_openssh("ssh-keygen") is None


def test_printed_commands_quote_a_path_with_a_space() -> None:
    from gagnvist.lumi.connection import quoted

    assert quoted(Path("/Users/jon/.ssh/id_lumi")) == "/Users/jon/.ssh/id_lumi"
    assert (
        quoted("C:\\Users\\Jon Jonsson\\.ssh\\id_lumi") == '"C:\\Users\\Jon Jonsson\\.ssh\\id_lumi"'
    )
