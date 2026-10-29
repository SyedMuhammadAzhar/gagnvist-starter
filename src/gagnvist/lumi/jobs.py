"""Your own work on LUMI: models, model servers and fine-tuning jobs.

Everything here runs under your own LUMI account, so Slurm itself guarantees that you
can only see the details of, and stop, your own jobs. Your files live in two places:

    /scratch/<project>/<username>/gagnvist/   models, fine-tuning runs and caches;
                                              your teammates can read them, but only
                                              you can change them
    ~/.gagnvist/                              job logs, and the address and key of each
                                              running server (your home folder, which
                                              only you can read)

Each function sends one short script to a LUMI login node (see :class:`Lumi`). The
values put into the scripts are checked against strict patterns first (see
:func:`_checked`), so that a typing mistake cannot turn into a different command.

Every member of the hackathon's project can create and rename folders at the top of
the project's /scratch folder. So the scripts check that your folders there belong to
you before using them, and the jobs never run a program kept there: the training script
and the gatekeeper of a server travel inside the job script itself.
"""

from __future__ import annotations

import io
import json
import re
import tarfile
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from gagnvist.config import Settings
from gagnvist.lumi.connection import Lumi, LumiError

# Limits the starter kit sets, so that no team can use up the shared GPU budget.
MAX_JOBS = 2  # your jobs, running or waiting, at the same time
GPU_CHOICES = (1, 2, 4)  # GPU chips (GCDs) per job: a model is split evenly between them
MAX_HOURS = 12  # hours per job
PARTITIONS = ("small-g", "dev-g")  # dev-g starts sooner but allows at most 3 hours

JOB_NAMES = ("gagnvist-chat", "gagnvist-embeddings", "gagnvist-finetune")
CPUS_PER_GPU = 7  # LUMI bills a GPU chip at 0.5 GPU-hours per hour up to 8 cores and 64 GB
LOGS = "$HOME/.gagnvist/logs"  # as written in the scripts, where the shell expands $HOME

# Files of a model repository that vLLM does not need (other formats of the weights).
_NOT_DOWNLOADED = [
    "original/*", "*.pth", "*.gguf", "onnx/*", "*.onnx", "openvino/*", "*.msgpack", "*.h5",
    "flax_model*", "tf_model*", "rust_model*", "coreml/*",
]  # fmt: skip

_PATTERNS = {
    "username": r"[a-z][a-z0-9_-]*",
    "project": r"project_\d+",
    "container": r"/[A-Za-z0-9_./-]+\.sif",
    "repo": r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*",
    "name": r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}",
    "path": r"/(?:scratch|project|flash)/project_\d+/[A-Za-z0-9_./-]+",
    "job": r"\d+",
    "node": r"[a-z0-9-]+",
}

# A shell function for the scripts below: make sure a folder is a real folder that
# belongs to you, and that only you can write in it; otherwise stop.
_OWN_FOLDER = """
own_folder() {
    if [ -L "$1" ] || ! mkdir -p "$1" || [ ! -O "$1" ] || ! chmod go-w "$1"; then
        echo "$1 is not a folder of yours (someone else's, or a link), so your files" >&2
        echo "would not be safe there: please tell the organizers" >&2
        exit 3
    fi
}
"""


@dataclass(frozen=True)
class Folders:
    """Where gagnvist keeps your files in the project's /scratch folder on LUMI."""

    project: str
    username: str

    @classmethod
    def from_settings(cls, settings: Settings) -> Folders:
        return cls(
            _checked("project", settings.lumi.project),
            _checked("username", settings.lumi.username),
        )

    @property
    def yours(self) -> str:
        return f"/scratch/{self.project}/{self.username}"

    @property
    def base(self) -> str:
        return f"{self.yours}/gagnvist"

    @property
    def models(self) -> str:
        return f"{self.base}/models"

    @property
    def finetune(self) -> str:
        return f"{self.base}/finetune"

    @property
    def cache(self) -> str:
        return f"{self.base}/cache"

    def check(self, *folders: str) -> str:
        """Shell lines that make sure your folders, and then ``folders``, are yours."""
        lines = [f"own_folder {folder}" for folder in (self.yours, self.base, *folders)]
        return _OWN_FOLDER + "\n".join(lines)


@dataclass(frozen=True)
class Job:
    """One of your Slurm jobs."""

    id: str
    name: str
    state: str  # PENDING, RUNNING, COMPLETING, ...
    node: str  # where it runs; empty while it waits
    time_left: str
    ready: bool  # a model server that has loaded its model and answers


