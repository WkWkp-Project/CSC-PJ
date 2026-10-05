"""Deliver a staff ticket into the LINE Wakuwaku group.

While LINE_CHANNEL_ACCESS_TOKEN / LINE_TARGET_GROUP_ID are blank, this runs in
DRY-RUN: it renders the ticket and records it instead of calling LINE, so the
whole pipeline is testable with no credentials. Fill the two values and it posts
for real - no code change.

This sends to STAFF (a LINE group the team owns), never to the customer.
"""

from __future__ import annotations

import json
import urllib.request
from typing import Any, Callable

PUSH_URL = "https://api.line.me/v2/bot/message/push"

PRIORITY_ICON = {"HIGH": "🔴", "NORMAL": "🟡", "LOW": "⚪"}


def render_ticket(ticket: dict[str, Any]) -> str:
    """Render the PII-free ticket as the message the team sees in LINE."""
    p = ticket
    lines = [
        "%s เคสใหม่ #%s" % (PRIORITY_ICON.get(p.get("priority", "NORMAL"), "🟡"),
                            (p.get("case_id") or "")[-6:].upper()),
        "━━━━━━━━━━",
        "หมวด: %s (%s)" % (p.get("intent_label", "-"), p.get("intent", "-")),
        "ส่งให้: 👉 %s" % p.get("role_label", p.get("assigned_role", "-")),
    ]
    if p.get("media_count"):
        lines.append("📎 มีไฟล์แนบ %d" % p["media_count"])
    sug = p.get("suggested_reply")
    if sug and sug.get("suggested_text"):
        tag = "✅ กดส่งได้" if sug.get("ready_to_send") and not sug.get("requires_human_review") else "✍️ ตรวจก่อนส่ง"
        lines += ["─ ร่างคำตอบ (%s) ─" % tag, sug["suggested_text"]]
        if sug.get("risk_sentinel_hits"):
            lines.append("⚠️ พบคำเสี่ยง: %s" % ", ".join(sug["risk_sentinel_hits"]))
    lines += ["━━━━━━━━━━", "เปิดแชทตอบลูกค้าในช่องทางเดิม"]
    return "\n".join(lines)


class LineGroupDeliverer:
    channel = "line_group"

    def __init__(self, access_token: str = "", target_id: str = "", *,
                 dry_run: bool | None = None,
                 http_post: Callable[[str, bytes, dict], Any] | None = None):
        self.access_token = access_token
        self.target_id = target_id
        self.dry_run = (not (access_token and target_id)) if dry_run is None else dry_run
        self._http_post = http_post or self._default_post
        self.sent: list[dict[str, Any]] = []  # dry-run record / audit

    def _default_post(self, url: str, body: bytes, headers: dict) -> str:
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 (fixed LINE host)
            return "line-%s" % resp.status

    def deliver(self, ticket: dict[str, Any]) -> str:
        text = render_ticket(ticket)
        record = {"to": self.target_id or "(unset)", "text": text, "outbox_id": ticket.get("outbox_id")}
        if self.dry_run:
            self.sent.append(record)
            return "dryrun-%d" % len(self.sent)
        payload = json.dumps({
            "to": self.target_id,
            "messages": [{"type": "text", "text": text[:4900]}],
        }).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer %s" % self.access_token,
        }
        self.sent.append(record)
        return self._http_post(PUSH_URL, payload, headers)
