"""Keeping a tunnel open (the tunnel is played here by a small local server)."""

import socket
import subprocess
import sys

import pytest

from gagnvist.lumi.connection import LumiError
from gagnvist.lumi.tunnel import check_server, hold_tunnel, port_is_free

SERVER = """
import http.server, json, sys
port, name, status, requests = int(sys.argv[1]), sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
class Answer(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(status)
        self.end_headers()
        self.wfile.write(json.dumps({"data": [{"id": name}]}).encode())
    def log_message(self, *args):
        pass
server = http.server.HTTPServer(("127.0.0.1", port), Answer)
if requests:  # end after this many connections
    for _ in range(requests):
        server.handle_request()
else:
    server.serve_forever()
"""


class LocalTunnel:
    """Stands in for Lumi: the "tunnel" is a local server named after its target.

    With ``drops``, the first tunnel ends after answering one request, as if the
    laptop had gone to sleep.
    """

    def __init__(self, status: int = 200, opens: bool = True, drops: bool = False) -> None:
        self.status = status
        self.opens = opens
        self.drops = drops
        self.processes: list[subprocess.Popen[bytes]] = []

    def open_tunnel(self, local_port: int, node: str, remote_port: int) -> subprocess.Popen[bytes]:
        if not self.opens:
            command = [sys.executable, "-c", "raise SystemExit(255)"]
        else:
            # A dropping tunnel ends after two connections: the port check and one request.
            requests = 2 if self.drops and not self.processes else 0
            command = [sys.executable, "-c", SERVER, str(local_port), f"{node}:{remote_port}"]
            command += [str(self.status), str(requests)]
        process = subprocess.Popen(command)
        self.processes.append(process)
        return process


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
        return port


def stop_when_connected(messages: list[str]):  # type: ignore[no-untyped-def]
    def say(message: str) -> None:
        messages.append(message)
        if message.startswith(("Connected", "The tunnel is open")):
            raise KeyboardInterrupt  # as if you pressed Ctrl+C

    return say


def test_the_tunnel_is_checked_and_closed_with_ctrl_c() -> None:
    port, tunnel, messages = free_port(), LocalTunnel(), []
    hold_tunnel(tunnel, port, lambda: ("nid005001", 4000), "key", stop_when_connected(messages))  # type: ignore[arg-type]
    assert f"Connected: http://127.0.0.1:{port}/v1 serves nid005001:4000." in messages
    assert messages[-1] == "Tunnel closed."
    assert all(process.poll() is not None for process in tunnel.processes)  # ssh is stopped


def test_a_refused_key_is_reported() -> None:
    port, tunnel, messages = free_port(), LocalTunnel(status=401), []
    hold_tunnel(tunnel, port, lambda: ("nid005001", 4000), "bad", stop_when_connected(messages))  # type: ignore[arg-type]
    assert (
        f"The tunnel is open, but the server at http://127.0.0.1:{port}/v1 refused the key."
        in messages
    )


def test_a_tunnel_that_never_opens_is_an_error() -> None:
    with pytest.raises(LumiError, match="could not be opened"):
        hold_tunnel(LocalTunnel(opens=False), free_port(), lambda: ("nid1", 4000), "key", print)  # type: ignore[arg-type]


def test_a_port_in_use_is_refused_before_connecting() -> None:
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        port = busy.getsockname()[1]
        assert not port_is_free(port)
        with pytest.raises(LumiError, match="already in use"):
            hold_tunnel(LocalTunnel(), port, lambda: ("nid1", 4000), "key", print)  # type: ignore[arg-type]


def test_a_server_that_does_not_answer_yet_is_explained() -> None:
    assert "does not answer yet" in check_server(free_port(), "key")


def test_a_dropped_tunnel_is_reopened_to_wherever_the_server_now_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("gagnvist.lumi.tunnel.RECONNECT_AFTER", 0)
    nodes = iter(["nid005001", "nid005002"])  # the server moved to another node
    port, tunnel, messages = free_port(), LocalTunnel(drops=True), []

    def say(message: str) -> None:
        messages.append(message)
        if message.startswith("Connected") and "nid005002" in message:
            raise KeyboardInterrupt

    hold_tunnel(tunnel, port, lambda: (next(nodes), 4000), "key", say)  # type: ignore[arg-type]
    connected = [m for m in messages if m.startswith("Connected")]
    assert connected == [
        f"Connected: http://127.0.0.1:{port}/v1 serves nid005001:4000.",
        f"Connected: http://127.0.0.1:{port}/v1 serves nid005002:4000.",
    ]
    assert any(m.startswith("The tunnel closed") for m in messages)
