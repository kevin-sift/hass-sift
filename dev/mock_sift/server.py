#!/usr/bin/env python3
"""Minimal schemaless ingest mock for local hass-sift testing."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

OUT = Path(__file__).resolve().parent / "received.jsonl"
PORT = 8765


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:  # quieter
        print(f"[mock-sift] {self.address_string()} - {fmt % args}")

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b'{"error":"invalid json"}')
            return

        auth = self.headers.get("Authorization", "")
        record = {
            "received_at": datetime.now(timezone.utc).isoformat(),
            "path": self.path,
            "authorization_present": auth.startswith("Bearer "),
            "payload": payload,
        }
        with OUT.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")

        channels = []
        for row in payload.get("data") or []:
            for val in row.get("values") or []:
                channels.append(val.get("channel"))
        print(f"[mock-sift] ok asset={payload.get('asset_name')} channels={channels[:8]}")

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status":"ok"}')


if __name__ == "__main__":
    OUT.write_text("")
    httpd = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"[mock-sift] listening on :{PORT}, writing {OUT}")
    httpd.serve_forever()
