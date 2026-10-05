from __future__ import annotations

import argparse
import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .engine import AssistEngine, IntakeError


class Handler(BaseHTTPRequestHandler):
    engine: AssistEngine

    def _reply(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json_body(self) -> dict:
        size = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(size) or b"{}")

    def do_POST(self) -> None:
        try:
            data = self._json_body()
            path = urlparse(self.path).path
            if path == "/v1/intake":
                self._reply(HTTPStatus.ACCEPTED, self.engine.ingest(data))
                return
            if path == "/v1/process":
                self._reply(HTTPStatus.OK, self.engine.flush_conversation(data["tenant_id"], data["channel_account_id"], data["conversation_id"]))
                return
            self._reply(HTTPStatus.NOT_FOUND, {"error": "endpoint_not_found", "send_capability": False})
        except (IntakeError, KeyError, ValueError, json.JSONDecodeError) as exc:
            self._reply(HTTPStatus.BAD_REQUEST, {"error": str(exc), "send_capability": False})

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/health":
            self._reply(HTTPStatus.OK, {"status": "ok", "mode": "send-disabled", "send_capability": False})
            return
        if path == "/v1/metrics":
            self._reply(HTTPStatus.OK, self.engine.metrics())
            return
        if path.startswith("/v1/cases/"):
            try:
                self._reply(HTTPStatus.OK, self.engine.get_case(path.rsplit("/", 1)[-1]))
            except IntakeError as exc:
                self._reply(HTTPStatus.NOT_FOUND, {"error": str(exc)})
            return
        self._reply(HTTPStatus.NOT_FOUND, {"error": "endpoint_not_found", "send_capability": False})

    def log_message(self, fmt: str, *args: object) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser(description="WakuFlow Assist Phase 6 send-disabled MVP")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--db", default="phase6/output/assist_mvp.sqlite3")
    parser.add_argument("--kb", default="phase6/config/approved_kb.json")
    args = parser.parse_args()
    secret = os.environ.get("WAKUFLOW_HMAC_SECRET", "").encode("utf-8")
    engine = AssistEngine(Path(args.db), Path(args.kb), secret=secret)
    Handler.engine = engine
    server = HTTPServer((args.host, args.port), Handler)
    print(f"WakuFlow Assist Phase 6 running at http://{args.host}:{args.port} (send-disabled)")
    try:
        server.serve_forever()
    finally:
        engine.close()


if __name__ == "__main__":
    main()
