"""Send a fake, correctly signed customer message to a running server.

Lets you test the whole path without a LINE or Facebook account and without
touching a real staff group: run the server with the delivery target blank
(dry-run), then this. The ticket appears in the server's log ~30 seconds later.

Facebook page (Messenger):
    set/export FB_APP_SECRET=<same value the server uses>
    python3 -m phase8.tools.simulate --channel meta "ราคาเท่าไหร่ ซื้อได้ที่ไหน"

LINE official account:
    set/export LINE_CHANNEL_SECRET=<same value the server uses>
    python3 -m phase8.tools.simulate "ราคาเท่าไหร่ ซื้อได้ที่ไหน"
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import secrets
import sys
import time
import urllib.request


def build_request(text: str, secret: str, user: str = "Usimulated1") -> tuple[bytes, str]:
    """A LINE webhook body plus its x-line-signature (base64 HMAC-SHA256)."""
    body = json.dumps({"events": [{
        "type": "message", "timestamp": int(time.time() * 1000),
        "source": {"type": "user", "userId": user},
        "message": {"id": "sim-%d" % int(time.time() * 1000), "type": "text", "text": text},
    }]}, ensure_ascii=False).encode("utf-8")
    sig = base64.b64encode(hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()).decode()
    return body, sig


def build_meta_request(text: str, app_secret: str, user: str = "FBsimulated1",
                       page_id: str = "PAGE_SIM") -> tuple[bytes, str]:
    """A Messenger webhook body plus its X-Hub-Signature-256 (hex HMAC-SHA256)."""
    body = json.dumps({"entry": [{"id": page_id, "messaging": [{
        "sender": {"id": user}, "recipient": {"id": page_id},
        "timestamp": int(time.time() * 1000),
        "message": {"mid": "sim-%d" % int(time.time() * 1000), "text": text},
    }]}]}, ensure_ascii=False).encode("utf-8")
    sig = "sha256=" + hmac.new(app_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return body, sig


CHANNELS = {
    # name: (webhook path, env var holding the secret, signature header, builder, id prefix)
    "line": ("/webhook/line", "LINE_CHANNEL_SECRET", "x-line-signature", build_request, "Usim"),
    "meta": ("/webhook/meta", "FB_APP_SECRET", "X-Hub-Signature-256", build_meta_request, "FBsim"),
}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("text")
    ap.add_argument("--channel", choices=sorted(CHANNELS), default="line",
                    help="which webhook to pretend to be (default: line)")
    ap.add_argument("--url", help="full webhook URL; built from --channel and $PORT when omitted")
    ap.add_argument("--user", default="", help="fake customer id; default is a new one per run, so each run "
                    "is a separate customer (messages from one customer within 30s merge into one case)")
    args = ap.parse_args(argv)

    path, env_var, header, build, prefix = CHANNELS[args.channel]
    secret = os.environ.get(env_var, "")
    if not secret:
        print("set %s to the same value the server uses" % env_var, file=sys.stderr)
        return 2

    url = args.url or "http://localhost:%s%s" % (os.environ.get("PORT", "8080"), path)
    body, sig = build(args.text, secret, args.user or prefix + secrets.token_hex(4))
    req = urllib.request.Request(url, body, {"Content-Type": "application/json", header: sig})
    print(urllib.request.urlopen(req, timeout=10).read().decode())
    return 0


if __name__ == "__main__":
    sys.exit(main())
