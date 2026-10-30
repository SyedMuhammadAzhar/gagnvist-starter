"""Models, servers and fine-tuning jobs on LUMI, run against the fake LUMI."""

import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest
from fake_lumi import CONTAINER, ORGANIZER, PROJECT, USER, FakeLumi, needs_posix

from gagnvist.lumi import jobs
from gagnvist.lumi.connection import LumiError
from gagnvist.lumi.jobs import (
    MAX_JOBS,
    FinetuneRequest,
    ServerRequest,
    Stored,
    _checked,
    _tar,
    check_account,
    delete_stored,
    download_model,
    find_gateway,
    job_log,
    list_jobs,
    list_stored,
    organizer_stop_folder,
    render_template,
    server_address,
    start_finetune,
    start_server,
    stop_job,
)

pytestmark = needs_posix

LOG_OPTION = "--output=" + "{home}/.gagnvist/logs/%x-%j.log"
STOP_FOLDER = f"/scratch/{PROJECT}/{ORGANIZER}/gagnvist/stop"


def test_check_account_reports_project_container_and_gateway(fake_lumi: FakeLumi) -> None:
    fake_lumi.add_job("900", "gagnvist-gateway", node="nid007001", user=ORGANIZER)
    facts = check_account(fake_lumi.lumi, fake_lumi.settings)
    assert facts == {
        "user": USER,
        "groups": f"{USER} {PROJECT}",
        "scratch": "yes",
        "container": "yes",
        "gateway": "nid007001",
    }


def test_the_gateway_is_found_by_its_owner_and_name(fake_lumi: FakeLumi) -> None:
    fake_lumi.add_job("901", "gagnvist-gateway", node="nid006666", user="someone-else")
    fake_lumi.add_job("902", "gagnvist-gateway", state="PENDING", user=ORGANIZER)
    with pytest.raises(LumiError, match="not running right now"):
        find_gateway(fake_lumi.lumi, fake_lumi.settings)
    fake_lumi.add_job("903", "gagnvist-gateway", node="nid007001", user=ORGANIZER)
    assert find_gateway(fake_lumi.lumi, fake_lumi.settings) == "nid007001"


def test_a_model_is_downloaded_once(fake_lumi: FakeLumi, capfd: pytest.CaptureFixture[str]) -> None:
    path = download_model(fake_lumi.lumi, fake_lumi.settings, "Qwen/Qwen2.5-7B-Instruct", "qwen7")
    assert path == f"/scratch/{PROJECT}/{USER}/gagnvist/models/qwen7"
    config = json.loads(
        fake_lumi.mine("models", "qwen7", "config.json").read_text(encoding="utf-8")
    )
    assert config == {"downloaded": "Qwen/Qwen2.5-7B-Instruct", "ignored": True}
    assert fake_lumi.mine("models", "qwen7", ".download-complete").exists()
    download_model(fake_lumi.lumi, fake_lumi.settings, "Qwen/Qwen2.5-7B-Instruct", "qwen7")
    assert "Already downloaded" in capfd.readouterr().out


def test_an_interrupted_download_is_continued(
    fake_lumi: FakeLumi, capfd: pytest.CaptureFixture[str]
) -> None:
    fake_lumi.add_model("qwen7", complete=False)
    download_model(fake_lumi.lumi, fake_lumi.settings, "Qwen/Qwen2.5-7B-Instruct", "qwen7")
    printed = capfd.readouterr().out
    assert "Already downloaded" not in printed and "Downloaded" in printed
    assert fake_lumi.mine("models", "qwen7", ".download-complete").exists()


