"""JURECA, the second supercomputer: the same commands and the same code as for LUMI,
with JURECA's own facts (gagnvist/clusters/jureca.py); run against the fake JURECA."""

import json
import os
import subprocess
from pathlib import Path

import pytest
from conftest import write_settings
from fake_lumi import (
    JURECA_CONTAINER,
    JURECA_PROJECT,
    PROJECT,
    TEAM_KEY,
    USER,
    FakeLumi,
    make_recording_ssh,
    needs_posix,
)
from test_lumi_scripts import JOB_ID, environment, stop_leftovers, wait_for

from gagnvist import cli
from gagnvist.cli import main
from gagnvist.clusters import JURECA, LUMI, cluster
from gagnvist.config import ConfigError, Settings, load_settings
from gagnvist.lumi.connection import Lumi, LumiError
from gagnvist.lumi.jobs import (
    FinetuneRequest,
    ServerRequest,
    _template_text,
    check_account,
    download_model,
    render_template,
    start_finetune,
    start_server,
)
from gagnvist.models.client import ModelClient, ModelError

MODELS = f"/p/project1/{JURECA_PROJECT}/{USER}/gagnvist/models"
JURECA_ENV = {
    "GAGNVIST_LUMI_USERNAME": "jon",
    "GAGNVIST_SSH_KEY": "keys/lumi",
    "GAGNVIST_JURECA_USERNAME": "jon1",
    "GAGNVIST_JURECA_SSH_KEY": "keys/jureca",
    "GAGNVIST_TEAM_KEY": TEAM_KEY,
}


def test_the_two_supercomputers_are_found_by_name() -> None:
    assert cluster("lumi") is LUMI and cluster("jureca") is JURECA
    assert (JURECA.name, JURECA.label) == ("jureca", "JURECA")
    with pytest.raises(ValueError, match="no supercomputer called 'mars'"):
        cluster("mars")


def test_jureca_has_its_own_section_and_personal_settings(tmp_path: Path) -> None:
    settings = load_settings(write_settings(tmp_path, JURECA_ENV))
    assert settings.cluster().name == "lumi"  # unless GAGNVIST_CLUSTER says otherwise
    jureca = settings.cluster("jureca")
    assert jureca.profile is JURECA
    assert jureca.host == "jureca.fz-juelich.de" and jureca.local_port == 8775
    assert jureca.username == "jon1" and jureca.ssh_key == tmp_path / "keys" / "jureca"
    assert settings.lumi.username == "jon" and settings.lumi.ssh_key == tmp_path / "keys" / "lumi"
    assert settings.lumi.gateway_user == settings.shared_services.gateway_user


def test_gagnvist_cluster_in_env_chooses_the_shared_models(tmp_path: Path) -> None:
    settings = load_settings(write_settings(tmp_path, {**JURECA_ENV, "GAGNVIST_CLUSTER": "jureca"}))
    assert settings.cluster().name == "jureca"
    assert settings.using_cluster("lumi").cluster().name == "lumi"
    with pytest.raises(ConfigError, match=r"GAGNVIST_CLUSTER .* 'mars'"):
        load_settings(write_settings(tmp_path, {"GAGNVIST_CLUSTER": "mars"}))


def test_without_a_jureca_section_the_commands_say_so(tmp_path: Path) -> None:
    path = write_settings(tmp_path, JURECA_ENV, changes={"[jureca]": "[not_jureca]"})
    settings = load_settings(path)
    assert settings.jureca is None
    with pytest.raises(ConfigError, match=r"no \[jureca\] section"):
        settings.cluster("jureca")
    with pytest.raises(ConfigError, match=r"no \[jureca\] section"):
        settings.using_cluster("jureca")


def test_the_model_client_uses_the_tunnel_to_the_chosen_supercomputer(tmp_path: Path) -> None:
    settings = load_settings(write_settings(tmp_path, JURECA_ENV))
    assert ModelClient.from_settings(settings).chat_endpoint.url == "http://127.0.0.1:8765/v1"
    client = ModelClient.from_settings(settings.using_cluster("jureca"))
    assert client.chat_endpoint.url == "http://127.0.0.1:8775/v1"
    assert client.embedding_endpoint.url == "http://127.0.0.1:8775/v1"
    assert client.chat_endpoint.key == TEAM_KEY  # the same team key on both