@dataclass(frozen=True)
class ServerAddress:
    """Where one of your model servers answers, as its job wrote it down."""

    job: str
    kind: str  # "chat" or "embeddings"
    model: str  # the name to put in requests (and in .env)
    node: str
    port: int
    key: str


@dataclass(frozen=True)
class ServerRequest:
    """What `gagnvist lumi start` asks for."""

    kind: str  # "chat" or "embeddings"
    model: str  # a model folder name in your models folder, or a full path on LUMI
    gpus: int = 1
    hours: int = 4
    partition: str = "small-g"
    context: int = 8192  # the longest conversation (prompt and answer), in tokens
    adapter: str = ""  # the name of one of your fine-tuning runs, to serve with the model


@dataclass(frozen=True)
class FinetuneRequest:
    """What `gagnvist lumi finetune` asks for."""

    model: str
    data: Path  # a JSON Lines file of conversations on this computer
    name: str  # the run's name, used for its folder and when serving the adapter
    epochs: int = 1
    rank: int = 16
    learning_rate: float = 2e-4
    hours: int = 2
    partition: str = "small-g"


def find_gateway(lumi: Lumi, settings: Settings) -> str:
    """The node where the organizers' gateway to the shared models runs.

    Slurm shows every user which node a job runs on, so this asks Slurm for the running
    job of the organizer named in gagnvist.toml; only that account can start or stop it.
    """
    settings.require_gateway()
    user = _checked("username", settings.shared_services.gateway_user)
    job = _checked("name", settings.shared_services.gateway_job)
    output = lumi.run(f"squeue -u {user} -n {job} -t RUNNING -h -o '@node %B'")
    nodes = _tagged(output, "@node")
    if not nodes:
        raise LumiError(
            f"the shared models are not running right now (there is no running job "
            f"{job!r} of {user!r}): please tell the organizers"
        )
    return _checked("node", nodes[0])


def check_account(lumi: Lumi, settings: Settings) -> dict[str, str]:
    """What LUMI says about your account: user name, groups, the gateway's node, and
    whether the project folder and the container for model jobs can be found."""
    folders = Folders.from_settings(settings)
    gateway_user = _checked("username", settings.shared_services.gateway_user)
    gateway_job = _checked("name", settings.shared_services.gateway_job)
    container = _checked("container", settings.lumi.container)
    output = lumi.run(
        f"""
        echo "@user $(whoami)"
        echo "@groups $(id -Gn)"
        if [ -d /scratch/{folders.project} ]; then echo "@scratch yes"; fi
        if [ -r {container} ]; then echo "@container yes"; fi
        if gateway=$(squeue -u {gateway_user} -n {gateway_job} -t RUNNING -h -o %B); then
            echo "@gateway $gateway"
        else
            echo "@slurm failed"
        fi
        """
    )
    if _tagged(output, "@slurm"):
        raise LumiError("Slurm, LUMI's job system, did not answer; try again in a minute")
    facts = {}
    for tag in ("@user", "@groups", "@scratch", "@container", "@gateway"):
        values = _tagged(output, tag)
        facts[tag[1:]] = values[0] if values else ""
    return facts


def download_model(lumi: Lumi, settings: Settings, repo: str, name: str) -> str:
    """Download a model from Hugging Face into your models folder; return its path.

    Models are downloaded once, on the login node, so that jobs start at once and never
    wait for a download. The download's progress is shown as it happens; an interrupted
    download is continued by running the command again. A model that needs a licence
    accepted on Hugging Face also needs your Hugging Face token on LUMI, in
    ~/.cache/huggingface/token (see docs/lumi.md).
    """
    folders = Folders.from_settings(settings)
    repo = _checked("repo", repo)
    target = f"{folders.models}/{_checked('name', name)}"
    container = _checked("container", settings.lumi.container)
    download = (
        "import sys; from huggingface_hub import snapshot_download; "
        "snapshot_download(repo_id=sys.argv[1], local_dir=sys.argv[2], "
        f"ignore_patterns={_NOT_DOWNLOADED!r})"
    )
    lumi.run(
        f"""
        umask 022
        {folders.check(folders.models, folders.cache, target)}
        if [ -f {target}/.download-complete ]; then echo "Already downloaded: {target}"; exit 0; fi
        module purge >/dev/null 2>&1
        module load Local-LAIF lumi-aif-singularity-bindings >/dev/null 2>&1 || exit 1
        set -euo pipefail
        export HF_HUB_CACHE={folders.cache}/huggingface  # not in your small home folder
        singularity run {container} python -c "{download}" {repo} {target}
        touch {target}/.download-complete
        echo "Downloaded {repo} to {target}"
        """,
        show_output=True,
    )
    return target


