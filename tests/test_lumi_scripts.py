"""The job scripts that run on LUMI, run here with bash, the fake programs and the real
gatekeeper (key_proxy.py)."""

import contextlib
import json
import os
import signal
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fake_lumi import CONTAINER, PROJECT, needs_posix

from gagnvist.lumi.jobs import _template_text, render_template

pytestmark = needs_posix

JOB_ID = "4242"


def environment(tmp_path: Path, fake_programs: Path) -> dict[str, str]:
    root = tmp_path / "lumi"
    root.mkdir(exist_ok=True)
    return {
        **os.environ,
        "PATH": f"{fake_programs}{os.pathsep}{os.environ['PATH']}",
        "HOME": str(tmp_path / "home"),
        "USER": "testuser",
        "SLURM_JOB_ID": JOB_ID,
        "FAKE_ROOT": str(root),
    }


def serve_script(tmp_path: Path, name: str) -> Path:
    script = tmp_path / "serve.sbatch"
    script.write_text(
        render_template(
            "serve.sbatch",
            job_name="gagnvist-chat",
            kind="chat",
            project=PROJECT,
            partition="small-g",
            gpus="1",
            cpus="7",
            hours="1",
            container=CONTAINER,
            model_path=str(tmp_path / "model"),
            served_name=name,
            request_name=name,
            extra_arguments="--max-model-len 8192 --gpu-memory-utilization 0.9",
            key_proxy=_template_text("key_proxy.py"),
        ),
        encoding="utf-8",
    )
    return script


def wait_for(path: Path, process: subprocess.Popen[bytes], seconds: float = 60) -> None:
    deadline = time.monotonic() + seconds
    while not path.exists():
        if process.poll() is not None or time.monotonic() > deadline:
            output = process.stdout.read().decode() if process.stdout else ""
            raise AssertionError(f"{path} never appeared; the script printed:\n{output}")
        time.sleep(0.2)


def stop_leftovers(root: Path) -> None:
    """Stop the fake vLLM and the gatekeeper, as Slurm does when a job ends."""
    for record in ("vllm-call.json", "gatekeeper-call.json"):
        if (root / record).exists():
            with contextlib.suppress(ProcessLookupError):
                os.kill(
                    json.loads((root / record).read_text(encoding="utf-8"))["pid"], signal.SIGTERM
                )