def test_require_access_names_jurecas_settings(tmp_path: Path) -> None:
    settings = load_settings(write_settings(tmp_path, {"GAGNVIST_LUMI_USERNAME": "jon"}))
    with pytest.raises(ConfigError, match=r"GAGNVIST_JURECA_USERNAME in \.env"):
        settings.require_access("jureca")
    settings = load_settings(write_settings(tmp_path, {"GAGNVIST_JURECA_USERNAME": "jon1"}))
    with pytest.raises(ConfigError, match=r"GAGNVIST_JURECA_SSH_KEY in \.env"):
        settings.require_access("jureca")


@needs_posix
def test_a_login_to_jureca_reuses_one_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recording_ssh = make_recording_ssh(tmp_path / "bin")
    monkeypatch.setenv("PATH", f"{recording_ssh}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_SSH_RECORD", str(tmp_path / "ssh-arguments.json"))
    for name in ("lumi", "jureca"):
        (tmp_path / "keys").mkdir(exist_ok=True)
        (tmp_path / "keys" / name).write_text("not a real key", encoding="utf-8")
    settings = load_settings(write_settings(tmp_path, JURECA_ENV))

    jureca = Lumi.from_settings(settings, "jureca")
    assert (jureca.username, jureca.host, jureca.cluster) == (
        "jon1",
        "jureca.fz-juelich.de",
        JURECA,
    )
    jureca.run("true")
    arguments = json.loads((tmp_path / "ssh-arguments.json").read_text(encoding="utf-8"))
    assert "ControlMaster=auto" in arguments and "ControlPersist=10h" in arguments
    assert arguments[arguments.index("ControlMaster=auto") + 2].startswith("ControlPath=")
    assert arguments[-2] == "jon1@jureca.fz-juelich.de"

    Lumi.from_settings(settings).run("true")  # LUMI: every connection logs in anew
    arguments = json.loads((tmp_path / "ssh-arguments.json").read_text(encoding="utf-8"))
    assert "ControlMaster=auto" not in arguments
    assert arguments[-2] == "jon@lumi.csc.fi"


@needs_posix
@pytest.mark.parametrize(
    ("error", "explanation"),
    [
        ("jon1@jureca.fz-juelich.de: Permission denied (keyboard-interactive).", "one-time code"),
        ("jon1@jureca.fz-juelich.de: Permission denied (publickey).", r"JuDoor .* from= clause"),
        ("Host key verification failed.", "JURECA's host key"),
    ],
)
def test_jurecas_ssh_failures_are_explained(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: str, explanation: str
) -> None:
    recording_ssh = make_recording_ssh(tmp_path / "bin")
    monkeypatch.setenv("PATH", f"{recording_ssh}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_SSH_RECORD", str(tmp_path / "ssh-arguments.json"))
    monkeypatch.setenv("FAKE_SSH_STATUS", "255")
    monkeypatch.setenv("FAKE_SSH_ERROR", error)
    jureca = Lumi("jon1", "jureca.fz-juelich.de", tmp_path / "key", JURECA)
    with pytest.raises(LumiError, match=explanation):
        jureca.run("true")


@needs_posix
def test_check_account_sees_the_project_folder_and_the_container_group(
    fake_jureca: FakeLumi,
) -> None:
    facts = check_account(fake_jureca.lumi, fake_jureca.settings)
    assert facts == {
        "user": USER,
        "groups": f"{USER} {JURECA_PROJECT} container",
        "partitions": "dc-gpu dc-gpu-devel dc-cpu",  # the budgets the member was given
        "scratch": "yes",  # the project folder, /p/project1/<project>
        "container": "yes",
        "gateway": "",
    }


