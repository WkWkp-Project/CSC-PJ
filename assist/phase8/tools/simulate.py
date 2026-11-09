"""Send a fake, correctly signed LINE customer message to a running server.

Lets you test the whole path without a LINE account and without touching the
real staff group: run the server with the LINE token/target blank (dry-run), then
this. The ticket appears in the server's log about 30 seconds later.

    export LINE_CHANNEL_SECRET=<same value the server uses>
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
    body = json.dumps({"events": [{
        "type": "message", "timestamp": int(time.time() * 1000),
        "source": {"type": "user", "userId": user},
        "message": {"id": "sim-%d" % int(time.time() * 1000), "type": "text", "text": text},
    }]}, ensure_ascii=False).encode("utf-8")
    sig = base64.b64encode(hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()).decode()
    return body, sig


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("text")
    ap.add_argument("--url", default="http://localhost:%s/webhook/line" % os.environ.get("PORT", "8080"))
    ap.add_argument("--user", default="", help="fake customer id; default is a new one per run, so each run "
                    "is a separate customer (messages from one customer within 30s are merged into one case)")
    args = ap.parse_args(argv)
    secret = os.environ.get("LINE_CHANNEL_SECRET", "")
    if not secret:
        print("set LINE_CHANNEL_SECRET to the same value the server uses", file=sys.stderr)
        return 2
    body, sig = build_request(args.text, secret, args.user or "Usim" + secrets.token_hex(4))
    req = urllib.request.Request(args.url, body, {"Content-Type": "application/json", "x-line-signature": sig})
    print(urllib.request.urlopen(req, timeout=10).read().decode())
    return 0


if __name__ == "__main__":
    sys.exit(main())
