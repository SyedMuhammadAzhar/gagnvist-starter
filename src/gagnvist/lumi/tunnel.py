"""Keeping a tunnel to a model server on LUMI open until you press Ctrl+C.

The tunnel ends on your computer at ``http://127.0.0.1:<port>/v1``, and only programs on
your computer can use it. If the connection drops, for example when the laptop sleeps
or changes network, it is opened again by itself.
"""

from __future__ import annotations

import socket
import subprocess
import time
from collections.abc import Callable

import httpx

from gagnvist.lumi.connection import Lumi, LumiError

RECONNECT_AFTER = 10  # seconds


def hold_tunnel(
    lumi: Lumi,
    local_port: int,
    find_server: Callable[[], tuple[str, int]],
    key: str,
    say: Callable[[str], None] = print,
) -> None:
    """Open a tunnel to the server that ``find_server`` names (node, port), check that it
    answers, and keep the tunnel open until Ctrl+C.

    ``find_server`` is asked again before every reconnection, since a restarted server
    may run on another node.
    """
    if not port_is_free(local_port):
        raise LumiError(
            f"port {local_port} on this computer is already in use, perhaps by another "
            "tunnel: close that program, or choose another port"
        )
    connected_once = False
    try:
        while True:
            try:
                node, remote_port = find_server()
            except LumiError as error:
                if not connected_once:
                    raise
                say(f"{error}. Trying again in {RECONNECT_AFTER} s; press Ctrl+C to stop.")
                time.sleep(RECONNECT_AFTER)
                continue

            say(f"Opening a tunnel: 127.0.0.1:{local_port} -> {node}:{remote_port} on LUMI")
            process = lumi.open_tunnel(local_port, node, remote_port)
            try:
                if _wait_until_listening(local_port, process):
                    connected_once = True
                    say(check_server(local_port, key))
                    say("The tunnel stays open until you press Ctrl+C.")
                status = process.wait()
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait()

            if not connected_once:
                raise LumiError(f"the tunnel could not be opened (ssh ended with status {status})")
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
    except httpx.HTTPError:
        return (
            "The tunnel is open, but the server on LUMI does not answer yet. A server that "
            "has just started can take several minutes to load its model."
        )
    if response.status_code in (401, 403):
        return f"The tunnel is open, but the server at {url} refused the key."
    if response.status_code != 200:
        return f"The tunnel is open, but the server at {url} answered {response.status_code}."
    try:
        models = [str(model["id"]) for model in response.json()["data"]]
    except (ValueError, KeyError, TypeError):
        models = []
    return f"Connected: {url} serves {', '.join(models) or 'no models'}."


def port_is_free(port: int) -> bool:
    """Whether a program on this computer could listen on ``port``."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


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
