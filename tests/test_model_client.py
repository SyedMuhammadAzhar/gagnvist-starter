"""Talking to the model servers (answered here by fake servers, without a network)."""

import http.server
import json
import socket
import threading
from collections.abc import Callable
from pathlib import Path

import httpx
import numpy as np
import pytest
from conftest import write_settings

from gagnvist.config import ConfigError, load_settings
from gagnvist.models.client import Endpoint, ModelClient, ModelError

Handler = Callable[[httpx.Request], httpx.Response]
CHAT = Endpoint("http://chat.test/v1", "chat-key", "chat-model")
EMBEDDINGS = Endpoint("http://embed.test/v1", "embed-key", "embed-model")


def client_answering(handler: Handler, waits: list[float] | None = None) -> ModelClient:
    """A client whose server is ``handler``; it does not really wait before a retry, but
    notes each wait in ``waits``."""
    http = httpx.Client(transport=httpx.MockTransport(handler))
    note = waits.append if waits is not None else (lambda seconds: None)
    return ModelClient(CHAT, EMBEDDINGS, http=http, sleep=note)


def chat_reply(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def test_chat_sends_model_key_and_messages() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return chat_reply("  Halló!  ")

    reply = client_answering(handler).chat([{"role": "user", "content": "Say hello"}])
    assert reply == "Halló!"
    request = seen[0]
    assert str(request.url) == "http://chat.test/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer chat-key"
    body = json.loads(request.content)
    assert body["model"] == "chat-model"
    assert body["temperature"] == 0.0
    assert body["messages"] == [{"role": "user", "content": "Say hello"}]


def test_chat_json_asks_for_the_schema_and_reads_json_in_code_fences() -> None:
    schema = {"type": "object"}
    seen: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return chat_reply('Here it is:\n```json\n{"categories": {"Ár": ["2024"]}}\n```')

    reply = client_answering(handler).chat_json([{"role": "user", "content": "?"}], schema)
    assert reply == {"categories": {"Ár": ["2024"]}}
    assert seen[0]["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "answer", "schema": schema},
    }


@pytest.mark.parametrize("content", ["no json here", '["a list"]', "{not json}"])
def test_chat_json_refuses_replies_that_are_not_a_json_object(content: str) -> None:
    client = client_answering(lambda request: chat_reply(content))
    with pytest.raises(ModelError, match="JSON"):
        client.chat_json([{"role": "user", "content": "?"}], {"type": "object"})


def test_embed_returns_vectors_in_the_order_of_the_texts() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://embed.test/v1/embeddings"
        assert request.headers["Authorization"] == "Bearer embed-key"
        texts = json.loads(request.content)["input"]
        data = [{"index": i, "embedding": [float(len(t)), 1.0]} for i, t in enumerate(texts)]
        return httpx.Response(200, json={"data": list(reversed(data))})  # any order

    vectors = client_answering(handler).embed(["a", "bbb", "cc"])
    assert vectors.dtype == np.float32
    np.testing.assert_array_equal(vectors[:, 0], [1.0, 3.0, 2.0])


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (401, "refused the key"),
        (403, "refused the key"),
        (404, "not found"),
        (429, "busy"),
        (503, "cannot answer yet"),
        (500, "answered 500"),
    ],
)
def test_server_errors_are_explained(status: int, message: str) -> None:
    client = client_answering(lambda request: httpx.Response(status, text="oops"))
    with pytest.raises(ModelError, match=message):
        client.chat([{"role": "user", "content": "?"}])


def test_a_busy_server_is_asked_again_and_its_wait_respected() -> None:
    answers = [
        httpx.Response(429, json={"error": "busy"}, headers={"Retry-After": "5"}),
        httpx.Response(503, json={"error": "loading"}),
        chat_reply("fine"),
    ]
    waits: list[float] = []
    client = client_answering(lambda request: answers.pop(0), waits)
    assert client.chat([{"role": "user", "content": "?"}]) == "fine"
    assert len(waits) == 2
    assert 5 <= waits[0] < 6  # as the server asked
    assert 4 <= waits[1] < 5  # the second wait: 4 s and a little randomness


def test_a_server_that_stays_busy_gives_its_own_message() -> None:
    waits: list[float] = []
    client = client_answering(
        lambda request: httpx.Response(
            429, json={"error": "your team already has 8 requests in progress"}
        ),
        waits,
    )
    with pytest.raises(ModelError, match="busy: your team already has 8 requests in progress"):
        client.chat([{"role": "user", "content": "?"}])
    assert len(waits) == 3  # asked four times in all


def test_other_errors_are_not_repeated() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(500, json={"message": "out of memory"})

    with pytest.raises(ModelError, match="answered 500: out of memory"):
        client_answering(handler).chat([{"role": "user", "content": "?"}])
    assert len(calls) == 1