@pytest.fixture
def running_server(
    tmp_path: Path, fake_programs: Path
) -> Iterator[tuple[subprocess.Popen[bytes], dict[str, object], Path]]:
    process = subprocess.Popen(
        ["bash", str(serve_script(tmp_path, "qwen7"))],
        env=environment(tmp_path, fake_programs),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    address_file = tmp_path / "home" / ".gagnvist" / "jobs" / f"{JOB_ID}.json"
    try:
        wait_for(address_file, process)
        yield process, json.loads(address_file.read_text(encoding="utf-8")), address_file
    finally:
        if process.poll() is None:
            process.kill()
        stop_leftovers(tmp_path / "lumi")


def test_the_server_publishes_its_address_privately(
    running_server: tuple[subprocess.Popen[bytes], dict[str, object], Path], tmp_path: Path
) -> None:
    _, address, address_file = running_server
    assert address["job"] == JOB_ID and address["kind"] == "chat" and address["model"] == "qwen7"
    assert address["node"] == subprocess.check_output(["hostname", "-s"], encoding="utf-8").strip()
    assert 20000 <= int(str(address["port"])) < 40000
    key = str(address["key"])
    assert len(key) == 60 and int(key, 16) >= 0
    assert address_file.stat().st_mode & 0o777 == 0o600
    assert address_file.parent.stat().st_mode & 0o777 == 0o700

    vllm = json.loads((tmp_path / "lumi" / "vllm-call.json").read_text(encoding="utf-8"))
    assert "--uds" in vllm["argv"] and "--port" not in vllm["argv"]  # vLLM: a socket file only
    assert key not in " ".join(vllm["argv"]) and "--api-key" not in vllm["argv"]
    gatekeeper = json.loads(
        (tmp_path / "lumi" / "gatekeeper-call.json").read_text(encoding="utf-8")
    )
    assert key not in " ".join(gatekeeper["argv"])  # the key is in its environment only


def test_only_requests_with_the_key_get_through_on_every_path(
    running_server: tuple[subprocess.Popen[bytes], dict[str, object], Path],
) -> None:
    _, address, _ = running_server
    url = f"http://127.0.0.1:{address['port']}"
    key = {"Authorization": f"Bearer {address['key']}"}
    wrong = {"Authorization": "Bearer guessed"}
    for path in ("/v1/models", "/invocations", "/health", "/pause"):
        assert httpx.get(url + path, timeout=10).status_code == 401, path
        assert httpx.get(url + path, headers=wrong, timeout=10).status_code == 401, path
    assert httpx.get(f"{url}/v1/models", headers=key, timeout=10).json()["data"][0]["id"] == "qwen7"
    assert (
        httpx.get(f"{url}/invocations", headers=key, timeout=10).text == "answered without any key"
    )

    echoed = httpx.post(f"{url}/v1/chat/completions", headers=key, json={"q": "Hæ"}, timeout=10)
    assert json.loads(echoed.json()["got"]) == {"q": "Hæ"}  # the body arrives unchanged
    assert echoed.json()["authorization"] is None  # the key is not passed on to vLLM


def test_a_streamed_answer_comes_through_piece_by_piece(
    running_server: tuple[subprocess.Popen[bytes], dict[str, object], Path],
) -> None:
    _, address, _ = running_server
    headers = {"Authorization": f"Bearer {address['key']}"}
    with httpx.stream(
        "GET", f"http://127.0.0.1:{address['port']}/v1/stream", headers=headers, timeout=10
    ) as response:
        pieces = [piece for piece in response.iter_raw() if piece]
    assert b"".join(pieces) == b"data: onedata: twodata: three"


def test_stopping_the_job_removes_its_address_and_working_files(
    running_server: tuple[subprocess.Popen[bytes], dict[str, object], Path], tmp_path: Path
) -> None:
    process, _, address_file = running_server
    vllm = json.loads((tmp_path / "lumi" / "vllm-call.json").read_text(encoding="utf-8"))
    socket_folder = Path(vllm["argv"][vllm["argv"].index("--uds") + 1]).parent
    assert socket_folder.stat().st_mode & 0o777 == 0o700
    process.send_signal(signal.SIGTERM)  # what `scancel` does
    assert process.wait(timeout=30) == 143
    assert not address_file.exists()
    assert not socket_folder.exists()


def test_a_server_that_fails_to_start_ends_the_job_without_an_address(
    tmp_path: Path, fake_programs: Path
) -> None:
    try:
        completed = subprocess.run(
            ["bash", str(serve_script(tmp_path, "broken"))],
            env=environment(tmp_path, fake_programs),
            capture_output=True,
            timeout=60,
        )
    finally:
        stop_leftovers(tmp_path / "lumi")
    assert completed.returncode == 1
    assert b"this model cannot be loaded" in completed.stderr
    assert b"The server stopped before it was ready" in completed.stderr
    assert not (tmp_path / "home" / ".gagnvist" / "jobs" / f"{JOB_ID}.json").exists()


def test_the_finetune_script_runs_its_own_copy_of_the_training_script(
    tmp_path: Path, fake_programs: Path
) -> None:
    run = tmp_path / "run"
    run.mkdir()
    (run / "train.jsonl").write_text("{}\n", encoding="utf-8")
    script = tmp_path / "finetune.sbatch"
    script.write_text(
        render_template(
            "finetune.sbatch",
            project=PROJECT,
            partition="small-g",
            cpus="7",
            hours="2",
            container=CONTAINER,
            model_path=str(tmp_path / "model"),
            run_folder=str(run),
            run_name="run",
            epochs="3",
            rank="16",
            learning_rate="0.0002",
            finetune_script=_template_text("finetune_lora.py"),
        ),
        encoding="utf-8",
    )
    env = environment(tmp_path, fake_programs)
    completed = subprocess.run(["bash", str(script)], env=env, capture_output=True, timeout=60)
    assert completed.returncode == 0, completed.stderr.decode()
    call = json.loads((tmp_path / "lumi" / "finetune-call.json").read_text(encoding="utf-8"))
    shipped = _template_text("finetune_lora.py")
    assert call["script"].rstrip("\n") == shipped.rstrip("\n")  # exactly the shipped script
    script_path = Path(call["argv"][1])
    assert not script_path.parent.exists()  # its private working folder is removed
    assert call["argv"][2:] == [
        "--model",
        str(tmp_path / "model"),
        "--data",
        f"{run}/train.jsonl",
        "--output",
        f"{run}/adapter",
        "--epochs",
        "3",
        "--rank",
        "16",
        "--learning-rate",
        "0.0002",
    ]
    assert (run / "adapter" / "adapter_config.json").exists()
    assert b"Finished: the adapter is in" in completed.stdout


@pytest.mark.parametrize("name", ["serve.sbatch", "finetune.sbatch"])
def test_job_scripts_never_put_a_key_on_a_command_line(name: str) -> None:
    assert "--api-key" not in _template_text(name)