@needs_posix
def test_check_from_the_command_line(
    fake_jureca: FakeLumi, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--config", str(fake_jureca.config), "jureca", "check"]) == 0
    printed = capsys.readouterr().out
    assert "Logging in to jureca.fz-juelich.de" in printed
    assert f"You are a member of the project {JURECA_PROJECT}." in printed
    assert "NOTE" not in printed  # the account may run containers
    assert "All set. Next: gagnvist jureca connect" in printed


@needs_posix
def test_check_tells_when_the_account_cannot_run_containers_yet(
    fake_jureca: FakeLumi, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("FAKE_GROUPS", JURECA_PROJECT)  # a member, but not of "container"
    assert main(["--config", str(fake_jureca.config), "jureca", "check"]) == 0
    printed = capsys.readouterr().out
    assert "NOTE: your account is not in the group 'container' yet" in printed
    assert "docs/jureca.md" in printed


@needs_posix
def test_check_tells_when_the_account_has_no_gpu_budget_yet(
    fake_jureca: FakeLumi, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("FAKE_PARTITIONS", "dc-cpu dc-cpu-devel")  # the CPU budget only
    assert main(["--config", str(fake_jureca.config), "jureca", "check"]) == 0
    printed = capsys.readouterr().out
    assert "NOTE: your account cannot use the GPU partitions of" in printed
    assert "(dc-gpu, dc-gpu-devel)" in printed and "JURECA-DC GPU" in printed
    assert "All set" in printed  # the shared models work regardless


@needs_posix
def test_a_job_slurm_refuses_for_the_partition_is_explained(
    fake_jureca: FakeLumi, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_jureca.add_model("qwen7")
    monkeypatch.setenv(
        "FAKE_SBATCH_REFUSES", "Invalid account or account/partition combination specified"
    )
    request = ServerRequest(kind="chat", model="qwen7", gpus=1, hours=1)
    with pytest.raises(LumiError, match=r"cannot use that partition.*JURECA-DC GPU.*in JuDoor"):
        start_server(fake_jureca.lumi, fake_jureca.settings, request)
    assert fake_jureca.jobs() == []
    monkeypatch.setenv("FAKE_SBATCH_REFUSES", "Requested time limit is invalid")
    with pytest.raises(LumiError, match=r"Slurm refused the job: sbatch: error: .*time limit"):
        start_server(fake_jureca.lumi, fake_jureca.settings, request)


@needs_posix
def test_a_model_is_downloaded_with_apptainer_on_the_login_node(fake_jureca: FakeLumi) -> None:
    path = download_model(fake_jureca.lumi, fake_jureca.settings, "BAAI/bge-m3", "bge-m3")
    assert path == f"{MODELS}/bge-m3"
    assert fake_jureca.mine("models", "bge-m3", ".download-complete").exists()
    assert fake_jureca.recorded("download-call.json")["runtime"] == ["apptainer", "exec"]


@needs_posix
def test_a_server_job_asks_for_a_jureca_node_and_runs_vllm_with_apptainer(
    fake_jureca: FakeLumi,
) -> None:
    fake_jureca.add_model("qwen7")
    request = ServerRequest(kind="chat", model="qwen7", gpus=2, hours=3)
    job = start_server(fake_jureca.lumi, fake_jureca.settings, request)
    script = fake_jureca.submitted(job)
    assert "#SBATCH --job-name=gagnvist-chat" in script
    assert f"#SBATCH --account={JURECA_PROJECT}" in script
    assert "#SBATCH --partition=dc-gpu" in script
    assert "#SBATCH --gres=gpu:2" in script
    assert "#SBATCH --cpus-per-task=16" in script
    assert "#SBATCH --time=3:00:00" in script
    assert f"srun apptainer exec --nv {JURECA_CONTAINER} vllm serve {MODELS}/qwen7" in script
    assert "--tensor-parallel-size 2" in script
    assert f"apptainer exec --nv {JURECA_CONTAINER} python" in script  # the gatekeeper
    assert "class Gatekeeper" in script
    for lumi_only in ("--gpus-per-node", "--mem-per-gpu", "MIOPEN", "Local-LAIF", "singularity"):
        assert lumi_only not in script, lumi_only
    assert {job["id"]: job["state"] for job in fake_jureca.jobs()} == {job: "PENDING"}


@needs_posix
@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"hours": 7}, "1 to 6 hours on dc-gpu"),
        ({"partition": "dc-gpu-devel", "hours": 3}, "1 to 2 hours on dc-gpu-devel"),
        ({"partition": "small-g"}, "partition dc-gpu or dc-gpu-devel"),
        ({"gpus": 3}, "1, 2, 4 GPU"),
        ({"model": f"/scratch/{PROJECT}/teammate/gagnvist/models/m"}, "not a valid path"),
        ({"model": "/p/project1/../etc/m"}, "not a valid path"),
    ],
)
def test_jurecas_own_limits_are_enforced(
    fake_jureca: FakeLumi, changes: dict[str, object], message: str
) -> None:
    request = ServerRequest(**{"kind": "chat", "model": "qwen7", **changes})  # type: ignore[arg-type]
    with pytest.raises(LumiError, match=message):
        start_server(fake_jureca.lumi, fake_jureca.settings, request)
    assert fake_jureca.jobs() == []


