"""Offering to remember the SSH key's passphrase, against stand-ins for ssh-add and
ssh-keygen (so that no real SSH agent is touched)."""

import json
import os
import sys
from pathlib import Path

import pytest
from fake_lumi import FakeLumi, _write_program, needs_posix

from gagnvist.cli import main
from gagnvist.lumi import agent

FINGERPRINT = "SHA256:fAkEpRiNt"

# ssh-keygen: -l prints the fingerprint; -y -P "" opens the key only without a passphrase.
_SSH_KEYGEN = f"""
import os, sys
if "-l" in sys.argv:
    print("256 {FINGERPRINT} a comment (ED25519)")
    sys.exit(0)
if os.environ.get("FAKE_BAD_PERMISSIONS"):
    sys.stderr.write("WARNING: UNPROTECTED PRIVATE KEY FILE!\\nbad permissions\\n")
    sys.exit(1)
sys.exit(0 if os.environ.get("FAKE_NO_PASSPHRASE") else 1)
"""
# ssh-add: -l lists what the agent holds; adding writes its arguments down.
_SSH_ADD = f"""
import json, os, sys
if sys.argv[1:] == ["-l"]:
    if os.environ.get("FAKE_NO_AGENT"):
        sys.exit(2)
    if os.environ.get("FAKE_HELD"):
        print("256 {FINGERPRINT} a comment (ED25519)")
        sys.exit(0)
    print("The agent has no identities.")
    sys.exit(1)
with open(os.environ["FAKE_ADDED"], "a", encoding="utf-8") as f:
    f.write(json.dumps(sys.argv[1:]) + "\\n")
sys.exit(int(os.environ.get("FAKE_ADD_STATUS", "0")))
"""


class Asker:
    """Answers the questions in turn, and writes them down."""

    def __init__(self, *answers: str) -> None:
        self.answers = list(answers)
        self.questions: list[str] = []

    def __call__(self, question: str) -> str:
        self.questions.append(question)
        return self.answers.pop(0)


