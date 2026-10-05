"""Phase 1 webhook server (standard library only - no external deps).

Endpoints:
  GET  /healthz        -> readiness JSON (which tokens are still blank)
  GET  /webhook/meta   -> Meta webhook verification (hub.challenge)
  POST /webhook/meta   -> receive Messenger events  (X-Hub-Signature-256)
  POST /webhook/line   -> receive LINE events        (x-line-signature)

A background thread flushes conversations idle >= debounce and delivers the
tickets. Credentials come from the environment (see .env.example); while blank
the server still runs, verification fails closed, and delivery is dry-run.

Run:  PYTHONPATH=. python3 -m phase8.webhook_server
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from phase8.config import Config
from phase8.pipeline import AssistPipeline

DEBOUNCE_SECONDS = 30.0
SWEEP_SECONDS = 5.0


def build_pipeline() -> AssistPipeline:
    cfg = Config.from_env()
    if not cfg.engine_ready:
        # Allow the server to boot for /healthz even before the secret is set.
        cfg.assist_hmac_secret = "DEV_PLACEHOLDER_SECRET_____________32B"
    return AssistPipeline.from_config(cfg)


class Handler(BaseHTTPRequestHandler):
    pipeline: AssistPipeline = None  # set by serve()

    def log_message(self, *a):  # quieter logs
        pass

    def _send(self, code: int, body: str = "", ctype: str = "text/plain"):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/healthz":
            self._send(200, json.dumps(self.pipeline.cfg.status(), ensure_ascii=False), "application/json")
            return
        if parsed.path == "/webhook/meta":
            params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
            challenge = self.pipeline.meta_verify_challenge(params, self.pipeline.cfg.fb_verify_token)
            if challenge is not None:
                self._send(200, challenge)
            else:
                self._send(403, "verification failed")
            return
        self._send(404, "not found")

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""
        if parsed.path == "/webhook/meta":
            sig = self.headers.get("X-Hub-Signature-256", "")
            result = self.pipeline.receive_meta(raw, sig)
        elif parsed.path == "/webhook/line":
            sig = self.headers.get("x-line-signature", "")
            result = self.pipeline.receive_line(raw, sig)
        else:
            self._send(404, "not found")
            return
        # Always 200 fast so the platform does not retry; processing already done.
        self._send(200, json.dumps(result, ensure_ascii=False), "application/json")


def _debounce_loop(pipeline: AssistPipeline, stop: threading.Event):
    while not stop.is_set():
        try:
            pipeline.flush_due(debounce_seconds=DEBOUNCE_SECONDS)
            pipeline.ops.sweep(sla_seconds=900)  # re-nag unacked tickets
        except Exception:
            pass
        stop.wait(SWEEP_SECONDS)


def serve(host: str = "0.0.0.0", port: int = 8080):
    pipeline = build_pipeline()
    Handler.pipeline = pipeline
    stop = threading.Event()
    t = threading.Thread(target=_debounce_loop, args=(pipeline, stop), daemon=True)
    t.start()
    httpd = ThreadingHTTPServer((host, port), Handler)
    print("WakuFlow Assist webhook server on %s:%d" % (host, port))
    print("status:", json.dumps(pipeline.cfg.status(), ensure_ascii=False))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        httpd.server_close()


if __name__ == "__main__":
    import os
    serve(port=int(os.environ.get("PORT", "8080")))
