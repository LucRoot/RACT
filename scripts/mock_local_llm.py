# Rooted by Dr. Lucas Root, Ph.D.
"""Tiny mock OpenAI-compatible server for fast RACT burn-in validation."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import json
from http.server import BaseHTTPRequestHandler, HTTPServer

GREETER_REFACTOR = '''# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()


def format_message(text: str) -> str:
    """Internal helper."""
    return text.strip().capitalize()


def hello(name: str) -> str:
    """Return a greeting."""
    return "Hello, " + format_message(name) + "!"


def goodbye(name: str) -> str:
    """Return a farewell."""
    return "Goodbye, " + format_message(name) + "!"


def surprise(name: str) -> str:
    """Return a surprise message."""
    cleaned = format_message(name)
    return "Surprise, " + cleaned + "!"
'''

PLAN = {
    "assumption": "The greeter refactor is a straightforward rename and deduplication.",
    "confidence": 0.95,
    "steps": [
        {
            "action": "Refactor src/greeter.py: rename _fmt to format_message and remove duplicated capitalization in surprise.",
            "provider_hint": "local",
            "expected_artifact": "src/greeter.py",
        }
    ],
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"data": [{"id": "mock"}]}).encode())

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()

        if "Emit the JSON plan now" in body:
            content = json.dumps(PLAN)
        else:
            content = json.dumps(
                {"artifact": "src/greeter.py", "content": GREETER_REFACTOR}
            )
        resp = {
            "id": "mock",
            "object": "chat.completion",
            "model": "mock",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
            },
        }
        self.wfile.write(json.dumps(resp).encode())


if __name__ == "__main__":
    server = HTTPServer(("127.0.0.1", 18011), Handler)
    print("Mock local LLM on http://127.0.0.1:18011")
    server.serve_forever()