@pytest.fixture
def tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Stand-ins for ssh-add and ssh-keygen, first on the PATH, in a terminal; returns
    the file where ssh-add writes down what it was asked to add."""
    folder = tmp_path / "bin"
    folder.mkdir()
    _write_program(folder / "ssh-keygen", f"#!{sys.executable}\n{_SSH_KEYGEN}")
    _write_program(folder / "ssh-add", f"#!{sys.executable}\n{_SSH_ADD}")
    monkeypatch.setenv("PATH", f"{folder}{os.pathsep}{os.environ['PATH']}")
    added = tmp_path / "added.jsonl"
    monkeypatch.setenv("FAKE_ADDED", str(added))
    for name in (
        "FAKE_NO_AGENT",
        "FAKE_HELD",
        "FAKE_NO_PASSPHRASE",
        "FAKE_ADD_STATUS",
        "FAKE_BAD_PERMISSIONS",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(agent, "_interactive", lambda: True)
    return added


def additions(added: Path) -> list[list[str]]:
    if not added.exists():
        return []
    return [json.loads(line) for line in added.read_text(encoding="utf-8").splitlines()]


KEY = Path("/home/me/.ssh/id_ed25519")


@needs_posix
def test_enter_remembers_the_key_for_the_default_time(
    tools: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    agent.remember_key(KEY, ask=Asker(""), time_limits=True)
    assert additions(tools) == [["-t", agent.DEFAULT_TIME, str(KEY)]]
    assert f"remembers your key for {agent.DEFAULT_TIME}" in capsys.readouterr().out


@needs_posix
def test_a_time_of_your_own_is_used(tools: Path) -> None:
    agent.remember_key(KEY, ask=Asker("2d"), time_limits=True)
    assert additions(tools) == [["-t", "2d", str(KEY)]]


@needs_posix
def test_a_time_that_is_not_one_is_asked_again(tools: Path) -> None:
    asker = Asker("two days", "8d", "1h 30m")
    agent.remember_key(KEY, ask=asker, time_limits=True)
    assert additions(tools) == [["-t", "1h30m", str(KEY)]]
    assert len(asker.questions) == 3
    assert "at most 7d" in asker.questions[1]


@needs_posix
def test_zero_means_being_asked_every_time(tools: Path, capsys: pytest.CaptureFixture[str]) -> None:
    agent.remember_key(KEY, ask=Asker("0"), time_limits=True)
    assert additions(tools) == []
    assert "ssh asks for it each time" in capsys.readouterr().out


@needs_posix
def test_nothing_is_asked_when_the_agent_holds_the_key(
    tools: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_HELD", "1")
    asker = Asker()
    agent.remember_key(KEY, ask=asker, time_limits=True)
    assert asker.questions == []
    assert additions(tools) == []


@needs_posix
def test_nothing_is_asked_for_a_key_without_a_passphrase(
    tools: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("FAKE_NO_PASSPHRASE", "1")
    monkeypatch.setenv("FAKE_NO_AGENT", "1")  # not even a tip, as there is nothing to type
    asker = Asker()
    agent.remember_key(KEY, ask=asker, time_limits=True)
    assert asker.questions == []
    assert capsys.readouterr().out == ""


@needs_posix
def test_without_an_agent_a_tip_is_given(
    tools: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("FAKE_NO_AGENT", "1")
    asker = Asker()
    agent.remember_key(KEY, ask=asker, time_limits=True)
    assert asker.questions == []
    assert "ssh-agent" in capsys.readouterr().out


@needs_posix
def test_outside_a_terminal_nothing_is_asked(tools: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(agent, "_interactive", lambda: False)
    asker = Asker()
    agent.remember_key(KEY, ask=asker, time_limits=True)
    assert asker.questions == []
    assert additions(tools) == []


@needs_posix
def test_on_windows_the_key_is_remembered_until_it_is_removed(
    tools: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    asker = Asker("")
    agent.remember_key(KEY, ask=asker, time_limits=False)
    assert additions(tools) == [[str(KEY)]]
    assert "[Y/n]" in asker.questions[0]
    assert f"until you remove it, also after a restart: ssh-add -d {KEY}" in (
        capsys.readouterr().out
    )


@needs_posix
def test_a_refusal_is_explained(
    tools: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("FAKE_ADD_STATUS", "1")
    agent.remember_key(KEY, ask=Asker("2h"), time_limits=True)
    printed = capsys.readouterr().out
    assert "was not remembered" in printed
    assert f"`ssh-add {KEY}`" in printed


@needs_posix
def test_end_of_input_counts_as_no(tools: Path) -> None:
    def closed(question: str) -> str:
        raise EOFError

    agent.remember_key(KEY, ask=closed, time_limits=True)
    agent.remember_key(KEY, ask=closed, time_limits=False)
    assert additions(tools) == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [("30m", 30), ("2h", 120), ("2d", 2880), ("1h30m", 90), ("12", None), ("2w", None), ("", None)],
)
def test_times_are_read_as_ssh_add_reads_them(text: str, expected: int | None) -> None:
    assert agent.minutes(text) == expected


@needs_posix
@pytest.mark.parametrize("command", ["check", "connect"])
def test_check_and_connect_offer_to_remember_the_key(
    fake_lumi: FakeLumi, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    offered: list[Path] = []

    def remember(ssh_key: Path) -> None:
        offered.append(ssh_key)
        raise SystemExit(0)  # stop before connecting: only the offer is tested here

    monkeypatch.setattr("gagnvist.lumi.cli.remember_key", remember)
    with pytest.raises(SystemExit):
        main(["--config", str(fake_lumi.config), "jureca", command])
    assert offered == [fake_lumi.settings.cluster().ssh_key]


@needs_posix
def test_a_key_refused_for_its_permissions_is_not_offered(
    tools: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_BAD_PERMISSIONS", "1")
    asker = Asker()
    agent.remember_key(KEY, ask=asker, time_limits=True)
    assert asker.questions == []  # ssh itself explains the permissions when it connects
