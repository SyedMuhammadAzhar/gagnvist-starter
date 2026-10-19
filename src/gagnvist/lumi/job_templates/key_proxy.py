"""The gatekeeper in front of a model server: only requests with the key get through.

A server started by `gagnvist lumi start` runs vLLM on a socket file that only your
account can open, and this program in front of it, on a network port that the tunnel
from your computer reaches. Every request must carry the job's key, sent as
``Authorization: Bearer <key>``; any other request is refused before it reaches vLLM,
whatever its path. (vLLM's own key would protect only paths that start with /v1.)

It runs inside the job, with the Python of the LUMI container, and uses only Python's
standard library. Usage, with the key in the environment variable GAGNVIST_KEY:

    python key_proxy.py SOCKET_FILE PORT
"""

from __future__ import annotations

import hmac
import http.client
import os
import socket
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Headers about one connection rather than the request itself: not passed on.
HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer",
    "transfer-encoding", "upgrade",
}  # fmt: skip
NOT_FORWARDED = HOP_BY_HOP | {"authorization", "host", "content-length"}


class SocketConnection(http.client.HTTPConnection):
    """An HTTP connection to a server that listens on a socket file."""

    def __init__(self, socket_file: str) -> None:
        super().__init__("localhost", timeout=3600)  # writing an answer can take long
        self.socket_file = socket_file

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.socket_file)


class Gatekeeper(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    key = b""
    socket_file = ""

    def do_GET(self) -> None:
        self.forward()

    def do_POST(self) -> None:
        self.forward()

    def do_PUT(self) -> None:
        self.forward()

    def do_PATCH(self) -> None:
        self.forward()

    def do_DELETE(self) -> None:
        self.forward()

    def forward(self) -> None:
        given = self.headers.get("Authorization", "").encode()
        if not hmac.compare_digest(given, b"Bearer " + self.key):
            self.refuse(401, "this server answers only requests with its key")
            return
        if "chunked" in self.headers.get("Transfer-Encoding", "").lower():
            self.refuse(411, "send the request with a Content-Length")
            return
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        headers = {k: v for k, v in self.headers.items() if k.lower() not in NOT_FORWARDED}
        upstream = SocketConnection(self.socket_file)
        started = False
        try:
            upstream.request(self.command, self.path, body=body, headers=headers)
            response = upstream.getresponse()
            started = True
            self.send_response(response.status, response.reason)
            for name, value in response.getheaders():
                if name.lower() not in HOP_BY_HOP and name.lower() != "content-length":
                    self.send_header(name, value)
            if response.status in (204, 304):  # answers without a body
                self.end_headers()
                return
            # The answer is passed on piece by piece as vLLM writes it, so that streamed
            # answers arrive as they are generated.
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            while chunk := response.read1(65536):
                self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
                self.wfile.flush()
            self.wfile.write(b"0\r\n\r\n")
        except (OSError, http.client.HTTPException):
            if not started:  # vLLM did not answer at all
                self.refuse(502, "the model server behind the key check did not answer")
            self.close_connection = True
        finally:
            upstream.close()

    def refuse(self, status: int, message: str) -> None:
        body = b'{"error": "%s"}' % message.encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def log_message(self, format: str, *args: object) -> None:
        pass  # the job's log is kept for vLLM's own messages


def wait_until_ready(socket_file: str) -> None:
    """Wait until vLLM has loaded the model and answers on its socket file."""
    while True:
        connection = SocketConnection(socket_file)
        try:
            connection.request("GET", "/health")
            if connection.getresponse().status == 200:
                return
        except (OSError, http.client.HTTPException):
            pass
        finally:
            connection.close()
        time.sleep(2)


def main() -> None:
    socket_file, port = sys.argv[1], int(sys.argv[2])
    Gatekeeper.key = os.environ["GAGNVIST_KEY"].encode()
    Gatekeeper.socket_file = socket_file
    wait_until_ready(socket_file)
    # The port opens only now, so a port that answers means a server that is ready.
    ThreadingHTTPServer(("0.0.0.0", port), Gatekeeper).serve_forever()


if __name__ == "__main__":
    main()
