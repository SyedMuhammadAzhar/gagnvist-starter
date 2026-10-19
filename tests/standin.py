"""A stand-in for the model servers on LUMI, for tests and for trying the program offline.

It answers the same API as the real servers, but no model is involved:

- embeddings: a text becomes the counts of its three-letter pieces, hashed into
  DIMENSIONS numbers, so texts that share words get similar vectors;
- chat that asks for JSON (choosing categories): for every dimension, the categories
  whose label shares the most words with the question; none if no word is shared;
- other chat (writing the answer): the facts it was given, repeated.

In tests it is used through ``httpx.MockTransport(handle)``. To run it as a server:

    python tests/standin.py --port 8765
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import httpx

DIMENSIONS = 256
CHAT_MODEL = "standin-chat"
EMBEDDING_MODEL = "standin-embeddings"

_DIMENSION_LINE = re.compile(r'^Dimension "(?P<code>[^"]+)":')
_CATEGORY_LINE = re.compile(r"^  (?P<code>[^:]+): (?P<label>.*)$")


def handle(request: httpx.Request) -> httpx.Response:
    """Answer one request the way an OpenAI-compatible server would."""
    body = json.loads(request.content or b"{}")
    if request.url.path.endswith("/embeddings"):
        vectors = [embed_text(text) for text in body["input"]]
        data = [{"index": i, "embedding": vector} for i, vector in enumerate(vectors)]
        return httpx.Response(200, json={"model": EMBEDDING_MODEL, "data": data})
    if request.url.path.endswith("/chat/completions"):
        content = _choose(body) if "response_format" in body else _write(body)
        message = {"role": "assistant", "content": content}
        return httpx.Response(200, json={"model": CHAT_MODEL, "choices": [{"message": message}]})
    return httpx.Response(404, json={"error": f"no such path: {request.url.path}"})


def embed_text(text: str) -> list[float]:
    vector = [0.0] * DIMENSIONS
    for word in re.findall(r"\w+", text.lower()):
        padded = f" {word} "
        for start in range(len(padded) - 2):
            digest = hashlib.blake2b(padded[start : start + 3].encode(), digest_size=4).digest()
            vector[int.from_bytes(digest, "little") % DIMENSIONS] += 1.0
    length = math.sqrt(sum(x * x for x in vector)) or 1.0
    return [x / length for x in vector]


def _choose(body: dict[str, Any]) -> str:
    prompt = body["messages"][-1]["content"]
    question = _words(prompt.split("\n", 1)[0])
    proposal: dict[str, list[str]] = {}
    dimension = ""
    scores: dict[str, list[tuple[int, str]]] = {}
    for line in prompt.splitlines():
        if found := _DIMENSION_LINE.match(line):
            dimension = found["code"]
            scores[dimension] = []
        elif (found := _CATEGORY_LINE.match(line)) and dimension:
            scores[dimension].append((len(question & _words(found["label"])), found["code"]))
    for code, scored in scores.items():
        best = max((score for score, _ in scored), default=0)
        if best > 0:
            proposal[code] = [category for score, category in scored if score == best]
    return json.dumps({"categories": proposal}, ensure_ascii=False)


def _write(body: dict[str, Any]) -> str:
    prompt = body["messages"][-1]["content"]
    facts = [line[2:] for line in prompt.splitlines() if line.startswith("- ")]
    if not facts:
        return "This is the stand-in model: it can only repeat the facts it is given."
    return "Stand-in answer: " + " | ".join(facts)


def _words(text: str) -> set[str]:
    return {word for word in re.findall(r"\w+", text.lower()) if len(word) > 2 or word.isdigit()}


class _Server(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        request = httpx.Request(
            "POST", f"http://standin{self.path}", content=self.rfile.read(length)
        )
        response = handle(request)
        self.send_response(response.status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response.content)))
        self.end_headers()
        self.wfile.write(response.content)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"stand-in: {self.command} {self.path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--port", type=int, default=8765)
    port = parser.parse_args().port
    print(f"stand-in model server on http://localhost:{port}/v1 (stop with Ctrl+C)")
    ThreadingHTTPServer(("127.0.0.1", port), _Server).serve_forever()
