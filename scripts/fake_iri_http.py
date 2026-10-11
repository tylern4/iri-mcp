"""Canned IRI backend for the offline smoke test.

Serves the well-tested ``FakeIRI`` handler (from the test suite) over real
HTTP so ``scripts/smoke_mcp.sh`` can run a genuine end-to-end pass: real MCP
server subprocess + real MCP stdio client + real HTTP request/response cycle —
without touching the live NERSC API.

Usage:
    uv run python scripts/fake_iri_http.py [--host 127.0.0.1] [--port 8971]
"""

from __future__ import annotations

import argparse
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from fake_iri import FakeIRI  # noqa: E402


class _Handler(BaseHTTPRequestHandler):
    server_version = "FakeIRI/1.0"

    def _route(self, method: str) -> None:
        length = int(self.headers.get("content-length", 0) or 0)
        body = self.rfile.read(length) if length else None
        base = f"http://127.0.0.1:{self.server.server_port}"
        request = httpx.Request(
            method,
            base + self.path,
            headers={k: v for k, v in self.headers.items()},
            content=body,
        )
        response = self.server.fake.handler(request)  # type: ignore[attr-defined]
        self.send_response(response.status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response.content)))
        self.end_headers()
        self.wfile.write(response.content)

    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        self._route("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._route("POST")

    def do_PUT(self) -> None:  # noqa: N802
        self._route("PUT")

    def do_DELETE(self) -> None:  # noqa: N802
        self._route("DELETE")

    def log_message(self, format: str, *args: object) -> None:
        pass  # keep the smoke output clean


def _seed(fake: FakeIRI) -> None:
    """Give the smoke workflow some deterministic content."""
    out = "/pscratch/sd/e/elvis/tmp/hello.out"
    err = "/pscratch/sd/e/elvis/tmp/hello.err"
    fake.files[out] = "hello from the fake backend\n"
    fake.files[err] = ""
    fake.checksums[out] = "d1" * 32


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8971)
    args = parser.parse_args()

    fake = FakeIRI()
    _seed(fake)
    server = ThreadingHTTPServer((args.host, args.port), _Handler)
    server.fake = fake  # type: ignore[attr-defined]
    print(
        f"fake IRI backend on http://{args.host}:{server.server_address[1]}/api/v1",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()