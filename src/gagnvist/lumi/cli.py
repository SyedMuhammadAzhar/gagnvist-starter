"""The ``gagnvist lumi`` and ``gagnvist jureca`` commands: tunnels to the shared models,
and jobs of your own, on either supercomputer.

Both have the same sub-commands (check, connect, download, start, finetune, jobs, log,
stop), made by :func:`add_cluster_commands` from one supercomputer's profile (see
:mod:`gagnvist.clusters`). Like the other commands, each one only reads the settings,
calls the library (:mod:`gagnvist.lumi.jobs`, :mod:`gagnvist.lumi.tunnel`) and prints
the outcome.
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Callable
from pathlib import Path

from gagnvist.clusters import JURECA, LUMI, Cluster
from gagnvist.config import Settings, team_key_problem
from gagnvist.lumi.agent import remember_key
from gagnvist.lumi.connection import Lumi, LumiError
from gagnvist.lumi.jobs import (
    FinetuneRequest,
    ServerAddress,
    ServerRequest,
    check_account,
    delete_stored,
    download_model,
    find_gateway,
    job_log,
    list_jobs,
    list_stored,
    server_address,
    start_finetune,
    start_server,
    stop_job,
)
from gagnvist.lumi.tunnel import hold_tunnel, try_key

Command = Callable[[argparse.Namespace, Settings], int]

# Ports on your computer for tunnels to servers of your own (the shared models use
# [shared_services] local_port), so that a chat and an embedding server can be open at
# once; JURECA's are in its profile, so that both supercomputers' can be open at once.
MAX_TRAINING_FILE = 100_000_000  # bytes


def add_lumi_commands(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add ``gagnvist lumi ...`` to the main command's sub-commands."""
    add_cluster_commands(commands, LUMI)


