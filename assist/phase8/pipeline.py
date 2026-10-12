"""Phase 1 pipeline: receive -> read -> store -> classify (split work) -> ticket.

Ties together the existing engine + the Phase 8 delivery/suggestion layers. It
does NOT reply to the customer; its output is a staff ticket delivered to the
LINE group. Credentials come from Config; while blank, signature checks fail
closed and delivery runs dry.
"""

from __future__ import annotations

import json
import time
from typing import Any

from phase5.classifier_v2 import classify_v2
from phase6.assist_mvp.engine import AssistEngine
from phase8.config import Config
from phase8.line_deliverer import LineGroupDeliverer
from phase8.ops_delivery import OpsDelivery
from phase8.signatures import verify_line, verify_meta
from phase8.suggestion import SuggestionEngine


# ---- webhook payload -> engine event (the fields the engine REQUIRES) ------

def normalize_meta(payload: dict[str, Any], tenant_id: str) -> list[dict[str, Any]]:
    events = []
    for entry in payload.get("entry", []):
        page_id = str(entry.get("id", ""))
        for m in entry.get("messaging", []):
            msg = m.get("message", {})
            if not msg or msg.get("is_echo"):
                continue  # skip our own / non-message events
            events.append({
                "tenant_id": tenant_id,
                "channel_account_id": "meta:%s" % page_id,
                "event_id": str(msg.get("mid", "")),
                "conversation_id": str(m.get("sender", {}).get("id", "")),
                "occurred_at": str(m.get("timestamp", "")),
                "direction": "inbound",
                "text": msg.get("text", "") or "",
                "media": [{"type": a.get("type", "document")}
                          for a in msg.get("attachments", []) if isinstance(a, dict)],
            })
    return events


def normalize_line(payload: dict[str, Any], tenant_id: str) -> list[dict[str, Any]]:
    events = []
    for e in payload.get("events", []):
        if e.get("type") != "message":
            continue
        msg = e.get("message", {})
        src = e.get("source", {})
        conv = src.get("groupId") or src.get("roomId") or src.get("userId") or ""
        mtype = msg.get("type", "text")
        events.append({
            "tenant_id": tenant_id,
            "channel_account_id": "line:%s" % str(src.get("type", "")),
            "event_id": str(msg.get("id", "")),
            "conversation_id": str(conv),
            "occurred_at": str(e.get("timestamp", "")),
            "direction": "inbound",
            "text": msg.get("text", "") if mtype == "text" else "",
            "media": [] if mtype == "text" else [{"type": mtype if mtype in
                     {"image", "audio", "video"} else "document"}],
        })
    return events


class AssistPipeline:
    def __init__(self, cfg: Config, engine: AssistEngine, ops: OpsDelivery,
                 suggestions: SuggestionEngine, deliverer):
        self.cfg = cfg
        self.engine = engine
        self.ops = ops
        self.suggestions = suggestions
        self.deliverer = deliverer
        # pending[(account, conversation_id)] = {"last": monotonic, "texts": [...]}
        # tracks debounce timing + the in-memory text used for reply suggestion.
        self.pending: dict[tuple[str, str], dict[str, Any]] = {}

    @classmethod
    def from_config(cls, cfg: Config, deliverer=None) -> "AssistPipeline":
        engine = AssistEngine(cfg.db_path, cfg.kb_approved_path,
                              secret=cfg.assist_hmac_secret.encode("utf-8"))
        ops = OpsDelivery(engine.conn)
        suggestions = SuggestionEngine.from_files(cfg.kb_approved_path, cfg.kb_draft_path)
        deliverer = deliverer or LineGroupDeliverer(cfg.line_channel_access_token, cfg.line_target_group_id)
        return cls(cfg, engine, ops, suggestions, deliverer)

    # ---- receive ----
    def receive_meta(self, raw_body: bytes, signature_header: str, *, now: float | None = None) -> dict[str, Any]:
        if not verify_meta(raw_body, signature_header, self.cfg.fb_app_secret):
            return {"accepted": False, "reason": "bad_or_unconfigured_signature"}
        payload = json.loads(raw_body.decode("utf-8"))
        return self._ingest_all(normalize_meta(payload, self.cfg.tenant_id), now=now)

    def receive_line(self, raw_body: bytes, signature_header: str, *, now: float | None = None) -> dict[str, Any]:
        if not verify_line(raw_body, signature_header, self.cfg.line_channel_secret):
            return {"accepted": False, "reason": "bad_or_unconfigured_signature"}
        payload = json.loads(raw_body.decode("utf-8"))
        return self._ingest_all(normalize_line(payload, self.cfg.tenant_id), now=now)

    def _ingest_all(self, events: list[dict[str, Any]], *, now: float | None = None) -> dict[str, Any]:
        now = now if now is not None else time.monotonic()
        n = 0
        for ev in events:
            if not ev.get("text") and not ev.get("media"):
                continue
            try:
                self.engine.ingest(ev)
            except Exception:
                continue
            key = (ev["channel_account_id"], ev["conversation_id"])
            slot = self.pending.setdefault(key, {"last": now, "texts": []})
            slot["last"] = now
            if ev.get("text"):
                slot["texts"].append(ev["text"])
            n += 1
        return {"accepted": True, "ingested": n}

    # ---- debounce: flush conversations idle >= window, then deliver -------
    def flush_due(self, *, debounce_seconds: float = 30.0, now: float | None = None) -> list[dict[str, Any]]:
        now = now if now is not None else time.monotonic()
        due = [k for k, v in self.pending.items() if now - v["last"] >= debounce_seconds]
        out = []
        for key in due:
            account, conversation_id = key
            slot = self.pending.pop(key)
            text = "\n".join(slot["texts"])
            try:
                out.append(self.flush_and_deliver_with_text(account, conversation_id, text))
            except Exception as exc:  # a flush with no buffer, etc.
                out.append({"key": key, "error": str(exc)})
        return out

    @staticmethod
    def meta_verify_challenge(params: dict[str, str], verify_token: str) -> str | None:
        """Answer Meta's GET webhook verification. Returns the challenge or None."""
        if (params.get("hub.mode") == "subscribe"
                and verify_token and params.get("hub.verify_token") == verify_token):
            return params.get("hub.challenge")
        return None

    # ---- flush (called by the debounce scheduler) -> ticket + deliver ----
    def flush_and_deliver(self, channel_account_id: str, conversation_id: str) -> dict[str, Any]:
        res = self.engine.flush_conversation(self.cfg.tenant_id, channel_account_id, conversation_id)
        suggestion = None
        cls = res.get("classification")
        if cls and cls.get("primary_intent"):
            # Suggestion needs the message text; the engine is content-ephemeral,
            # so a real runner passes the combined text here. Omitted => route-only.
            pass
        enq = self.ops.enqueue_from_flush(res, suggestion=suggestion)
        delivered = self.ops.deliver_pending(self.deliverer)
        return {"flush": res.get("status"), "enqueue": enq, "delivered": delivered}

    def flush_and_deliver_with_text(self, channel_account_id: str, conversation_id: str,
                                    text: str) -> dict[str, Any]:
        """Same, but compute a reply suggestion from the (in-memory) text."""
        res = self.engine.flush_conversation(self.cfg.tenant_id, channel_account_id, conversation_id)
        suggestion = None
        cls = res.get("classification")
        if cls and cls.get("primary_intent"):
            suggestion = self.suggestions.best(cls["primary_intent"], text)
        self.ops.enqueue_from_flush(res, suggestion=suggestion)
        return {"flush": res.get("status"), "delivered": self.ops.deliver_pending(self.deliverer)}
