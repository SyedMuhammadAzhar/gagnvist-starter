"""A fake JURECA for the tests: ssh, Slurm and the container runtime, all on this
computer. (The names say LUMI, the supercomputer the fake was written for.)

The fake ``ssh`` runs the script it is given right here instead of on the
supercomputer, with its folders (/p) moved into a temporary folder. The fake Slurm
commands (squeue, sbatch, scancel, srun) keep their queue in a JSON file, and the fake
``apptainer`` pretends to download a model, to serve one, or to fine-tune. The job
scripts are bash, so this works on macOS and Linux only.
"""

from __future__ import annotations

import json
import os
import re
import stat
import sys
from pathlib import Path

import pytest

from gagnvist.clusters import CLUSTERS
from gagnvist.config import Settings, load_settings
from gagnvist.lumi.connection import Lumi

USER = "testuser"
ORGANIZER = "organizer"
PROJECT = "training2000"
TEAM_KEY = "0123456789abcdef" * 3  # shaped like a real team key: 48 hex digits
CONTAINER = f"/p/project1/{PROJECT}/{ORGANIZER}/gagnvist/containers/vllm-test.sif"

needs_posix = pytest.mark.skipif(sys.platform == "win32", reason="the job scripts are bash")

_COMMON = """
import json, os, sys
ROOT = os.environ["FAKE_ROOT"]
QUEUE = os.path.join(ROOT, "slurm", "queue.json")
def load():
    with open(QUEUE, encoding="utf-8") as f:
        return json.load(f)
def save(jobs):
    with open(QUEUE, "w", encoding="utf-8") as f:
        json.dump(jobs, f)
"""

# The container runtime: `apptainer exec [--nv] [--bind ...] <container> ...`; the
# command for the container comes after the first argument that ends in .sif.
_CONTAINER_RUNTIME = """
args = sys.argv[1:]
first = next(i for i, argument in enumerate(args) if argument.endswith(".sif"))
command = args[first + 1:]  # after the container
def record(name, **fields):
    with open(os.path.join(ROOT, name), "w", encoding="utf-8") as f:
        json.dump({"argv": command, "pid": os.getpid(), "cwd": os.getcwd(),
                   "runtime": [os.path.basename(sys.argv[0]), *args[:first]], **fields}, f)
if command[:2] == ["vllm", "serve"]:
    import http.server, socketserver, time
    name = command[command.index("--served-model-name") + 1]
    socket_file = command[command.index("--uds") + 1]
    record("vllm-call.json", key=os.environ.get("GAGNVIST_KEY"))
    if name == "broken":
        sys.exit("fake vllm: this model cannot be loaded")
    class Answer(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        def address_string(self):
            return "socket"
        def reply(self, body, status=200):
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def do_GET(self):
            if self.path == "/v1/stream":  # an answer written in pieces, like a streamed chat
                self.send_response(200)
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                for piece in (b"data: one", b"data: two", b"data: three"):
                    self.wfile.write(b"%x\\r\\n%s\\r\\n" % (len(piece), piece))
                    self.wfile.flush()
                    time.sleep(0.1)
                self.wfile.write(b"0\\r\\n\\r\\n")
                return
            answers = {"/health": b"", "/v1/models": json.dumps({"data": [{"id": name}]}).encode(),
                       "/invocations": b"answered without any key"}
            if self.path in answers:
                self.reply(answers[self.path])
            else:
                self.reply(b"not found", 404)
        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            self.reply(json.dumps({"path": self.path, "got": body.decode(),
                                   "authorization": self.headers.get("Authorization")}).encode())
        def log_message(self, *args):
            pass
    class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
        daemon_threads = True
    time.sleep(1)  # "loading the model"
    Server(socket_file, Answer).serve_forever()
elif command[0] in ("python", "python3") and command[1].endswith("key_proxy.py"):
    record("gatekeeper-call.json")
    os.execv(sys.executable, [sys.executable, *command[1:]])  # the real gatekeeper
elif command[0] in ("python", "python3") and command[1].endswith("finetune_lora.py"):
    with open(command[1], encoding="utf-8") as f:
        record("finetune-call.json", script=f.read())
    if os.environ.get("FAKE_SLOW_TRAINING"):  # a training that takes long
        import time
        time.sleep(60)
    output = command[command.index("--output") + 1]
    os.makedirs(output, exist_ok=True)
    open(os.path.join(output, "adapter_config.json"), "w", encoding="utf-8").close()
elif command[0] in ("python", "python3") and command[1] == "-c":  # a download
    target = command[-1]
    record("download-call.json")
    os.makedirs(target, exist_ok=True)
    with open(os.path.join(target, "config.json"), "w", encoding="utf-8") as f:
        json.dump({"downloaded": command[-2], "ignored": "ignore_patterns" in command[2]}, f)
else:
    sys.exit(f"fake container runtime: unexpected command {command}")
"""