def start_server(lumi: Lumi, settings: Settings, request: ServerRequest) -> str:
    """Submit a job that serves a model with vLLM; return the job's id."""
    folders = Folders.from_settings(settings)
    if request.kind not in ("chat", "embeddings"):
        raise LumiError(f"a server is for chat or embeddings, not {request.kind!r}")
    _check_resources(request.gpus, request.hours, request.partition)
    if not 512 <= request.context <= 131072:
        raise LumiError(f"give a context of 512 to 131072 tokens, not {request.context}")
    model_path = _model_path(folders, request.model)
    served_name = _checked("name", Path(model_path).name)  # the base model's name
    request_name = served_name  # the name requests use: the adapter's, if there is one
    if request.kind == "embeddings":
        extra = ["--runner pooling"]
    else:
        extra = [f"--max-model-len {request.context}", "--gpu-memory-utilization 0.9"]
    checks = [_model_must_exist(folders, model_path)]
    if request.adapter:
        if request.kind != "chat":
            raise LumiError("an adapter can only be served with a chat model")
        request_name = _checked("name", request.adapter)
        if request_name == served_name:
            raise LumiError("give the fine-tuning run a name other than the model's")
        adapter = f"{folders.finetune}/{request_name}/adapter"
        extra += [f"--enable-lora --lora-modules {request_name}={adapter}", "--max-lora-rank 64"]
        checks.append(_must_exist(f"{adapter}/adapter_config.json", adapter))
    script = render_template(
        "serve.sbatch",
        job_name=f"gagnvist-{request.kind}",
        kind=request.kind,
        project=folders.project,
        partition=request.partition,
        gpus=str(request.gpus),
        cpus=str(CPUS_PER_GPU * request.gpus),
        hours=str(request.hours),
        container=_checked("container", settings.lumi.container),
        model_path=model_path,
        served_name=served_name,
        request_name=request_name,
        extra_arguments=" ".join(extra),
        key_proxy=_template_text("key_proxy.py"),
    )
    return _submit(lumi, checks, stdin=script.encode())  # sbatch reads the script itself


def start_finetune(lumi: Lumi, settings: Settings, request: FinetuneRequest) -> str:
    """Upload the training data and submit a LoRA fine-tuning job; return the job's id."""
    folders = Folders.from_settings(settings)
    _check_resources(1, request.hours, request.partition)
    if not 1 <= request.epochs <= 20:
        raise LumiError(f"give 1 to 20 epochs, not {request.epochs}")
    if not 0 < request.learning_rate < 1:
        raise LumiError(f"give a learning rate between 0 and 1, not {request.learning_rate}")
    if request.rank not in (8, 16, 32, 64):
        raise LumiError(f"the LoRA rank is 8, 16, 32 or 64, not {request.rank}")
    model_path = _model_path(folders, request.model)
    run_folder = f"{folders.finetune}/{_checked('name', request.name)}"
    script = render_template(
        "finetune.sbatch",
        project=folders.project,
        partition=request.partition,
        cpus=str(CPUS_PER_GPU),
        hours=str(request.hours),
        container=_checked("container", settings.lumi.container),
        model_path=model_path,
        run_folder=run_folder,
        run_name=request.name,
        epochs=str(request.epochs),
        rank=str(request.rank),
        learning_rate=repr(request.learning_rate),
        finetune_script=_template_text("finetune_lora.py"),
    )
    upload = _tar({"train.jsonl": request.data.read_bytes(), "finetune.sbatch": script.encode()})
    # The upload is unpacked in your private home folder first, and only the data is
    # moved to the run folder, so the job script never lies in a shared folder.
    checks = [
        _model_must_exist(folders, model_path),
        f"if [ -e {run_folder} ]; then echo '@exists {run_folder}'; exit 0; fi",
        folders.check(folders.finetune, run_folder),
        "upload=$(mktemp -d ~/.gagnvist/upload.XXXXXX)",
        "trap 'rm -rf \"$upload\"' EXIT",
        'tar -xf - -C "$upload"',
        f'mv "$upload/train.jsonl" {run_folder}/train.jsonl',
    ]
    return _submit(lumi, checks, stdin=upload, script='"$upload/finetune.sbatch"')


