"""On Windows, Python joins a command's arguments into one command line, and ssh.exe
splits it again with the rules of the Microsoft C runtime. The scripts sent to the
supercomputer must survive that round trip unchanged."""

import shlex
import subprocess

import pytest

from gagnvist.clusters import JURECA
from gagnvist.lumi import jobs


def windows_split(command_line: str) -> list[str]:
    """Split a command line the way a Windows program (the Microsoft C runtime) does."""
    arguments: list[str] = []
    current, quoted, in_argument, i = "", False, False, 0
    while i < len(command_line):
        character = command_line[i]
        if character == "\\":
            run = len(command_line[i:]) - len(command_line[i:].lstrip("\\"))
            if i + run < len(command_line) and command_line[i + run] == '"':
                current += "\\" * (run // 2)
                if run % 2:  # an escaped quote
                    current += '"'
                    i += run + 1
                else:  # the quote opens or closes a quoted part
                    i += run
                in_argument = True
                continue
            current += "\\" * run
            i += run
            in_argument = True
            continue
        if character == '"':
            quoted = not quoted
            in_argument = True
        elif character in " \t" and not quoted:
            if in_argument:
                arguments.append(current)
            current, in_argument = "", False
        else:
            current += character
            in_argument = True
        i += 1
    if in_argument:
        arguments.append(current)
    return arguments


class Recorder:
    """Stands in for Lumi: records the scripts that would be sent."""

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.scripts: list[str] = []

    def run(self, script: str, *, stdin: bytes | None = None, show_output: bool = False) -> str:
        self.scripts.append(script)
        return self.reply

    cluster = JURECA  # as a Lumi knows which supercomputer it logs in to
    label = JURECA.label


def test_the_splitter_follows_the_windows_rules() -> None:
    assert windows_split('a "b c" d') == ["a", "b c", "d"]
    assert windows_split(r'"a\"b"') == ['a"b']
    assert windows_split(r"a\\b") == [r"a\\b"]
    assert windows_split(r'"a\\" b') == ["a\\", "b"]


@pytest.mark.parametrize(
    "script",
    [
        "squeue --me -h -o '@job %i|%j|%T|%B|%L'",
        'echo "@state $(squeue --me -h -j 12 -o %T 2>&1)"\nif [ -f ~/.x ]; then echo ok; fi',
        'printf \'%s\\n\' "$queue"\nfor f in ~/.gagnvist/jobs/*.json; do echo "$f"; done',
        'tail -n 40 "${logs[0]}"  # Íslenskir stafir: ð þ æ ö',
    ],
)
def test_scripts_survive_the_windows_command_line(script: str) -> None:
    key = r"C:\Users\Jón Jónsson\.ssh\id_ed25519_jureca"
    command = ["ssh", "-i", key, "u@jureca.fz-juelich.de"]
    command.append("bash -lc " + shlex.quote(script))
    assert windows_split(subprocess.list2cmdline(command)) == command


def test_the_real_remote_scripts_survive_the_windows_command_line(
    fake_lumi_settings: object,
) -> None:
    recorder = Recorder("@job 1\n@gateway nid1\n@node nid1\n@user u\n@groups g\n")
    settings = fake_lumi_settings
    jobs.list_jobs(recorder)  # type: ignore[arg-type]
    jobs.check_account(recorder, settings)  # type: ignore[arg-type]
    jobs.find_gateway(recorder, settings)  # type: ignore[arg-type]
    jobs.start_server(recorder, settings, jobs.ServerRequest("chat", "qwen7"))  # type: ignore[arg-type]
    assert len(recorder.scripts) == 4
    for script in recorder.scripts:
        command = ["ssh", "u@jureca.fz-juelich.de", "bash -lc " + shlex.quote(script)]
        assert windows_split(subprocess.list2cmdline(command)) == command