def test_the_older_weight_format_is_left_out_when_the_newer_one_is_there(tmp_path: Path) -> None:
    """The download script, run with a stand-in for huggingface_hub that lists whatever
    files FAKE_REPO_FILES names and writes down what it is asked to download."""
    stub = tmp_path / "stub" / "huggingface_hub"
    stub.mkdir(parents=True)
    (stub / "__init__.py").write_text(
        "import json, os\n"
        "def list_repo_files(repo_id):\n"
        "    return os.environ['FAKE_REPO_FILES'].split()\n"
        "def snapshot_download(**kwargs):\n"
        "    with open(os.environ['FAKE_DOWNLOAD_RECORD'], 'w') as f:\n"
        "        json.dump(kwargs, f)\n",
        encoding="utf-8",
    )
    record = tmp_path / "record.json"

    def skipped(*files: str) -> list[str]:
        env = {
            **os.environ,
            "PYTHONPATH": str(stub.parent),
            "FAKE_REPO_FILES": " ".join(files),
            "FAKE_DOWNLOAD_RECORD": str(record),
        }
        subprocess.run(
            [sys.executable, "-c", jobs._DOWNLOAD, "org/model", str(tmp_path / "m")],
            env=env,
            check=True,
        )
        asked = json.loads(record.read_text(encoding="utf-8"))
        assert (asked["repo_id"], asked["local_dir"]) == ("org/model", str(tmp_path / "m"))
        patterns: list[str] = asked["ignore_patterns"]
        return patterns

    both = skipped("config.json", "model.safetensors", "pytorch_model.bin", "onnx/model.onnx")
    assert "*.bin" in both and "*.pt" in both and "onnx/*" in both
    older_only = skipped("config.json", "pytorch_model.bin", "onnx/model.onnx")
    assert "*.bin" not in older_only and "*.pt" not in older_only and "onnx/*" in older_only
    assert skipped("config.json", "sub/model.safetensors", "pytorch_model.bin") == older_only


def test_your_folders_are_made_writable_by_you_only(fake_lumi: FakeLumi) -> None:
    base = fake_lumi.mine()
    base.mkdir(parents=True)
    base.chmod(0o775)  # group-writable, as LUMI's default permissions make new folders
    download_model(fake_lumi.lumi, fake_lumi.settings, "Qwen/Qwen2.5-7B-Instruct", "qwen7")
    for folder in (base.parent, base, fake_lumi.mine("models"), fake_lumi.mine("models", "qwen7")):
        assert folder.stat().st_mode & 0o022 == 0, folder
    assert fake_lumi.mine("models", "qwen7", "config.json").stat().st_mode & 0o022 == 0


