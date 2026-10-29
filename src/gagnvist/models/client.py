"""Talking to the language model and the embedding model.

The shared models run on LUMI (or on JURECA) behind the organizers' gateway, which you
reach through a private SSH tunnel (``gagnvist lumi connect``, ``gagnvist jureca
connect``). The gateway speaks the API that OpenAI made popular and that vLLM and most
model servers copy; models you start yourself (``gagnvist lumi start``) speak it too. So
one client talks to either: only the address, the key and the model name differ, and
the chat model and the embedding model may even live at different addresses ([models]
in gagnvist.toml, or your own servers in .env).
"""

from __future__ import annotations

import json
import logging
import random
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import httpx
import numpy as np

from gagnvist.config import Settings, team_key_problem
from gagnvist.search.vector_search import Vectors

Message = dict[str, str]  # {"role": "system" | "user" | "assistant", "content": ...}

log = logging.getLogger(__name__)

# A busy (429) or loading (503) server is asked again this many times, waiting a little
# longer each time; timeouts and other errors are never repeated.
RETRIES = 3


class ModelError(Exception):
    """A model could not be reached, refused the request, or gave an unusable answer."""


@dataclass(frozen=True)
class Endpoint:
    """Where one model is served."""

    url: str  # base address of the API, e.g. "http://127.0.0.1:8765/v1"
    key: str  # the key the server asks for (your team key for the shared models)
    model: str  # the model's name on that server


class ModelClient:
    """Chat with the language model and embed texts with the embedding model."""

    def __init__(
        self,
        chat: Endpoint,
        embeddings: Endpoint,
        *,
        timeout: float = 120.0,
        http: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.chat_endpoint = chat
        self.embedding_endpoint = embeddings
        # trust_env=False: requests (and their key) never go through a proxy set on this
        # computer; the models are reached through your own tunnel to LUMI.
        self._http = http or httpx.Client(timeout=timeout, trust_env=False)
        self._timeout = timeout
        self._sleep = sleep

    @classmethod
    def from_settings(cls, settings: Settings) -> ModelClient:
        """A client for the models in the settings: the shared models, reached through
        the tunnel to the supercomputer the settings say (``settings.cluster()``), or
        your own server where .env gives its address."""
        models = settings.models
        if not (models.chat_url and models.embeddings_url):
            settings.require_team_key()
        gateway = f"http://127.0.0.1:{settings.cluster().local_port}/v1"
        team_key = settings.shared_services.team_key
        return cls(
            chat=Endpoint(
                models.chat_url or gateway,
                models.chat_key if models.chat_url else team_key,
                models.chat,
            ),
            embeddings=Endpoint(
                models.embeddings_url or gateway,
                models.embeddings_key if models.embeddings_url else team_key,
                models.embeddings,
            ),
        )

    def close(self) -> None:
        self._http.close()

    def chat(self, messages: Sequence[Message], *, max_tokens: int = 512) -> str:
        """The model's reply to a conversation."""
        body: dict[str, Any] = {
            "model": self.chat_endpoint.model,
            "messages": list(messages),
            "temperature": 0.0,  # the same question gets the same answer
            "max_tokens": max_tokens,
        }
        return _message_content(self._post(self.chat_endpoint, "chat/completions", body)).strip()

    def chat_json(
        self, messages: Sequence[Message], schema: dict[str, Any], *, max_tokens: int = 512
    ) -> dict[str, Any]:
        """The model's reply as a JSON object shaped like ``schema``.

        The server is asked to keep to the schema (vLLM enforces it); the reply is still
        parsed and checked here, since not every server enforces it.
        """
        body: dict[str, Any] = {
            "model": self.chat_endpoint.model,
            "messages": list(messages),
            "temperature": 0.0,
            "max_tokens": max_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "answer", "schema": schema},
            },
        }
        reply = self._post(self.chat_endpoint, "chat/completions", body)
        return _parse_json_object(_message_content(reply))

    def embed(self, texts: Sequence[str]) -> Vectors:
        """One vector per text, in the same order."""
        body = {"model": self.embedding_endpoint.model, "input": list(texts)}
        reply = self._post(self.embedding_endpoint, "embeddings", body)
        try:
            rows = sorted(reply["data"], key=lambda row: row["index"])
            vectors = np.array([row["embedding"] for row in rows], dtype=np.float32)
        except (KeyError, TypeError, ValueError) as e:
            raise ModelError(f"unexpected reply from the embedding model: {reply!r:.300}") from e
        if vectors.ndim != 2 or len(vectors) != len(texts):
            raise ModelError(
                f"the embedding model returned {len(vectors)} vectors for {len(texts)} texts"
            )
        return vectors

    def _post(self, endpoint: Endpoint, path: str, body: dict[str, Any]) -> Any:
        for attempt in range(RETRIES + 1):
            response = self._send(endpoint, path, body)
            if response.status_code not in (429, 503) or attempt == RETRIES:
                break
            wait = _wait_before_retry(response, attempt)
            log.info(
                "  the model server %s; asking again in %.0f s (%s of %s)",
                "is busy" if response.status_code == 429 else "cannot answer yet",
                wait,
                attempt + 1,
                RETRIES,
            )
            self._sleep(wait)
        url = f"{endpoint.url.rstrip('/')}/{path}"
        if response.status_code in (401, 403):
            hint = team_key_problem(endpoint.key)
            raise ModelError(
                f"the model server at {endpoint.url} refused the key: check the key in .env "
                "(GAGNVIST_TEAM_KEY, or GAGNVIST_CHAT_KEY / GAGNVIST_EMBEDDINGS_KEY for a "
                "server of your own)"
                + (
                    f". If it is your team key: {hint}"
                    if hint and endpoint.url.startswith("http://127.0.0.1")
                    else ""
                )
            )
        if response.status_code == 404:
            raise ModelError(f"{url} or the model {endpoint.model!r} was not found on the server")
        if response.status_code == 429:
            raise ModelError(
                f"the model server is busy: {_server_message(response) or 'too many requests'}. "
                "Wait a moment and try again; if your own code sends many requests at once, "
                "send fewer at a time"
            )
        if response.status_code == 503:
            message = _server_message(response) or "unavailable"
            raise ModelError(
                f"the model server cannot answer yet: {message}. Wait a minute and try again"
            )
        if response.status_code >= 400:
            raise ModelError(
                f"the model server answered {response.status_code}: "
                f"{_server_message(response) or response.text:.300}"
            )
        try:
            return response.json()
        except ValueError:
            raise ModelError(
                f"the model server's answer is not JSON: {response.text:.300}"
            ) from None

    def _send(self, endpoint: Endpoint, path: str, body: dict[str, Any]) -> httpx.Response:
        url = f"{endpoint.url.rstrip('/')}/{path}"
        try:
            return self._http.post(
                url, json=body, headers={"Authorization": f"Bearer {endpoint.key}"}
            )
        except httpx.ConnectError:
            raise ModelError(
                f"cannot reach the model server at {endpoint.url}: is the tunnel to LUMI "
                "(or JURECA) open? (`gagnvist lumi connect`, `gagnvist jureca connect`, or "
                "`... connect --job ...` for a server of your own)"
            ) from None
        except httpx.TimeoutException:
            raise ModelError(
                f"no answer from {endpoint.url} within {self._timeout:.0f} s"
            ) from None
        except (httpx.UnsupportedProtocol, httpx.InvalidURL):
            raise ModelError(f"{endpoint.url} is not a valid address (http://...)") from None
        except httpx.HTTPError as e:  # e.g. the tunnel is open, but no server behind it
            raise ModelError(
                f"the connection to {endpoint.url} broke off ({type(e).__name__}): the tunnel "
                "may lead to a server that has stopped or moved. Stop the `connect` command "
                "(`gagnvist lumi connect` or `gagnvist jureca connect`, Ctrl+C) and start it "
                "again; `... check` says whether the shared models are running"
            ) from None
        except UnicodeError:  # httpx sends only plain ASCII in headers
            raise ModelError(
                "the key in .env contains characters other than letters and digits (copied "
                "quote marks or spaces?): copy the key again"
            ) from None