def add_jureca_commands(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add ``gagnvist jureca ...``, the same commands for the second supercomputer."""
    add_cluster_commands(commands, JURECA)


def add_cluster_commands(
    commands: argparse._SubParsersAction[argparse.ArgumentParser], cluster: Cluster
) -> None:
    """Add ``gagnvist <cluster> ...`` to the main command's sub-commands."""
    name, label = cluster.name, cluster.label
    top = commands.add_parser(name, help=f"the shared models, and your own jobs, on {label}")
    top.set_defaults(cluster=name)  # which supercomputer every command below works on
    sub = top.add_subparsers(title=f"{name} commands", metavar="COMMAND", required=True)

    check = sub.add_parser(
        "check", help=f"check that you can log in to {label} and use the project"
    )
    check.set_defaults(command=_check)

    connect = sub.add_parser(
        "connect", help="open the tunnel to the shared models (or to a server of your own)"
    )
    connect.add_argument("--job", help="connect to your own model server in this job instead")
    connect.add_argument(
        "--port", type=_port, help="the port on this computer for the tunnel (1024 to 65535)"
    )
    connect.set_defaults(command=_connect)

    download = sub.add_parser(
        "download", help=f"download a model from Hugging Face into your folder on {label}"
    )
    download.add_argument(
        "repo", help="the model's name on Hugging Face, e.g. Qwen/Qwen2.5-7B-Instruct"
    )
    download.add_argument("--name", help=f"the folder name on {label} (default: the part after /)")
    download.set_defaults(command=_download)

    models = sub.add_parser("models", help=f"list your models and fine-tuning runs on {label}")
    models.set_defaults(command=_models)

    delete = sub.add_parser("delete", help="delete one of your models or fine-tuning runs")
    delete.add_argument("kind", choices=["model", "run"], help="what to delete")
    delete.add_argument("name", help=f"its name, as `gagnvist {name} models` lists it")
    delete.set_defaults(command=_delete)

    start = sub.add_parser("start", help="start a model server of your own (a Slurm job)")
    start.add_argument("kind", choices=["chat", "embeddings"], help="what the model is for")
    start.add_argument("model", help="a model you downloaded (its folder name), or a full path")
    _add_resources(start, cluster, default_hours=4)
    start.add_argument(
        "--context",
        type=int,
        default=8192,
        help="longest conversation in tokens, for chat models (default: 8192)",
    )
    start.add_argument("--adapter", help="also serve this fine-tuning run's adapter (chat only)")
    start.set_defaults(command=_start)

    finetune = sub.add_parser("finetune", help="fine-tune a model with LoRA (a Slurm job)")
    finetune.add_argument("model", help="a model you downloaded (its folder name), or a full path")
    finetune.add_argument("data", type=Path, help="a .jsonl file of conversations on this computer")
    finetune.add_argument("--name", help="a name for this run (default: run-<date>-<time>)")
    finetune.add_argument("--epochs", type=int, default=1, help="passes over the data (default: 1)")
    finetune.add_argument(
        "--rank",
        type=int,
        choices=[8, 16, 32, 64],
        default=16,
        help="LoRA rank: bigger learns more, but needs more data (default: 16)",
    )
    finetune.add_argument(
        "--learning-rate", type=float, default=2e-4, help="how big each step is (default: 0.0002)"
    )
    _add_resources(finetune, cluster, default_hours=2, gpus=False)
    finetune.set_defaults(command=_finetune)

    jobs = sub.add_parser("jobs", help=f"list your jobs on {label}")
    jobs.set_defaults(command=_jobs)

    log = sub.add_parser("log", help="show the end of a job's log")
    log.add_argument("job")
    log.add_argument("--lines", type=int, default=40, help="how many lines (default: 40)")
    log.set_defaults(command=_log)

    stop = sub.add_parser("stop", help="stop one of your jobs (and its cost)")
    stop.add_argument("job")
    stop.set_defaults(command=_stop)


def _add_resources(
    parser: argparse.ArgumentParser, cluster: Cluster, *, default_hours: int, gpus: bool = True
) -> None:
    if gpus:
        parser.add_argument(
            "--gpus",
            type=int,
            choices=cluster.gpu_choices,
            default=1,
            help="GPUs: a model too big for one is split evenly (default: 1)",
        )
    most = cluster.partition_hours[cluster.partitions[0]]
    default_hours = min(default_hours, most)
    parser.add_argument(
        "--hours",
        type=int,
        default=default_hours,
        help=f"the job stops after this many hours, at most {most} (default: {default_hours})",
    )
    parser.add_argument(
        "--partition",
        choices=cluster.partitions,
        default=cluster.partitions[0],
        help=cluster.partition_help,
    )


def _port(text: str) -> int:
    """A port number for a tunnel on this computer (below 1024 needs administrator rights)."""
    try:
        port = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a port number: {text!r}") from None
    if not 1024 <= port <= 65535:
        raise argparse.ArgumentTypeError(f"use a port from 1024 to 65535, not {port}")
    return port


def _login(args: argparse.Namespace, settings: Settings) -> Lumi:
    """Your account on the supercomputer the command is for."""
    return Lumi.from_settings(settings, args.cluster)


def _check(args: argparse.Namespace, settings: Settings) -> int:
    lumi = _login(args, settings)
    remember_key(lumi.ssh_key)
    print(f"Logging in to {lumi.host} as {lumi.username} with the key {lumi.ssh_key} ...")
    facts = check_account(lumi, settings)
    account = settings.cluster(lumi.cluster.name)
    project = account.project
    problems = []
    print(f"  You are logged in as {facts['user']}.")
    groups = facts["groups"].split()
    if project in groups:
        print(f"  You are a member of the project {project}.")
    else:
        problems.append(f"your account is not (yet) a member of the project {project}")
    if not facts["scratch"]:
        root = lumi.cluster.project_root.format(project=project)
        problems.append(f"the project folder {root} cannot be seen")
    for problem in problems:
        print(f"  PROBLEM: {problem}; please tell the organizers.")
    if not facts["container"]:
        print(
            f"  NOTE: the container for jobs of your own is not there (yet): "
            f"{account.container}; `download`, `start` and `finetune` wait for it, the "
            "shared models work anyway. Tell the organizers if it stays missing."
        )
    needed = lumi.cluster.container_group
    if needed and needed not in groups:
        print(
            f"  NOTE: your account is not in the group {needed!r} yet, so `gagnvist "
            f"{lumi.cluster.name} download` and jobs of your own cannot run containers "
            f"there; the shared models work anyway. See {lumi.cluster.docs}."
        )
    allowed = facts["partitions"].split()  # empty where Slurm lists no partitions (LUMI)
    if allowed and not any(partition in allowed for partition in lumi.cluster.partitions):
        print(
            f"  NOTE: your account cannot use the GPU partitions of {project} "
            f"({', '.join(lumi.cluster.partitions)}) yet, so jobs of your own cannot start; "
            f"the shared models work anyway. {lumi.cluster.partition_access_hint} "
            f"See {lumi.cluster.docs}."
        )
    key = settings.shared_services.team_key
    key_problem = (
        "it is not filled in"
        if not key or key == "paste-your-team-key-here"
        else team_key_problem(key)
    )
    if key_problem:
        print(f"  PROBLEM: GAGNVIST_TEAM_KEY in .env: {key_problem}. Copy your team's key again.")
    if facts["gateway"]:
        print(f"  The shared models are running (on {facts['gateway']}).")
        if not key_problem:
            answer = try_key(lumi, facts["gateway"], account.gateway_port, key)
            if answer.startswith("Connected"):
                print("  Your team key works.")
            elif "refused the key" in answer:
                key_problem = "refused"
                print(
                    "  PROBLEM: the shared models refused your team key: check GAGNVIST_TEAM_KEY."
                )
            else:
                print(f"  Your team key could not be tried yet: {answer}")
    else:
        print("  The shared models are not running right now.")
    if problems or key_problem:
        return 1
    print(f"All set. Next: gagnvist {lumi.cluster.name} connect")
    return 0


def _connect(args: argparse.Namespace, settings: Settings) -> int:
    lumi = _login(args, settings)
    remember_key(lumi.ssh_key)
    cluster = lumi.cluster
    if settings.default_cluster != cluster.name:
        print(
            f"Note: the other commands use the shared models on "
            f"{settings.cluster().profile.label} (for whatever a server of your own does "
            f"not serve); to use {cluster.label}'s, add GAGNVIST_CLUSTER={cluster.name} to "
            f".env, or --cluster {cluster.name} to each command."
        )
    if args.job:
        address = server_address(lumi, args.job)
        port = args.port or cluster.own_server_ports[address.kind]
        _explain_own_server(address, port)

        def find_own_server() -> tuple[str, int]:
            found = server_address(lumi, args.job)
            return found.node, found.port

        hold_tunnel(lumi, port, find_own_server, address.key, label=lumi.label)
    else:
        settings.require_team_key()
        settings.require_gateway(cluster.name)
        account = settings.cluster(cluster.name)
        expected = account.local_port
        port = args.port or expected
        if port != expected:
            print(
                f"Note: the other commands look for the shared models on port {expected}; "
                f"to use port {port}, set {cluster.local_port_setting}={port} in .env."
            )

        def find_shared_models() -> tuple[str, int]:
            return find_gateway(lumi, settings), account.gateway_port

        hold_tunnel(
            lumi, port, find_shared_models, settings.shared_services.team_key, label=lumi.label
        )
    return 0


def _explain_own_server(address: ServerAddress, port: int) -> None:
    prefix = f"GAGNVIST_{address.kind.upper()}"
    print(
        f"Your {address.kind} server {address.model!r} (job {address.job}) answers at "
        f"http://127.0.0.1:{port}/v1 while the tunnel is open."
    )
    print("To use it, add these lines to .env (and remove them to go back to the shared one):")
    print()
    print(f"    {prefix}_MODEL={address.model}")
    print(f"    {prefix}_URL=http://127.0.0.1:{port}/v1")
    print(f"    {prefix}_KEY={address.key}")
    print()


def _download(args: argparse.Namespace, settings: Settings) -> int:
    lumi = _login(args, settings)
    name = args.name or args.repo.rsplit("/", 1)[-1]
    path = download_model(lumi, settings, args.repo, name)
    cmd = lumi.cluster.name
    print(f"The model is in {path} on {lumi.label}.")
    print(f"Serve it:  gagnvist {cmd} start chat {name}         (a chat model)")
    print(f"           gagnvist {cmd} start embeddings {name}   (an embedding model)")
    return 0


def _models(args: argparse.Namespace, settings: Settings) -> int:
    lumi = _login(args, settings)
    cmd = lumi.cluster.name
    stored = list_stored(lumi, settings)
    models = [s for s in stored if s.kind == "model"]
    runs = [s for s in stored if s.kind == "run"]
    if not models:
        print(f"You have no models of your own on {lumi.label} (gagnvist {cmd} download REPO).")
    else:
        print(f"{'MODEL':<40} {'SIZE':>6}  STATE")
        for model in models:
            state = "complete" if model.complete else "download not finished"
            print(f"{model.name[:40]:<40} {model.size:>6}  {state}")
    if runs:
        print()
        print(f"{'FINE-TUNING RUN':<40} {'SIZE':>6}  ADAPTER")
        for run in runs:
            state = "ready" if run.complete else f"not there yet (its job: gagnvist {cmd} jobs)"
            print(f"{run.name[:40]:<40} {run.size:>6}  {state}")
    print()
    print(f"Serve:   gagnvist {cmd} start chat MODEL  (or embeddings; --adapter RUN for a run)")
    print(f"Delete:  gagnvist {cmd} delete model MODEL   or   gagnvist {cmd} delete run RUN")
    return 0


def _delete(args: argparse.Namespace, settings: Settings) -> int:
    lumi = _login(args, settings)
    size = delete_stored(lumi, settings, args.kind, args.name)
    print(f"Deleted the {args.kind} {args.name} ({size}) from {lumi.label}.")
    return 0


def _start(args: argparse.Namespace, settings: Settings) -> int:
    lumi = _login(args, settings)
    request = ServerRequest(
        kind=args.kind,
        model=args.model,
        gpus=args.gpus,
        hours=args.hours,
        partition=args.partition,
        context=args.context,
        adapter=args.adapter or "",
    )
    job = start_server(lumi, settings, request)
    name = lumi.cluster.name
    print(f"Submitted job {job}: a {args.kind} server for {args.model}.")
    print("It may wait for a free GPU first, and then needs a few minutes to load the model.")
    print(f"Follow it:      gagnvist {name} jobs   (its log: gagnvist {name} log {job})")
    print(f"When it is READY:  gagnvist {name} connect --job {job}")
    _print_cost(lumi.cluster, args.gpus, args.hours, job)
    return 0


def _finetune(args: argparse.Namespace, settings: Settings) -> int:
    count = check_training_data(args.data)
    lumi = _login(args, settings)
    name = args.name or time.strftime("run-%Y%m%d-%H%M")
    request = FinetuneRequest(
        model=args.model,
        data=args.data,
        name=name,
        epochs=args.epochs,
        rank=args.rank,
        learning_rate=args.learning_rate,
        hours=args.hours,
        partition=args.partition,
    )
    job = start_finetune(lumi, settings, request)
    cluster = lumi.cluster.name
    print(f"Submitted job {job}: fine-tuning {args.model} on {count:,} conversations ({name}).")
    print(f"Follow it:  gagnvist {cluster} log {job}")
    print(f"When it has finished:  gagnvist {cluster} start chat {args.model} --adapter {name}")
    _print_cost(lumi.cluster, 1, args.hours, job)
    return 0


def check_training_data(path: Path) -> int:
    """Check a training file before it is uploaded; return its number of conversations."""
    if not path.is_file():
        raise LumiError(f"{path} not found")
    if path.stat().st_size > MAX_TRAINING_FILE:
        raise LumiError(f"{path} is larger than {MAX_TRAINING_FILE // 1_000_000} MB")
    count = 0
    try:
        # utf-8-sig: also accept the byte-order mark that Notepad and Excel may write.
        with path.open(encoding="utf-8-sig") as lines:
            for number, line in enumerate(lines, 1):
                if not line.strip():
                    continue
                problem = _conversation_problem(line)
                if problem:
                    raise LumiError(f"{path}, line {number}: {problem}")
                count += 1
    except UnicodeDecodeError:
        raise LumiError(f"{path} is not UTF-8 text: save it as UTF-8 and try again") from None
    if count == 0:
        raise LumiError(f"{path} holds no conversations")
    return count


def _conversation_problem(line: str) -> str:
    """What is wrong with one line of training data, or "" if nothing is."""
    try:
        conversation = json.loads(line)
    except json.JSONDecodeError as e:
        return f"not valid JSON ({e.msg})"
    messages = conversation.get("messages") if isinstance(conversation, dict) else None
    if not isinstance(messages, list) or not messages:
        return 'expected {"messages": [...]} with at least one message'
    for message in messages:
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            return "every message needs a role and a text content"
        if message.get("role") not in ("system", "user", "assistant"):
            return f"unknown role {message.get('role')!r} (use system, user or assistant)"
    if messages[-1]["role"] != "assistant":
        return "the last message must be the answer (role assistant)"
    return ""


def _jobs(args: argparse.Namespace, settings: Settings) -> int:
    lumi = _login(args, settings)
    jobs = list_jobs(lumi)
    if not jobs:
        print(f"You have no jobs on {lumi.label}.")
        return 0
    print(f"{'JOB':<10} {'NAME':<22} {'STATE':<11} {'NODE':<12} TIME LEFT")
    for job in jobs:
        state = "READY" if job.ready else job.state
        print(f"{job.id:<10} {job.name[:22]:<22} {state:<11} {job.node or '-':<12} {job.time_left}")
    print(
        "A server is READY once it has loaded its model: "
        f"gagnvist {lumi.cluster.name} connect --job JOB"
    )
    return 0


def _log(args: argparse.Namespace, settings: Settings) -> int:
    print(job_log(_login(args, settings), args.job, args.lines), end="")
    return 0


def _stop(args: argparse.Namespace, settings: Settings) -> int:
    stop_job(_login(args, settings), args.job)
    print(f"Stopped job {args.job}.")
    return 0


def _print_cost(cluster: Cluster, gpus: int, hours: int, job: str) -> None:
    print(cluster.cost(gpus, hours))
    print(f"Stop it as soon as you are done:  gagnvist {cluster.name} stop {job}")