def test_a_folder_that_is_not_yours_is_refused(
    fake_lumi: FakeLumi, tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    elsewhere = tmp_path / "someone-elses-folder"
    elsewhere.mkdir()
    fake_lumi.mine().parent.mkdir(parents=True)
    fake_lumi.mine().symlink_to(elsewhere)  # gagnvist/ is a link, which someone could change
    with pytest.raises(LumiError, match="see the messages above"):
        download_model(fake_lumi.lumi, fake_lumi.settings, "Qwen/Qwen2.5-7B-Instruct", "qwen7")
    assert "is not a folder of yours" in capfd.readouterr().err
    assert list(elsewhere.iterdir()) == []

    teammate = fake_lumi.root / "scratch" / PROJECT / "teammate" / "gagnvist" / "models" / "m"
    teammate.mkdir(parents=True)
    (teammate / "config.json").write_text("{}", encoding="utf-8")
    request = FinetuneRequest(
        model=f"/scratch/{PROJECT}/teammate/gagnvist/models/m", data=_data(tmp_path), name="r"
    )
    with pytest.raises(LumiError, match="is not a folder of yours"):
        start_finetune(fake_lumi.lumi, fake_lumi.settings, request)
    assert fake_lumi.jobs() == [] and list(elsewhere.iterdir()) == []


def test_a_chat_server_job_is_submitted_with_the_right_resources(fake_lumi: FakeLumi) -> None:
    fake_lumi.add_model("qwen7")
    request = ServerRequest(kind="chat", model="qwen7", gpus=2, hours=6)
    job = start_server(fake_lumi.lumi, fake_lumi.settings, request)
    script = fake_lumi.submitted(job)
    assert "#SBATCH --job-name=gagnvist-chat" in script
    assert f"#SBATCH --account={PROJECT}" in script
    assert "#SBATCH --gpus-per-node=2" in script
    assert "#SBATCH --cpus-per-task=14" in script
    assert "#SBATCH --time=6:00:00" in script
    assert f"vllm serve /scratch/{PROJECT}/{USER}/gagnvist/models/qwen7" in script
    assert "--tensor-parallel-size 2" in script
    assert "--max-model-len 8192" in script
    assert f"singularity run {CONTAINER} vllm serve" in script
    assert "class Gatekeeper" in script  # the gatekeeper travels inside the job script
    assert "--api-key" not in script
    assert f'stop_file="{STOP_FOLDER}/$SLURM_JOB_ID"' in script  # the organizers' way to end it
    home = str(fake_lumi.home)
    assert fake_lumi.sbatch_options(job) == ["--parsable", LOG_OPTION.format(home=home)]
    assert {job["id"]: job["state"] for job in fake_lumi.jobs()} == {job: "PENDING"}


def test_an_embedding_server_runs_vllm_as_a_pooling_model(fake_lumi: FakeLumi) -> None:
    fake_lumi.add_model("bge-m3")
    job = start_server(fake_lumi.lumi, fake_lumi.settings, ServerRequest("embeddings", "bge-m3"))
    script = fake_lumi.submitted(job)
    assert "#SBATCH --job-name=gagnvist-embeddings" in script
    assert "--runner pooling" in script
    assert "--max-model-len" not in script


def test_an_adapter_is_served_under_its_own_name(fake_lumi: FakeLumi) -> None:
    fake_lumi.add_model("qwen7")
    adapter = fake_lumi.mine("finetune", "my-run", "adapter")
    adapter.mkdir(parents=True)
    (adapter / "adapter_config.json").write_text("{}", encoding="utf-8")
    request = ServerRequest("chat", "qwen7", adapter="my-run")
    script = fake_lumi.submitted(start_server(fake_lumi.lumi, fake_lumi.settings, request))
    lora = f"--lora-modules my-run=/scratch/{PROJECT}/{USER}/gagnvist/finetune/my-run/adapter"
    assert lora in script
    assert "--served-model-name qwen7" in script
    assert '"{{request_name}}"' not in script and '"my-run"' in script


def test_a_missing_model_is_reported_before_anything_is_submitted(fake_lumi: FakeLumi) -> None:
    with pytest.raises(LumiError, match="was not found on LUMI"):
        start_server(fake_lumi.lumi, fake_lumi.settings, ServerRequest("chat", "nothing"))
    assert fake_lumi.jobs() == []


def test_a_half_downloaded_model_is_refused(fake_lumi: FakeLumi) -> None:
    fake_lumi.add_model("qwen7", complete=False)
    with pytest.raises(LumiError, match="did not finish"):
        start_server(fake_lumi.lumi, fake_lumi.settings, ServerRequest("chat", "qwen7"))
    assert fake_lumi.jobs() == []


def test_no_more_than_the_allowed_number_of_jobs(fake_lumi: FakeLumi) -> None:
    fake_lumi.add_model("qwen7")
    for number in range(MAX_JOBS):
        fake_lumi.add_job(str(100 + number), "gagnvist-chat")
    fake_lumi.add_job("200", "other-work")  # jobs that are not gagnvist's do not count
    with pytest.raises(LumiError, match=f"already have {MAX_JOBS} gagnvist jobs"):
        start_server(fake_lumi.lumi, fake_lumi.settings, ServerRequest("chat", "qwen7"))


def test_a_job_that_is_ending_no_longer_counts(fake_lumi: FakeLumi) -> None:
    fake_lumi.add_model("qwen7")
    for number in range(MAX_JOBS - 1):
        fake_lumi.add_job(str(100 + number), "gagnvist-chat")
    fake_lumi.add_job("150", "gagnvist-embeddings", state="COMPLETING")  # just stopped
    job = start_server(fake_lumi.lumi, fake_lumi.settings, ServerRequest("chat", "qwen7"))
    assert job in {j["id"] for j in fake_lumi.jobs()}
    fake_lumi.add_job("160", "gagnvist-finetune", state="PENDING")  # waiting ones do count
    with pytest.raises(LumiError, match="already have"):
        start_server(fake_lumi.lumi, fake_lumi.settings, ServerRequest("chat", "qwen7"))


def test_models_and_runs_are_listed_with_their_sizes(fake_lumi: FakeLumi) -> None:
    assert list_stored(fake_lumi.lumi, fake_lumi.settings) == []
    fake_lumi.add_model("qwen7")
    fake_lumi.add_model("half", complete=False)
    adapter = fake_lumi.mine("finetune", "run-1", "adapter")
    adapter.mkdir(parents=True)
    (adapter / "adapter_config.json").write_text("{}", encoding="utf-8")
    fake_lumi.mine("finetune", "run-2").mkdir()
    stored = list_stored(fake_lumi.lumi, fake_lumi.settings)
    assert [(s.kind, s.name, s.complete) for s in stored] == [
        ("model", "half", False),
        ("model", "qwen7", True),
        ("run", "run-1", True),
        ("run", "run-2", False),
    ]
    assert all(isinstance(s, Stored) and s.size and " " not in s.size for s in stored)


def test_a_model_or_run_of_yours_can_be_deleted(fake_lumi: FakeLumi) -> None:
    fake_lumi.add_model("qwen7")
    run = fake_lumi.mine("finetune", "run-1")
    run.mkdir(parents=True)
    (run / "train.jsonl").write_text("{}\n", encoding="utf-8")
    assert delete_stored(fake_lumi.lumi, fake_lumi.settings, "model", "qwen7")
    assert not fake_lumi.mine("models", "qwen7").exists()
    assert delete_stored(fake_lumi.lumi, fake_lumi.settings, "run", "run-1")
    assert not run.exists()
    with pytest.raises(LumiError, match="no model 'qwen7'"):
        delete_stored(fake_lumi.lumi, fake_lumi.settings, "model", "qwen7")
    with pytest.raises(LumiError, match="not a valid name"):
        delete_stored(fake_lumi.lumi, fake_lumi.settings, "model", "../../elsewhere")
    with pytest.raises(LumiError, match="not 'folder'"):
        delete_stored(fake_lumi.lumi, fake_lumi.settings, "folder", "qwen7")


def test_a_model_a_running_server_serves_is_not_deleted(fake_lumi: FakeLumi) -> None:
    fake_lumi.add_model("qwen7")
    fake_lumi.add_job("501", "gagnvist-chat")
    fake_lumi.write_address("501", kind="chat", model="qwen7", node="nid005001", port=1, key="k")
    with pytest.raises(LumiError, match="job 501 serves 'qwen7'"):
        delete_stored(fake_lumi.lumi, fake_lumi.settings, "model", "qwen7")
    assert fake_lumi.mine("models", "qwen7", "config.json").exists()
    stop_job(fake_lumi.lumi, "501")
    fake_lumi.write_address("502", kind="chat", model="qwen7", node="nid005001", port=1, key="k")
    assert delete_stored(fake_lumi.lumi, fake_lumi.settings, "model", "qwen7")  # 502 has ended
    assert not fake_lumi.mine("models", "qwen7").exists()


def test_a_folder_that_is_not_yours_is_not_deleted(fake_lumi: FakeLumi, tmp_path: Path) -> None:
    elsewhere = tmp_path / "someone-elses-folder"
    elsewhere.mkdir()
    (elsewhere / "config.json").write_text("{}", encoding="utf-8")
    fake_lumi.mine("models").mkdir(parents=True)
    fake_lumi.mine("models", "linked").symlink_to(elsewhere)
    with pytest.raises(LumiError, match="not a folder of yours"):
        delete_stored(fake_lumi.lumi, fake_lumi.settings, "model", "linked")
    assert (elsewhere / "config.json").exists()


def test_the_organizers_stop_folder_is_in_their_part_of_the_project(fake_lumi: FakeLumi) -> None:
    assert organizer_stop_folder(fake_lumi.settings) == STOP_FOLDER


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"gpus": 3}, "1, 2, 4 GPU chips"),
        ({"gpus": 8}, "1, 2, 4 GPU chips"),
        ({"hours": 13}, "1 to 12 hours"),
        ({"partition": "dev-g", "hours": 4}, "1 to 3 hours on dev-g"),
        ({"partition": "standard-g"}, "partition"),
        ({"context": 100}, "context of 512"),
        ({"model": "../other"}, "not a valid name"),
        ({"model": "/home/someone/model"}, "not a valid path"),
        ({"model": "qwen7; rm -rf ~"}, "not a valid name"),
    ],
)
def test_requests_outside_the_rules_are_refused_without_running_anything(
    fake_lumi: FakeLumi, changes: dict[str, object], message: str
) -> None:
    request = ServerRequest(**{"kind": "chat", "model": "qwen7", **changes})  # type: ignore[arg-type]
    with pytest.raises(LumiError, match=message):
        start_server(fake_lumi.lumi, fake_lumi.settings, request)
    assert fake_lumi.jobs() == []