_PROGRAMS = {
    "ssh": """
args = sys.argv[1:]
if "-N" in args or args[-1].startswith("sleep "):  # a tunnel, or one through a shared connection
    sys.exit("fake ssh: tunnels are not faked")
if "-O" in args:  # `ssh -O cancel -L ...`: a forwarding taken out of a shared connection
    sys.exit(0)
command = args[-1].replace("bash -lc ", "bash -c ", 1)  # no login scripts here
for top in ("/scratch/", "/appl/", "/p/"):
    command = command.replace(top, ROOT + top)
import subprocess
sys.exit(subprocess.run(["sh", "-c", command]).returncode)
""",
    "squeue": """
import argparse
if os.environ.get("FAKE_SLURM_DOWN"):
    sys.exit("slurm_load_jobs error: Socket timed out on send/recv operation")
parser = argparse.ArgumentParser(add_help=False)
parser.add_argument("--me", action="store_true")
parser.add_argument("-h", action="store_true")
for option in ("-u", "-n", "-t", "-j", "-o"):
    parser.add_argument(option)
args = parser.parse_args()
for job in load():
    if (args.me and job["user"] != os.environ["FAKE_USER"]) \\
            or (args.u and job["user"] != args.u) \\
            or (args.n and job["name"] not in args.n.split(",")) \\
            or (args.t and job["state"] not in args.t.upper().split(",")) \\
            or (args.j and job["id"] != args.j):
        continue
    line = args.o or "%i %j %T"
    for code, key in (("%i", "id"), ("%j", "name"), ("%T", "state"), ("%B", "node"),
                      ("%L", "time_left")):
        line = line.replace(code, job[key])
    print(line)
""",
    "sbatch": """
import re
if os.environ.get("FAKE_SBATCH_REFUSES"):
    sys.exit("sbatch: error: Batch job submission failed: " + os.environ["FAKE_SBATCH_REFUSES"])
options, files = [], []
for argument in sys.argv[1:]:
    if files:
        sys.exit("fake sbatch: arguments after the script would be passed to the script")
    (options if argument.startswith("--") else files).append(argument)
script = open(files[0], encoding="utf-8").read() if files else sys.stdin.read()
jobs = load()
job_id = str(4000 + len(jobs) + 1)
os.makedirs(os.path.join(ROOT, "slurm", "submitted"), exist_ok=True)
submitted = os.path.join(ROOT, "slurm", "submitted", job_id)
with open(submitted + ".sbatch", "w", encoding="utf-8") as f:
    f.write(script)
with open(submitted + ".options", "w", encoding="utf-8") as f:
    json.dump(options, f)
name = re.search(r"^#SBATCH --job-name=(\\S+)", script, re.M).group(1)
jobs.append({"id": job_id, "name": name, "state": "PENDING", "node": "n/a",
             "time_left": "4:00:00", "user": os.environ["FAKE_USER"]})
save(jobs)
print(job_id)
""",
    "scancel": """
job_id = sys.argv[1]
jobs = load()
job = next((j for j in jobs if j["id"] == job_id), None)
if job is None:
    sys.exit(f"scancel: error: Invalid job id {job_id}")
if job["user"] != os.environ["FAKE_USER"]:
    sys.exit(f"scancel: error: Kill job error on job id {job_id}: Access/permission denied")
jobs.remove(job)
save(jobs)
""",
    "apptainer": _CONTAINER_RUNTIME,
}
_SHELL_PROGRAMS = {
    "srun": 'exec "$@"\n',
    "module": "exit 0\n",
    "whoami": 'echo "$FAKE_USER"\n',
    "id": 'echo "$FAKE_USER $FAKE_GROUPS"\n',
    # `sacctmgr show assoc ... format=partition`: one partition per line (JURECA lists
    # the partitions a member's budgets allow), or one empty line where none are listed.
    "sacctmgr": "printf '%s\\n' $FAKE_PARTITIONS\n",
}