@needs_posix
def test_two_jobs_at_a_time_on_jureca(fake_jureca: FakeLumi) -> None:
    """A chat model and an embedding model, as on LUMI; each is a whole node there."""
    fake_jureca.add_model("qwen7")
    fake_jureca.add_job("100", "gagnvist-embeddings")
    job = start_server(fake_jureca.lumi, fake_jureca.settings, ServerRequest("chat", "qwen7"))
    assert job.isdigit()
    with pytest.raises(LumiError, match=r"already have 2 gagnvist jobs \(the limit is 2\)"):
        start_server(fake_jureca.lumi, fake_jureca.settings, ServerRequest("chat", "qwen7"))


@needs_posix
def test_a_teammates_model_on_jureca_is_named_by_its_full_path(fake_jureca: FakeLumi) -> None:
    folder = fake_jureca.project_folder / "teammate" / "gagnvist" / "models" / "m"
    folder.mkdir(parents=True)
    (folder / "config.json").write_text("{}", encoding="utf-8")
    full_path = f"/p/project1/{JURECA_PROJECT}/teammate/gagnvist/models/m"
    job = start_server(fake_jureca.lumi, fake_jureca.settings, ServerRequest("chat", full_path))
    assert f"vllm serve {full_path}" in fake_jureca.submitted(job)


@needs_posix
def test_finetuning_on_jureca_uses_one_gpu_of_a_node(fake_jureca: FakeLumi, tmp_path: Path) -> None:
    fake_jureca.add_model("qwen7")
    data = tmp_path / "train.jsonl"
    data.write_text(
        '{"messages": [{"role": "user", "content": "Q"}, {"role": "assistant", "content": "A"}]}\n',
        encoding="utf-8",
    )
    request = FinetuneRequest(model="qwen7", data=data, name="run-1", hours=2)
    job = start_finetune(fake_jureca.lumi, fake_jureca.settings, request)
    script = fake_jureca.submitted(job)
    assert "#SBATCH --gres=gpu:1" in script and "#SBATCH --partition=dc-gpu" in script
    assert "#SBATCH --cpus-per-task=8" in script
    assert f"srun apptainer exec --nv {JURECA_CONTAINER} python" in script
    assert (fake_jureca.mine("finetune", "run-1", "train.jsonl")).exists()


@needs_posix
def test_the_commands_say_the_cost_in_core_hours_and_name_the_jureca_commands(
    fake_jureca: FakeLumi, capsys: pytest.CaptureFixture[str]
) -> None:
    config = str(fake_jureca.config)
    fake_jureca.add_model("qwen7")
    assert main(["--config", config, "jureca", "start", "chat", "qwen7", "--hours", "2"]) == 0
    printed = capsys.readouterr().out
    job = printed.split("Submitted job ", 1)[1].split(":", 1)[0]
    assert (
        "at most 256 core-hours" in printed and "a whole node, 128 core-hours per hour" in printed
    )
    assert f"gagnvist jureca connect --job {job}" in printed
    assert f"gagnvist jureca stop {job}" in printed

    assert main(["--config", config, "jureca", "jobs"]) == 0
    listed = capsys.readouterr().out
    assert job in listed and "gagnvist-chat" in listed and "gagnvist jureca connect" in listed

    assert main(["--config", config, "jureca", "stop", job]) == 0
    assert fake_jureca.jobs() == []


