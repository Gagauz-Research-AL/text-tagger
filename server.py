#!/usr/bin/env python3
"""Dev server for the text-tagger web UI (stdlib only).

Routes:
    GET  /              static/index.html
    GET  /static/...    vendored assets (vue, logic.js)
    GET  /api/job       the mock job (external JSON format)
    GET  /api/jobs      the mock job backlog
    POST /api/result    prints the approved final text to the console
    POST /api/skip      prints the skipped job ID to the console
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from mock_data import generate_mock, generate_mock_jobs
from tagger import approve

ROOT = Path(__file__).parent / "static"

TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".woff2": "font/woff2",
}


class Handler(BaseHTTPRequestHandler):
    def _send(self, status, body, ctype="text/plain; charset=utf-8"):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json(self, status, obj):
        self._send(status, json.dumps(obj), "application/json; charset=utf-8")

    def do_GET(self):
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path == "/" or path == "/index.html":
            self._serve_file("index.html")
        elif path == "/api/job":
            self._json(200, generate_mock())
        elif path == "/api/jobs":
            self._json(200, {"jobs": generate_mock_jobs()})
        elif path.startswith("/static/"):
            self._serve_file(path.removeprefix("/static/"))
        else:
            self._send(404, "not found")

    def do_POST(self):
        path = self.path.rstrip("/")
        length = int(self.headers.get("Content-Length", 0))
        try:
            raw = json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            self._json(400, {"status": "bad json"})
            return

        if path == "/api/result":
            job_id = raw.get("id", "unknown")
            print(f"\n--- FINAL TEXT [{job_id}] ---")
            print(approve({"text": str(raw.get("text", "")), "underlines": []}), flush=True)
            self._json(200, {"status": "saved", "id": job_id})
        elif path == "/api/skip":
            job_id = raw.get("id", "unknown")
            print(f"\n--- SKIPPED [{job_id}] ---", flush=True)
            self._json(200, {"status": "skipped", "id": job_id})
        else:
            self._send(404, "not found")

    def _serve_file(self, name):
        f = (ROOT / name).resolve()
        if not str(f).startswith(str(ROOT.resolve())) or not f.is_file():
            self._send(404, "not found")
            return
        ctype = TYPES.get(f.suffix, "application/octet-stream")
        self._send(200, f.read_bytes(), ctype)

    def log_message(self, fmt, *args):
        pass


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1",
                        help="bind address; use 0.0.0.0 inside docker")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"text-tagger UI on http://{args.host}:{args.port}  (Ctrl+C to stop)", flush=True)
    threading.current_thread().name = "MainServer"
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