def make_programs(folder: Path) -> Path:
    """Write the fake programs into ``folder``, once per test session (a new program can
    take macOS a second to check the first time it runs)."""
    folder.mkdir(parents=True, exist_ok=True)
    for name, body in _PROGRAMS.items():
        _write_program(folder / name, f"#!{sys.executable}\n{_COMMON}{body}")
    for name, body in _SHELL_PROGRAMS.items():
        _write_program(folder / name, f"#!/bin/sh\n{body}")
    return folder


class FakeLumi:
    """A temporary JURECA (or, with ``cluster``, another supercomputer of this edition):
    its folders, its queue, and the settings to reach it."""

    def __init__(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        bin_folder: Path,
        cluster: str = "jureca",
    ) -> None:
        self.cluster = cluster
        self.root = tmp_path / "lumi"
        self.home = tmp_path / "home"
        for folder in (self.root / "slurm", self.home):
            folder.mkdir(parents=True)
        (self.root / "slurm" / "queue.json").write_text("[]", encoding="utf-8")
        container = self.root / CONTAINER.lstrip("/")
        container.parent.mkdir(parents=True, exist_ok=True)
        container.touch()
        self.project_folder.mkdir(parents=True, exist_ok=True)
        if self.organizer_libraries:  # the organizers have installed peft for fine-tuning
            (self.organizer_libraries / "peft").mkdir(parents=True)

        monkeypatch.setenv("PATH", f"{bin_folder}{os.pathsep}{os.environ['PATH']}")
        monkeypatch.setenv("HOME", str(self.home))
        monkeypatch.setenv("FAKE_ROOT", str(self.root))
        monkeypatch.setenv("FAKE_USER", USER)
        # On JURECA, running containers needs the "container" group as well.
        monkeypatch.setenv("FAKE_GROUPS", f"{PROJECT} container")
        # JURECA lists the partitions a member's budgets allow (the GPU ones here).
        monkeypatch.setenv("FAKE_PARTITIONS", "dc-gpu dc-gpu-devel dc-cpu")

        key = tmp_path / "id_ed25519_jureca"
        key.write_text("not a real key", encoding="utf-8")
        self.config = tmp_path / "gagnvist.toml"
        self.config.write_text(_shared_settings(), encoding="utf-8")
        profile = CLUSTERS[cluster]
        personal = {
            profile.username_setting: USER,
            profile.ssh_key_setting: key.as_posix(),
            "GAGNVIST_TEAM_KEY": TEAM_KEY,
            "GAGNVIST_CLUSTER": cluster,
        }
        (tmp_path / ".env").write_text(
            "".join(f"{name}={value}\n" for name, value in personal.items()), encoding="utf-8"
        )
        for name in personal:
            monkeypatch.delenv(name, raising=False)  # the test's .env, not the runner's
        self.settings: Settings = load_settings(self.config)
        self.lumi = Lumi.from_settings(self.settings, cluster)

    @property
    def project(self) -> str:
        return PROJECT

    @property
    def project_folder(self) -> Path:
        """The project's folder on the fake file system (/p/project1/<project> on JURECA)."""
        root = CLUSTERS[self.cluster].project_root.format(project=PROJECT)
        return self.root / root.lstrip("/")

    @property
    def organizer_libraries(self) -> Path | None:
        """The organizers' folder of Python libraries for fine-tuning (peft), where the
        supercomputer's container lacks them; None where it has them."""
        pattern = CLUSTERS[self.cluster].finetune_libraries
        if not pattern:
            return None
        folder = pattern.format(project=PROJECT, gateway_user=ORGANIZER)
        return self.root / folder.lstrip("/")

    def mine(self, *parts: str) -> Path:
        """A path in your gagnvist folder in the fake project folder."""
        return self.project_folder / USER / "gagnvist" / Path(*parts)

    def add_model(self, name: str, *, complete: bool = True) -> Path:
        """A downloaded model; with ``complete=False``, a download that never finished."""
        folder = self.mine("models", name)
        folder.mkdir(parents=True)
        (folder / "config.json").write_text("{}", encoding="utf-8")
        if complete:
            (folder / ".download-complete").touch()
        return folder

    def add_job(
        self,
        job_id: str,
        name: str,
        *,
        state: str = "RUNNING",
        node: str = "jrc0501",
        user: str = USER,
    ) -> None:
        jobs = self.jobs()
        jobs.append(
            {"id": job_id, "name": name, "state": state, "node": node, "time_left": "3:59:00",
             "user": user}
        )  # fmt: skip
        (self.root / "slurm" / "queue.json").write_text(json.dumps(jobs), encoding="utf-8")

    def jobs(self) -> list[dict[str, str]]:
        return json.loads((self.root / "slurm" / "queue.json").read_text(encoding="utf-8"))

    def submitted(self, job_id: str) -> str:
        return (self.root / "slurm" / "submitted" / f"{job_id}.sbatch").read_text(encoding="utf-8")

    def sbatch_options(self, job_id: str) -> list[str]:
        options: list[str] = json.loads(
            (self.root / "slurm" / "submitted" / f"{job_id}.options").read_text(encoding="utf-8")
        )
        return options

    def recorded(self, name: str) -> dict[str, object]:
        """What the fake container runtime wrote down about a call (vllm-call.json,
        gatekeeper-call.json, finetune-call.json, download-call.json)."""
        record: dict[str, object] = json.loads((self.root / name).read_text(encoding="utf-8"))
        return record

    def write_address(self, job_id: str, **fields: object) -> None:
        folder = self.home / ".gagnvist" / "jobs"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{job_id}.json").write_text(
            json.dumps({"job": job_id, **fields}), encoding="utf-8"
        )