def _wait_before_retry(response: httpx.Response, attempt: int) -> float:
    """Seconds to wait before asking a busy server again: what it asks for (Retry-After,
    at most 30 s), or 2, 4, 8 s, with a little randomness so that many clients do not
    all come back at the same moment."""
    try:
        asked = float(response.headers.get("retry-after", ""))
    except ValueError:
        asked = 0.0
    return min(max(asked, 2.0**attempt * 2), 30.0) + random.uniform(0, 1)


def _server_message(response: httpx.Response) -> str:
    """The error message in a server's JSON answer ({"error": "..."} from the gateway,
    {"message": ...} or {"error": {"message": ...}} from vLLM), or ""."""
    try:
        answer = response.json()
    except ValueError:
        return ""
    if not isinstance(answer, dict):
        return ""
    error = answer.get("error", answer.get("message", ""))
    if isinstance(error, dict):
        error = error.get("message", "")
    return str(error)[:300]


def _message_content(reply: Any) -> str:
    """The text of the first choice in a chat reply."""
    try:
        content = reply["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise ModelError(f"unexpected reply from the chat model: {reply!r:.300}") from e
    if not isinstance(content, str):  # e.g. null when the model only called a tool
        raise ModelError(f"the chat model's reply has no text: {reply!r:.300}")
    return content


def _parse_json_object(content: str) -> dict[str, Any]:
    """The JSON object in a model's reply, allowing for text or code fences around it."""
    start, end = content.find("{"), content.rfind("}")
    if start < 0 or end < start:
        raise ModelError(f"the model did not answer with JSON: {content!r:.300}")
    try:
        value = json.loads(content[start : end + 1])
    except json.JSONDecodeError as e:
        raise ModelError(f"the model's JSON could not be read: {content!r:.300}") from e
    if not isinstance(value, dict):
        raise ModelError(f"the model's JSON is not an object: {content!r:.300}")
    return value
