"""The `gagnvist jureca` commands, run against the fake JURECA."""

import re
from pathlib import Path

import pytest
from fake_lumi import PROJECT, TEAM_KEY, FakeLumi, needs_posix

from gagnvist.cli import main
from gagnvist.lumi.cli import _explain_own_server, check_training_data
from gagnvist.lumi.connection import LumiError
from gagnvist.lumi.jobs import ServerAddress

GOOD = '{"messages": [{"role": "user", "content": "Q?"}, {"role": "assistant", "content": "A."}]}'


def test_good_training_data_is_counted(tmp_path: Path) -> None:
    data = tmp_path / "train.jsonl"
    data.write_text(f"{GOOD}\n\n{GOOD}\n", encoding="utf-8")
    assert check_training_data(data) == 2


@pytest.mark.parametrize(
    ("line", "problem"),
    [
        ("not json", "not valid JSON"),
        ('{"text": "hi"}', "at least one message"),
        ('{"messages": [{"role": "user", "content": "Q?"}]}', "last message must be the answer"),
        ('{"messages": [{"role": "bot", "content": "A"}]}', "unknown role 'bot'"),
        ('{"messages": [{"role": "assistant"}]}', "a role and a text content"),
    ],
)
def test_bad_training_data_is_refused_with_its_line_number(
    tmp_path: Path, line: str, problem: str
) -> None:
    data = tmp_path / "train.jsonl"
    data.write_text(f"{GOOD}\n{line}\n", encoding="utf-8")
    with pytest.raises(LumiError, match="line 2: .*" + re.escape(problem)):
        check_training_data(data)


def test_connecting_to_your_own_server_explains_the_settings(
    capsys: pytest.CaptureFixture[str],
) -> None:
    address = ServerAddress("123", "embeddings", "bge-m3", "nid005001", 23456, "k3y")
    _explain_own_server(address, 8802)
    printed = capsys.readouterr().out
    assert "GAGNVIST_EMBEDDINGS_MODEL=bge-m3" in printed
    assert "GAGNVIST_EMBEDDINGS_URL=http://127.0.0.1:8802/v1" in printed
    assert "GAGNVIST_EMBEDDINGS_KEY=k3y" in printed


@needs_posix
def test_start_jobs_and_stop_from_the_command_line(
    fake_lumi: FakeLumi, capsys: pytest.CaptureFixture[str]
) -> None:
    config = str(fake_lumi.config)
    fake_lumi.add_model("qwen7")
    assert main(["--config", config, "jureca", "start", "chat", "qwen7", "--hours", "2"]) == 0
    printed = capsys.readouterr().out
    job = printed.split("Submitted job ", 1)[1].split(":", 1)[0]
    assert "at most 256 core-hours" in printed

    assert main(["--config", config, "jureca", "jobs"]) == 0
    listed = capsys.readouterr().out
    assert job in listed and "gagnvist-chat" in listed and "PENDING" in listed

    assert main(["--config", config, "jureca", "stop", job]) == 0
    assert fake_lumi.jobs() == []


@needs_posix
def test_models_are_listed_and_deleted_from_the_command_line(
    fake_lumi: FakeLumi, capsys: pytest.CaptureFixture[str]
) -> None:
    config = str(fake_lumi.config)
    assert main(["--config", config, "jureca", "models"]) == 0
    assert "no models of your own" in capsys.readouterr().out
    fake_lumi.add_model("qwen7")
    fake_lumi.add_model("half", complete=False)
    assert main(["--config", config, "jureca", "models"]) == 0
    printed = capsys.readouterr().out
    assert "qwen7" in printed and "complete" in printed and "download not finished" in printed
    assert "FINE-TUNING RUN" not in printed  # there are none

    assert main(["--config", config, "jureca", "delete", "model", "half"]) == 0
    assert "Deleted the model half (" in capsys.readouterr().out
    assert not fake_lumi.mine("models", "half").exists()
    assert fake_lumi.mine("models", "qwen7", "config.json").exists()
    assert main(["--config", config, "jureca", "delete", "run", "half"]) == 1
    assert "no run 'half'" in capsys.readouterr().err


@needs_posix
def test_check_reports_a_ready_account(
    fake_lumi: FakeLumi, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--config", str(fake_lumi.config), "jureca", "check"]) == 0
    printed = capsys.readouterr().out
    assert f"You are a member of the project {PROJECT}." in printed
    assert "The shared models are not running right now." in printed
    assert "All set." in printed


def test_check_reports_a_key_that_is_not_a_team_key(
    fake_lumi: FakeLumi, capsys: pytest.CaptureFixture[str]
) -> None:
    env = fake_lumi.config.parent / ".env"
    env.write_text(env.read_text(encoding="utf-8").replace(TEAM_KEY, "team-01"), encoding="utf-8")
    assert main(["--config", str(fake_lumi.config), "jureca", "check"]) == 1
    printed = capsys.readouterr().out
    assert "PROBLEM: GAGNVIST_TEAM_KEY in .env: it has 7 characters" in printed
    assert "All set." not in printed


@needs_posix
def test_errors_are_printed_without_a_traceback(
    fake_lumi: FakeLumi, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--config", str(fake_lumi.config), "jureca", "stop", "999"]) == 1
    assert (
        "error: a command on JURECA failed: scancel: error: Invalid job id 999"
        in capsys.readouterr().err
    )


def test_training_data_with_a_byte_order_mark_is_accepted(tmp_path: Path) -> None:
    data = tmp_path / "train.jsonl"
    data.write_text(GOOD + "\n", encoding="utf-8-sig")
    assert check_training_data(data) == 1


def test_training_data_that_is_not_utf8_is_explained(tmp_path: Path) -> None:
    data = tmp_path / "train.jsonl"
    data.write_bytes(GOOD.replace("A.", "Árið").encode("cp1252"))
    with pytest.raises(LumiError, match="not UTF-8"):
        check_training_data(data)


@pytest.mark.parametrize(
    ("port", "problem"),
    [("70000", "1024 to 65535"), ("80", "1024 to 65535"), ("x", "not a port number")],
)
def test_connect_refuses_a_port_it_cannot_use(
    port: str, problem: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit):
        main(["jureca", "connect", "--port", port])
    assert problem in capsys.readouterr().err