def test_a_refused_team_key_is_described() -> None:
    client = ModelClient(
        Endpoint("http://127.0.0.1:8765/v1", "paste-it-here", "m"),
        EMBEDDINGS,
        http=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(401))),
    )
    with pytest.raises(ModelError, match="it has 13 characters"):
        client.chat([{"role": "user", "content": "?"}])


def test_a_key_with_typographic_quotes_is_explained_not_a_crash() -> None:
    client = ModelClient(
        Endpoint("http://127.0.0.1:8765/v1", "\u201ckey\u201d", "m"),
        EMBEDDINGS,
        http=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200))),
    )
    with pytest.raises(ModelError, match="copy the key again"):
        client.chat([{"role": "user", "content": "?"}])


def test_an_answer_that_is_not_json_is_explained() -> None:
    client = client_answering(lambda request: httpx.Response(200, text="<html>proxy</html>"))
    with pytest.raises(ModelError, match="not JSON"):
        client.embed(["text"])


@pytest.mark.parametrize("error", [httpx.ReadError, httpx.RemoteProtocolError])
def test_a_tunnel_without_a_server_behind_it_is_explained(error: type[httpx.HTTPError]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise error("Connection reset by peer", request=request)

    with pytest.raises(ModelError, match="broke off"):
        client_answering(handler).chat([{"role": "user", "content": "?"}])


def test_an_address_without_http_is_explained() -> None:
    client = ModelClient(Endpoint("localhost:8801/v1", "k", "m"), EMBEDDINGS)
    with pytest.raises(ModelError, match="not a valid address"):
        client.chat([{"role": "user", "content": "?"}])
    client.close()


def test_a_proxy_set_on_the_computer_is_not_used(monkeypatch: pytest.MonkeyPatch) -> None:
    """The key must not travel through a proxy: requests go straight to the tunnel."""

    class Answer(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            self.rfile.read(int(self.headers["Content-Length"]))
            body = json.dumps({"choices": [{"message": {"content": "direct"}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Answer)
    threading.Thread(target=server.handle_request, daemon=True).start()
    with socket.socket() as proxy:  # a "proxy" that would see any request sent to it
        proxy.bind(("127.0.0.1", 0))
        proxy.listen()
        proxy.settimeout(0.5)
        monkeypatch.setenv("HTTP_PROXY", f"http://127.0.0.1:{proxy.getsockname()[1]}")
        monkeypatch.setenv("NO_PROXY", "")
        url = f"http://127.0.0.1:{server.server_address[1]}/v1"
        client = ModelClient(Endpoint(url, "secret", "m"), Endpoint(url, "secret", "m"))
        assert client.chat([{"role": "user", "content": "?"}]) == "direct"
        client.close()
        with pytest.raises(TimeoutError):
            proxy.accept()  # nothing came to the proxy
    server.server_close()


def test_an_unreachable_server_points_to_the_tunnel() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(ModelError, match="is the tunnel open"):
        client_answering(handler).chat([{"role": "user", "content": "?"}])


def test_from_settings_needs_the_team_key(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="team's key"):
        ModelClient.from_settings(load_settings(write_settings(tmp_path, env={})))


def test_from_settings_can_use_your_own_servers_without_a_team_key(tmp_path: Path) -> None:
    env = {
        "GAGNVIST_CHAT_URL": "http://localhost:8801/v1",
        "GAGNVIST_CHAT_KEY": "own-key",
        "GAGNVIST_EMBEDDINGS_URL": "http://localhost:8802/v1",
    }
    client = ModelClient.from_settings(load_settings(write_settings(tmp_path, env)))
    assert client.chat_endpoint == Endpoint("http://localhost:8801/v1", "own-key", "qwen2.5-7b")
    assert client.embedding_endpoint == Endpoint("http://localhost:8802/v1", "", "bge-m3")
    client.close()


def test_a_reply_without_text_is_explained() -> None:
    reply = httpx.Response(200, json={"choices": [{"message": {"content": None}}]})
    with pytest.raises(ModelError, match="no text"):
        client_answering(lambda request: reply).chat([{"role": "user", "content": "?"}])


def test_a_wrong_number_of_vectors_is_refused() -> None:
    data = {"data": [{"index": 0, "embedding": [1.0, 0.0]}]}
    client = client_answering(lambda request: httpx.Response(200, json=data))
    with pytest.raises(ModelError, match="1 vectors for 2 texts"):
        client.embed(["one", "two"])


def test_from_settings_uses_the_tunnel_and_the_shared_models(tmp_path: Path) -> None:
    settings = load_settings(write_settings(tmp_path, {"GAGNVIST_TEAM_KEY": "team-07-key"}))
    client = ModelClient.from_settings(settings)
    assert client.chat_endpoint == Endpoint("http://127.0.0.1:8775/v1", "team-07-key", "qwen2.5-7b")
    assert client.embedding_endpoint.model == "bge-m3"
    client.close()