def _shared_settings() -> str:
    """The starter kit's gagnvist.toml, with the fake project, organizer and container in
    every supercomputer's section ([jureca], and any other of this edition)."""
    values = {"project": PROJECT, "gateway_user": ORGANIZER, "container": CONTAINER}
    lines, section, replaced = [], "", 0
    shared = (Path(__file__).parents[1] / "gagnvist.toml").read_text(encoding="utf-8")
    for line in shared.splitlines():
        if found := re.match(r"\[(\w+)\]", line):
            section = found[1]
        elif section in CLUSTERS and (found := re.match(r"(\w+) = ", line)) and found[1] in values:
            line = f'{found[1]} = "{values[found[1]]}"'
            replaced += 1
        lines.append(line)
    assert replaced == len(values) * len(CLUSTERS), f"{replaced} values replaced in gagnvist.toml"
    return "\n".join(lines) + "\n"


def make_recording_ssh(folder: Path) -> Path:
    """A fake ssh that only writes down its arguments (to $FAKE_SSH_RECORD), prints
    $FAKE_SSH_ERROR and ends with the status $FAKE_SSH_STATUS."""
    folder.mkdir(parents=True, exist_ok=True)
    _write_program(
        folder / "ssh",
        f"""#!{sys.executable}
import json, os, sys
with open(os.environ["FAKE_SSH_RECORD"], "w", encoding="utf-8") as f:
    json.dump(sys.argv[1:], f)
sys.stderr.write(os.environ.get("FAKE_SSH_ERROR", ""))
sys.exit(int(os.environ.get("FAKE_SSH_STATUS", "0")))
""",
    )
    return folder


def _write_program(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
