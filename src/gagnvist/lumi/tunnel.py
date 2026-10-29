"""Keeping a tunnel to a model server on LUMI or JURECA open until you press Ctrl+C.

The tunnel ends on your computer at ``http://127.0.0.1:<port>/v1``, and only programs on
your computer can use it. If the connection drops, for example when the laptop sleeps
or changes network, it is opened again by itself. While it is open, it checks every
minute that the server still answers; if the server has moved to another node (it was
restarted there), the tunnel follows it.
"""

from __future__ import annotations

import errno
import os
import signal
import socket
import subprocess
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from types import FrameType

import httpx

from gagnvist.config import team_key_problem
from gagnvist.lumi.connection import Lumi, LumiError

RECONNECT_AFTER = 30  # seconds to wait before opening a dropped tunnel again
CHECK_EVERY = 60  # seconds between checks that the server still answers
CHECKS_BEFORE_LOOKUP = 2  # failed checks in a row before asking LUMI where the server is


def hold_tunnel(
    lumi: Lumi,
    local_port: int,
    find_server: Callable[[], tuple[str, int]],
    key: str,
    say: Callable[[str], None] = print,
    label: str = "LUMI",
) -> None:
    """Open a tunnel to the server that ``find_server`` names (node, port), check that it
    answers, and keep the tunnel open until Ctrl+C.

    ``find_server`` is asked again before every reconnection, and whenever the server
    stops answering, since a restarted server may run on another node. ``label`` is the
    supercomputer's name, for the messages.
    """
    problem = port_problem(local_port)
    if problem:
        raise LumiError(problem)
    connected_once = False
    moved_to: tuple[str, int] | None = None  # where the server went, if the tunnel saw it move
    with _stop_on_signals():
        try:
            while True:
                try:
                    node, remote_port = moved_to or find_server()
                    moved_to = None
                except LumiError as error:
                    if not connected_once:
                        raise
                    say(f"{error}. Trying again in {RECONNECT_AFTER} s; press Ctrl+C to stop.")
                    time.sleep(RECONNECT_AFTER)
                    continue

                say(f"Opening a tunnel: 127.0.0.1:{local_port} -> {node}:{remote_port} on {label}")
                process = lumi.open_tunnel(local_port, node, remote_port)
                status: int | tuple[str, int]
                try:
                    if _wait_until_listening(local_port, process):
                        connected_once = True
                        say(check_server(local_port, key))
                        say("The tunnel stays open until you press Ctrl+C.")
                        status = _watch(process, local_port, key, node, find_server, say, label)
                    else:
                        status = process.wait()
                finally:
                    _stop(process)

                if not connected_once:
                    raise LumiError(
                        f"the tunnel could not be opened (ssh ended with status {status})"
                    )
                if isinstance(status, tuple):  # the server moved: follow it at once
                    moved_to = status
                    continue
                say(
                    f"The tunnel closed (ssh ended with status {status}); reopening it in "
                    f"{RECONNECT_AFTER} s. Press Ctrl+C to stop."
                )
                time.sleep(RECONNECT_AFTER)
        except KeyboardInterrupt:
            say("Tunnel closed.")


def check_server(port: int, key: str) -> str:
    """Ask the server at the end of the tunnel which models it serves; say what happened."""
    url = f"http://127.0.0.1:{port}/v1"
    try:
        response = httpx.get(  # trust_env=False: never through a proxy set on this computer
            f"{url}/models", headers={"Authorization": f"Bearer {key}"}, timeout=30, trust_env=False
        )
    except (httpx.HTTPError, UnicodeError):
        return (
            "The tunnel is open, but the server at its other end does not answer yet. A "
            "server that has just started can take several minutes to load its model."
        )
    if response.status_code in (401, 403):
        hint = team_key_problem(key)
        return (
            f"The tunnel is open, but the server at {url} refused the key."
            + (f" PROBLEM: the key in .env does not look like a team key: {hint}." if hint else "")
            + " Fix the key in .env; the tunnel can stay open, as every command reads .env again."
        )
    if response.status_code != 200:
        return f"The tunnel is open, but the server at {url} answered {response.status_code}."
    try:
        models = [str(model["id"]) for model in response.json()["data"]]
    except (ValueError, KeyError, TypeError):
        models = []
    return f"Connected: {url} serves {', '.join(models) or 'no models'}."