def test_the_hours_a_command_offers_fit_the_supercomputer(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        main(["jureca", "start", "--help"])
    printed = capsys.readouterr().out
    assert "at most 6" in printed and "dc-gpu-devel" in printed
    with pytest.raises(SystemExit):
        main(["lumi", "start", "--help"])
    printed = capsys.readouterr().out
    assert "at most 12" in printed and "dev-g" in printed


def _jureca_serve_script(model_path: str) -> str:
    return render_template(
        "serve.sbatch",
        JURECA,
        job_name="gagnvist-chat",
        kind="chat",
        project=JURECA_PROJECT,
        partition="dc-gpu",
        gpus="1",
        cpus="8",
        hours="1",
        container=JURECA_CONTAINER,
        model_path=model_path,
        served_name="qwen7",
        request_name="qwen7",
        extra_arguments="--max-model-len 8192 --gpu-memory-utilization 0.9",
        key_proxy=_template_text("key_proxy.py"),
    )


@needs_posix
def test_the_job_scripts_render_for_jureca_and_are_valid_bash() -> None:
    serve = _jureca_serve_script("/m").replace("--gres=gpu:1", "--gres=gpu:1")
    finetune = render_template(
        "finetune.sbatch",
        JURECA,
        project=JURECA_PROJECT,
        partition="dc-gpu",
        cpus="8",
        hours="2",
        container=JURECA_CONTAINER,
        model_path="/m",
        run_folder="/r",
        run_name="r",
        epochs="1",
        rank="16",
        learning_rate="0.0002",
        finetune_script="print('training')",
    )
    for script in (serve, finetune):
        assert "{{" not in script and "module purge" in script
        assert "Local-LAIF" not in script and "MIOPEN" not in script
        subprocess.run(["bash", "-n"], input=script.encode(), check=True)
    assert "#SBATCH --gres=gpu:1" in serve and "#SBATCH --gres=gpu:1" in finetune


@needs_posix
def test_a_jureca_server_script_runs_vllm_and_the_gatekeeper_with_apptainer(
    tmp_path: Path, fake_programs: Path
) -> None:
    script = tmp_path / "serve.sbatch"
    script.write_text(_jureca_serve_script(str(tmp_path / "model")), encoding="utf-8")
    process = subprocess.Popen(
        ["bash", str(script)],
        env=environment(tmp_path, fake_programs),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    address_file = tmp_path / "home" / ".gagnvist" / "jobs" / f"{JOB_ID}.json"
    try:
        wait_for(address_file, process)
        address = json.loads(address_file.read_text(encoding="utf-8"))
        assert address["model"] == "qwen7" and 20000 <= int(address["port"]) < 40000
        root = tmp_path / "lumi"
        vllm = json.loads((root / "vllm-call.json").read_text(encoding="utf-8"))
        assert vllm["runtime"] == ["apptainer", "exec", "--nv"]
        gatekeeper = json.loads((root / "gatekeeper-call.json").read_text(encoding="utf-8"))
        assert gatekeeper["runtime"] == ["apptainer", "exec", "--nv"]
    finally:
        if process.poll() is None:
            process.kill()
        stop_leftovers(tmp_path / "lumi")


def test_cluster_option_sends_a_command_to_the_other_supercomputers_models(
    fake_lumi_settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ports: list[int] = []

    def remember_port(settings: Settings) -> ModelClient:
        ports.append(settings.cluster().local_port)
        raise ModelError("stopped here")  # no request is sent

    monkeypatch.setattr(cli.ModelClient, "from_settings", remember_port)
    config = str(tmp_path / "gagnvist.toml")
    assert main(["--config", config, "try-models", "--cluster", "jureca"]) == 1
    assert main(["--config", config, "try-models"]) == 1
    assert main(["--config", config, "try-models", "--cluster", "lumi"]) == 1
    assert ports == [8775, 8765, 8765]