def list_jobs(lumi: Lumi) -> list[Job]:
    """Your jobs on LUMI (all of them, not only gagnvist's), oldest first."""
    output = lumi.run(
        """
        if queue=$(squeue --me -h -o '@job %i|%j|%T|%B|%L'); then
            printf '%s\\n' "$queue"
        else
            echo "@slurm failed"
        fi
        for file in ~/.gagnvist/jobs/*.json; do
            if [ -e "$file" ]; then echo "@ready $(basename "$file" .json)"; fi
        done
        """
    )
    if _tagged(output, "@slurm"):
        raise LumiError("Slurm, LUMI's job system, did not answer; try again in a minute")
    ready = set(_tagged(output, "@ready"))
    jobs = []
    for line in _tagged(output, "@job"):
        job_id, name, state, node, time_left = (line.split("|") + [""] * 5)[:5]
        node = "" if node in ("n/a", "(null)", "None assigned") else node
        jobs.append(Job(job_id, name, state, node, time_left, job_id in ready))
    return jobs


def server_address(lumi: Lumi, job: str) -> ServerAddress:
    """Where your model server in ``job`` answers, once it has loaded its model."""
    job = _checked("job", job)
    output = lumi.run(
        f"""
        if state=$(squeue --me -h -j {job} -o %T 2>&1); then
            echo "@state $state"
        elif printf '%s' "$state" | grep -q "Invalid job id"; then
            echo "@state ended"
        else
            echo "@slurm failed"
        fi
        if [ -f ~/.gagnvist/jobs/{job}.json ]; then
            echo "@address $(cat ~/.gagnvist/jobs/{job}.json)"
        fi
        """
    )
    if _tagged(output, "@slurm"):
        raise LumiError("Slurm, LUMI's job system, did not answer; try again in a minute")
    state = (_tagged(output, "@state") or [""])[0]
    addresses = _tagged(output, "@address")
    if state in ("PENDING", "CONFIGURING"):
        raise LumiError(f"job {job} is still waiting for a GPU; try again in a while")
    if state != "RUNNING":
        raise LumiError(f"job {job} is not one of your running jobs (see: gagnvist lumi jobs)")
    if not addresses:
        raise LumiError(
            f"job {job} is still loading its model, or is not a model server; try again in "
            f"a minute (its log: gagnvist lumi log {job})"
        )
    try:
        found = json.loads(addresses[0])
        address = ServerAddress(
            job=str(found["job"]),
            kind=str(found["kind"]),
            model=str(found["model"]),
            node=_checked("node", str(found["node"])),
            port=int(found["port"]),
            key=str(found["key"]),
        )
    except (ValueError, KeyError, TypeError) as e:
        raise LumiError(f"the address file of job {job} could not be read: {e}") from e
    if address.kind not in ("chat", "embeddings") or not 1024 <= address.port <= 65535:
        raise LumiError(f"the address file of job {job} is not a model server's")
    return address


def stop_job(lumi: Lumi, job: str) -> None:
    """Cancel one of your jobs. Slurm refuses to cancel anybody else's."""
    job = _checked("job", job)
    lumi.run(f"set -e\nscancel {job}\nrm -f ~/.gagnvist/jobs/{job}.json")


def job_log(lumi: Lumi, job: str, lines: int = 40) -> str:
    """The last ``lines`` lines of a job's log."""
    job = _checked("job", job)
    if not 1 <= lines <= 10_000:
        raise LumiError(f"ask for 1 to 10000 lines, not {lines}")
    output = lumi.run(
        f"""
        shopt -s nullglob
        logs=({LOGS}/*-{job}.log)
        if [ ${{#logs[@]}} -eq 0 ]; then
            echo "@none yes"
        else
            tail -n {lines} "${{logs[0]}}"
        fi
        """
    )
    if _tagged(output, "@none"):
        raise LumiError(f"there is no log for job {job} (logs are kept in ~/.gagnvist/logs)")
    return output


def render_template(name: str, **values: str) -> str:
    """A job script from ``job_templates/``, with every {{placeholder}} filled in."""
    text = _template_text(name)
    for key, value in values.items():
        placeholder = "{{" + key + "}}"
        if placeholder not in text:
            raise ValueError(f"{name} has no placeholder {placeholder}")
        text = text.replace(placeholder, value)
    left = re.findall(r"\{\{\w+\}\}", text)
    if left:
        raise ValueError(f"{name}: no value given for {', '.join(sorted(set(left)))}")
    return text