def test_a_teammates_model_can_be_named_by_its_full_path(fake_lumi: FakeLumi) -> None:
    folder = fake_lumi.root / "scratch" / PROJECT / "teammate" / "gagnvist" / "models" / "m"
    folder.mkdir(parents=True)
    (folder / "config.json").write_text("{}", encoding="utf-8")
    full_path = f"/scratch/{PROJECT}/teammate/gagnvist/models/m"
    job = start_server(fake_lumi.lumi, fake_lumi.settings, ServerRequest("chat", full_path))
    assert f"vllm serve {full_path}" in fake_lumi.submitted(job)


def test_jobs_are_listed_and_ready_servers_marked(fake_lumi: FakeLumi) -> None:
    fake_lumi.add_job("301", "gagnvist-chat", node="nid005001")
    fake_lumi.add_job("302", "gagnvist-embeddings", state="PENDING", node="n/a")
    fake_lumi.add_job("303", "gagnvist-chat", user="someone-else")
    fake_lumi.write_address("301", kind="chat", model="qwen7", node="nid005001", port=1, key="k")
    jobs = {job.id: job for job in list_jobs(fake_lumi.lumi)}
    assert set(jobs) == {"301", "302"}
    assert jobs["301"].ready and jobs["301"].node == "nid005001"
    assert not jobs["302"].ready and jobs["302"].node == ""


