"""Tell the team in LINE when WakuFlow stops answering (and when it is back).

Run it every minute from cron on the same server:

    * * * * * cd /opt/wakuflow && set -a && . /etc/wakuflow.env && set +a && \
        PYTHONPATH=. python3 -m phase8.tools.watchdog --url http://127.0.0.1:8080/healthz

It checks /healthz, and only speaks on a CHANGE (down after N misses in a row,
then recovered), so it never spams the group. It posts with the same bot and
group as the tickets (LINE_CHANNEL_ACCESS_TOKEN / LINE_TARGET_GROUP_ID).

Limit: it runs on the server it watches, so it cannot report that the whole
server or its network is down. For that, also point a free outside uptime
monitor at the public /healthz URL.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Callable

PUSH_URL = "https://api.line.me/v2/bot/message/push"


def check(url: str, timeout: float = 5.0) -> tuple[bool, str]:
    """(healthy?, reason). Healthy = HTTP 200, JSON, engine_ready true."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 (operator-chosen URL)
            body = resp.read().decode("utf-8", "replace")
            if resp.status != 200:
                return False, "HTTP %s" % resp.status
        data = json.loads(body)
    except Exception as exc:  # network error, timeout, bad JSON ...
        return False, "%s: %s" % (type(exc).__name__, exc)
    if not data.get("engine_ready"):
        return False, "engine_ready is false"
    return True, "ok"


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text("utf-8"))
    except Exception:
        return {"status": "up", "misses": 0, "down_since": None}


def run_once(url: str, state_path: str | Path, notify: Callable[[str], None], *,
             failures: int = 2, now: datetime | None = None,
             probe: Callable[[str], tuple[bool, str]] = check) -> str:
    """One check. Returns 'up', 'down', 'newly_down' or 'recovered'."""
    state_path = Path(state_path)
    state = _load(state_path)
    stamp = (now or datetime.now()).strftime("%d/%m %H:%M")
    ok, reason = probe(url)
    outcome = "up"
    if ok:
        if state["status"] == "down":
            notify("✅ ระบบ WakuFlow กลับมาทำงานแล้ว (%s) ล่มตั้งแต่ %s" % (stamp, state.get("down_since") or "-"))
            outcome = "recovered"
        state = {"status": "up", "misses": 0, "down_since": None}
    else:
        state["misses"] = int(state.get("misses", 0)) + 1
        outcome = "down" if state["status"] == "down" else "up"
        if state["status"] == "up" and state["misses"] >= failures:
            state["status"], state["down_since"] = "down", stamp
            notify("⚠️ ระบบ WakuFlow ไม่ตอบสนอง (%s) สาเหตุ: %s\nใบแจ้งงานจะไม่เข้ากลุ่มจนกว่าจะแก้" % (stamp, reason))
            outcome = "newly_down"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state), "utf-8")
    return outcome


def line_notifier(token: str, group_id: str, post=None) -> Callable[[str], None]:
    def _post(url: str, body: bytes, headers: dict) -> None:
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        urllib.request.urlopen(req, timeout=10).read()  # noqa: S310 (fixed LINE host)

    send = post or _post

    def notify(text: str) -> None:
        if not (token and group_id):
            print("[watchdog] LINE not configured, would say: %s" % text, flush=True)
            return
        body = json.dumps({"to": group_id, "messages": [{"type": "text", "text": text}]}, ensure_ascii=False).encode("utf-8")
        send(PUSH_URL, body, {"Content-Type": "application/json", "Authorization": "Bearer " + token})

    return notify


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://127.0.0.1:%s/healthz" % os.environ.get("PORT", "8080"))
    ap.add_argument("--state", default="/tmp/wakuflow-watchdog.json", help="file remembering up/down")
    ap.add_argument("--failures", type=int, default=2, help="misses in a row before alerting (default 2)")
    args = ap.parse_args(argv)
    notify = line_notifier(os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", ""), os.environ.get("LINE_TARGET_GROUP_ID", ""))
    try:
        outcome = run_once(args.url, args.state, notify, failures=args.failures)
    except Exception as exc:  # a failed alert must be visible in cron mail/logs
        print("watchdog error: %s" % exc, file=sys.stderr)
        return 1
    print(outcome)
    return 0


if __name__ == "__main__":
    sys.exit(main())