def _submit(lumi: Lumi, checks: list[str], *, stdin: bytes, script: str = "") -> str:
    """Run ``checks``, then submit the job, unless you already have MAX_JOBS jobs.

    The job script is ``script`` (a path on LUMI that ``checks`` put there), or else
    what ``stdin`` holds. The job's log goes to your home folder.
    """
    names = ",".join(JOB_NAMES)
    check_lines = "\n".join(checks)
    output = lumi.run(
        f"""
        set -euo pipefail
        umask 022
        jobs=$(squeue --me -h -n {names} -o %i | wc -l | tr -d ' ')
        if [ "$jobs" -ge {MAX_JOBS} ]; then echo "@too-many $jobs"; exit 0; fi
        mkdir -p {LOGS} ~/.gagnvist/jobs
        chmod 700 ~/.gagnvist
        {check_lines}
        job=$(sbatch --parsable --output="{LOGS}/%x-%j.log" {script})
        echo "@job $job"
        """,
        stdin=stdin,
    )
    if found := _tagged(output, "@too-many"):
        raise LumiError(
            f"you already have {found[0]} gagnvist jobs (the limit is {MAX_JOBS}): stop one "
            "first (gagnvist lumi jobs, gagnvist lumi stop JOB)"
        )
    if found := _tagged(output, "@missing"):
        raise LumiError(f"{found[0]} was not found on LUMI (gagnvist lumi download ...?)")
    if found := _tagged(output, "@incomplete"):
        raise LumiError(
            f"the download of {found[0]} did not finish: run `gagnvist lumi download` again"
        )
    if found := _tagged(output, "@exists"):
        raise LumiError(f"{found[0]} already exists: choose another name with --name")
    job_ids = [line.split(";")[0] for line in _tagged(output, "@job")]
    if not job_ids or not job_ids[0].isdigit():
        raise LumiError(f"sbatch did not return a job id: {output[-300:]}")
    return job_ids[0]


def _must_exist(path: str, shown: str) -> str:
    """A line of shell that stops the submission, with a note, if ``path`` is missing."""
    return f"if [ ! -e {path} ]; then echo '@missing {shown}'; exit 0; fi"


def _model_must_exist(folders: Folders, model_path: str) -> str:
    """Shell lines that stop the submission unless the model is complete: for a model you
    downloaded, its download finished; for a full path, the folder holds a model."""
    lines = [_must_exist(f"{model_path}/config.json", model_path)]
    if model_path.startswith(f"{folders.models}/"):
        complete = f"{model_path}/.download-complete"
        lines.append(f"if [ ! -e {complete} ]; then echo '@incomplete {model_path}'; exit 0; fi")
    return "\n".join(lines)


def _model_path(folders: Folders, model: str) -> str:
    """A model folder name in your models folder, or a full path on LUMI (for example a
    teammate's model)."""
    if model.startswith("/"):
        return _checked("path", model.rstrip("/"))
    return f"{folders.models}/{_checked('name', model)}"


def _check_resources(gpus: int, hours: int, partition: str) -> None:
    if partition not in PARTITIONS:
        raise LumiError(f"use the partition {' or '.join(PARTITIONS)}, not {partition!r}")
    if gpus not in GPU_CHOICES:
        choices = ", ".join(str(n) for n in GPU_CHOICES)
        raise LumiError(f"ask for {choices} GPU chips (a model is split evenly), not {gpus}")
    longest = 3 if partition == "dev-g" else MAX_HOURS
    if not 1 <= hours <= longest:
        raise LumiError(f"ask for 1 to {longest} hours on {partition}, not {hours}")


def _checked(kind: str, value: str) -> str:
    """``value`` if it matches the pattern for ``kind``, so it is safe in a shell script."""
    if not re.fullmatch(_PATTERNS[kind], value) or ".." in value:
        raise LumiError(f"{value!r} is not a valid {kind} here")
    return value


def _tagged(output: str, tag: str) -> list[str]:
    """The values of the output lines that start with ``tag`` (other lines, such as
    messages from LUMI's login scripts, are ignored)."""
    prefix = tag + " "
    return [line[len(prefix) :].strip() for line in output.splitlines() if line.startswith(prefix)]


def _template_text(name: str) -> str:
    # utf-8-sig: a template edited in Notepad may begin with a byte-order mark, and sbatch
    # wants #! as the very first characters. (Windows line endings become \n on reading.)
    template = resources.files("gagnvist.lumi").joinpath("job_templates", name)
    return template.read_text("utf-8-sig")


def _tar(files: dict[str, bytes]) -> bytes:
    """A tar archive of ``files`` ({name: content}), to unpack on LUMI in one step."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for name, content in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            info.mode = 0o600
            archive.addfile(info, io.BytesIO(content))
    return buffer.getvalue()