def try_key(lumi: Lumi, node: str, remote_port: int, key: str, wait: float = 60) -> str:
    """Open a short tunnel on a free port, ask the server with ``key``, and close it again.

    Returns what :func:`check_server` says, or why the tunnel did not open in time."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
    process = lumi.open_tunnel(port, node, remote_port)
    try:
        deadline = time.monotonic() + wait
        while process.poll() is None and time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    return check_server(port, key)
            except OSError:
                time.sleep(0.5)
        return f"the tunnel to {node} did not open within {wait:.0f} s"
    finally:
        _stop(process)


def server_answers(port: int, key: str, timeout: float = 20) -> bool:
    """Whether anything answers HTTP at the end of the tunnel (any status counts)."""
    try:
        httpx.get(
            f"http://127.0.0.1:{port}/v1/models",
            headers={"Authorization": f"Bearer {key}"} if key else {},
            timeout=timeout,
            trust_env=False,
        )
    except (httpx.HTTPError, UnicodeError):
        return False
    return True


def port_problem(port: int) -> str | None:
    """Why a tunnel cannot listen on ``port`` on this computer, in words; None if it can."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        if os.name != "nt":  # do not mistake a just-closed connection for a busy port
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError as error:
            failure = error
        else:
            return None
    another_port = (
        "choose another port: for the shared models, add GAGNVIST_LOCAL_PORT=8790 (or any "
        "free port; for JURECA, GAGNVIST_JURECA_LOCAL_PORT) to .env; for a server of your "
        "own, use --port"
    )
    if failure.errno == errno.EACCES or getattr(failure, "winerror", None) == 10013:
        return (
            f"this computer does not let programs use port {port} (Windows reserves some "
            "ports, for example for Hyper-V, WSL or Docker; `netsh interface ipv4 show "
            f"excludedportrange protocol=tcp` lists them): {another_port}"
        )
    if server_answers(port, "", timeout=5):
        return (
            f"port {port} on this computer is already in use by a tunnel, perhaps another "
            "`gagnvist lumi connect` (or `jureca connect`) that is still open, or one that "
            "was closed badly and left its ssh behind. Use that one, or stop it: on macOS or "
            f"Linux, `lsof -nP -iTCP:{port} -sTCP:LISTEN` shows its PID, then `kill <PID>`; on "
            f"Windows, `netstat -ano | findstr :{port}` shows its PID, then "
            f"`taskkill /PID <PID> /F`. Or {another_port}"
        )
    return (
        f"port {port} on this computer is already in use by another program (the Anki "
        f"add-on AnkiConnect, for example, uses 8765): close it, or {another_port}"
    )


def port_is_free(port: int) -> bool:
    """Whether a program on this computer could listen on ``port``."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        if os.name != "nt":
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _watch(
    process: subprocess.Popen[bytes],
    port: int,
    key: str,
    node: str,
    find_server: Callable[[], tuple[str, int]],
    say: Callable[[str], None],
    label: str = "LUMI",
) -> int | tuple[str, int]:
    """Wait while ssh runs, checking now and then that the server still answers.

    ssh itself keeps running when the server behind the tunnel is gone, so when the
    server stops answering, the supercomputer is asked where it runs now. Returns ssh's
    exit status when ssh ends, or the server's new (node, port) when it has moved.
    """
    failed = 0
    while True:
        try:
            return process.wait(timeout=CHECK_EVERY)
        except subprocess.TimeoutExpired:
            pass
        if server_answers(port, key):
            failed = 0
            continue
        failed += 1
        if failed < CHECKS_BEFORE_LOOKUP:
            continue
        failed = 0
        try:
            new_node, new_port = find_server()
        except LumiError as error:
            say(f"The server on {label} does not answer ({error}); checking again in a minute.")
            continue
        if new_node != node:
            say(f"The server on {label} now runs on {new_node}, not {node}: following it.")
            return new_node, new_port
        say(f"The server on {label} does not answer; it may be restarting. Checking again.")


def _stop(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


@contextmanager
def _stop_on_signals() -> Iterator[None]:
    """Treat "please stop" signals like Ctrl+C, so that ssh is stopped too.

    Without this, ``kill``, closing an editor's terminal or a program stopping this one
    would end Python at once and leave ssh running, holding the port.
    """

    def stop(signum: int, frame: FrameType | None) -> None:
        raise KeyboardInterrupt

    previous = {}
    for name in ("SIGTERM", "SIGHUP", "SIGBREAK"):  # SIGBREAK: Ctrl+Break on Windows
        number = getattr(signal, name, None)
        if number is None:
            continue
        with suppress(ValueError, OSError):  # not the main thread, or not allowed here
            previous[number] = signal.signal(number, stop)
    try:
        yield
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


def _wait_until_listening(port: int, process: subprocess.Popen[bytes]) -> bool:
    """Wait until the tunnel listens on ``port``; False if ssh ends first.

    There is no time limit: ssh may be waiting for you to type your key's passphrase.
    """
    while process.poll() is None:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            time.sleep(0.5)
    return False