def test_no_jobs_is_not_an_error(fake_lumi: FakeLumi) -> None:
    assert list_jobs(fake_lumi.lumi) == []


def test_a_busy_slurm_is_reported_not_taken_for_no_jobs(
    fake_lumi: FakeLumi, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_SLURM_DOWN", "1")
    with pytest.raises(LumiError, match="did not answer"):
        list_jobs(fake_lumi.lumi)
    with pytest.raises(LumiError, match="did not answer"):
        server_address(fake_lumi.lumi, "401")
    with pytest.raises(LumiError, match="did not answer"):
        check_account(fake_lumi.lumi, fake_lumi.settings)


def test_a_ready_server_tells_where_it_answers(fake_lumi: FakeLumi) -> None:
    fake_lumi.add_job("401", "gagnvist-chat")
    fake_lumi.write_address(
        "401", kind="chat", model="qwen7", node="nid005002", port=23456, key="s3cret"
    )
    address = server_address(fake_lumi.lumi, "401")
    assert (address.model, address.node, address.port, address.key) == (
        "qwen7",
        "nid005002",
        23456,
        "s3cret",
    )


@pytest.mark.parametrize(
    ("state", "with_address", "message"),
    [
        ("PENDING", False, "waiting for a GPU"),
        ("RUNNING", False, "still loading its model"),
        (None, False, "not one of your running jobs"),
        (None, True, "not one of your running jobs"),  # an address left behind by an old job
    ],
)
def test_a_server_that_is_not_ready_is_explained(
    fake_lumi: FakeLumi, state: str | None, with_address: bool, message: str
) -> None:
    if state:
        fake_lumi.add_job("402", "gagnvist-chat", state=state)
    if with_address:
        fake_lumi.write_address("402", kind="chat", model="m", node="nid005003", port=2000, key="k")
    with pytest.raises(LumiError, match=message):
        server_address(fake_lumi.lumi, "402")


def test_you_can_stop_your_own_job_but_not_anybody_elses(fake_lumi: FakeLumi) -> None:
    fake_lumi.add_job("501", "gagnvist-chat")
    fake_lumi.write_address("501", kind="chat", model="m", node="nid005004", port=2000, key="k")
    fake_lumi.add_job("900", "gagnvist-gateway", user=ORGANIZER)
    stop_job(fake_lumi.lumi, "501")
    assert [job["id"] for job in fake_lumi.jobs()] == ["900"]
    assert not (fake_lumi.home / ".gagnvist" / "jobs" / "501.json").exists()
    with pytest.raises(LumiError, match="permission denied"):
        stop_job(fake_lumi.lumi, "900")
    assert [job["id"] for job in fake_lumi.jobs()] == ["900"]


def test_the_end_of_a_log_is_shown(fake_lumi: FakeLumi) -> None:
    logs = fake_lumi.home / ".gagnvist" / "logs"
    logs.mkdir(parents=True)
    (logs / "gagnvist-chat-601.log").write_text(
        "".join(f"line {n}\n" for n in range(100)), encoding="utf-8"
    )
    assert job_log(fake_lumi.lumi, "601", lines=3) == "line 97\nline 98\nline 99\n"
    with pytest.raises(LumiError, match="no log for job 602"):
        job_log(fake_lumi.lumi, "602")


def _data(tmp_path: Path) -> Path:
    data = tmp_path / "train.jsonl"
    data.write_text(
        '{"messages": [{"role": "user", "content": "Q"}, {"role": "assistant", "content": "A"}]}\n',
        encoding="utf-8",
    )
    return data


def test_finetuning_uploads_the_data_and_carries_the_script_in_the_job(
    fake_lumi: FakeLumi, tmp_path: Path
) -> None:
    fake_lumi.add_model("qwen7")
    data = _data(tmp_path)
    request = FinetuneRequest(model="qwen7", data=data, name="run-1", epochs=2, rank=32)
    job = start_finetune(fake_lumi.lumi, fake_lumi.settings, request)
    run = fake_lumi.mine("finetune", "run-1")
    assert sorted(p.name for p in run.iterdir()) == ["train.jsonl"]  # nothing to run lies here
    assert (run / "train.jsonl").read_text(encoding="utf-8") == data.read_text(encoding="utf-8")
    script = fake_lumi.submitted(job)
    assert "#SBATCH --job-name=gagnvist-finetune" in script
    assert "--epochs 2 --rank 32 --learning-rate 0.0002" in script
    assert '"""Fine-tune a chat model with LoRA' in script
    assert f'stop_file="{STOP_FOLDER}/$SLURM_JOB_ID"' in script
    assert not list((fake_lumi.home / ".gagnvist").glob("upload.*"))  # the upload is cleaned up
    with pytest.raises(LumiError, match="already exists"):
        start_finetune(fake_lumi.lumi, fake_lumi.settings, request)


def test_every_template_renders_completely_and_is_valid_bash() -> None:
    values = {
        "serve.sbatch": dict(
            job_name="gagnvist-chat", kind="chat", project=PROJECT, partition="small-g",
            gpus="1", cpus="7", hours="4", container=CONTAINER, model_path="/m",
            served_name="m", request_name="m", extra_arguments="--max-model-len 8192",
            stop_folder=STOP_FOLDER, key_proxy="print('gatekeeper')",
        ),
        "finetune.sbatch": dict(
            project=PROJECT, partition="small-g", cpus="7", hours="2", container=CONTAINER,
            model_path="/m", run_folder="/r", run_name="r", epochs="1", rank="16",
            learning_rate="0.0002", stop_folder=STOP_FOLDER,
            finetune_script="print('training')",
        ),
    }  # fmt: skip
    for name, given in values.items():
        script = render_template(name, **given)
        assert "{{" not in script
        subprocess.run(["bash", "-n"], input=script.encode(), check=True)
    with pytest.raises(ValueError, match="no value given"):
        render_template("finetune.sbatch", project=PROJECT)


@pytest.mark.parametrize("name", ["key_proxy.py", "finetune_lora.py"])
def test_scripts_carried_in_job_scripts_cannot_end_the_heredoc_early(name: str) -> None:
    text = (Path(__file__).parents[1] / "src/gagnvist/lumi/job_templates" / name).read_text(
        encoding="utf-8"
    )
    assert "GAGNVIST_END_OF_SCRIPT" not in text
    assert "{{" not in text


def test_a_finetune_upload_is_a_plain_archive(tmp_path: Path) -> None:
    archive = tmp_path / "upload.tar"
    archive.write_bytes(_tar({"a.txt": b"one", "b.txt": b"two"}))
    with tarfile.open(archive) as opened:
        assert sorted(opened.getnames()) == ["a.txt", "b.txt"]


def test_the_example_settings_pass_the_checks_used_in_job_scripts() -> None:
    text = (Path(__file__).parents[1] / "gagnvist.toml").read_text(encoding="utf-8")
    container = text.split('container = "', 1)[1].split('"', 1)[0]
    assert _checked("container", container) == container
    assert _checked("name", "gagnvist-gateway") == "gagnvist-gateway"
    assert os.path.basename(container).startswith("lumi-multitorch-full-")


def test_a_template_saved_by_notepad_still_starts_with_its_shebang(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "job_templates").mkdir()
    (tmp_path / "job_templates" / "serve.sbatch").write_bytes(
        b"\xef\xbb\xbf#!/bin/bash -l\r\n# \xc3\x8dsland\r\necho ok\r\n"
    )
    monkeypatch.setattr(jobs.resources, "files", lambda package: tmp_path)
    text = jobs._template_text("serve.sbatch")
    assert text.startswith("#!/bin/bash -l\n")
    assert "\r" not in text
