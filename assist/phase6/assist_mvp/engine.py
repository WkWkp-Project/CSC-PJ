from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import threading
import uuid
from collections import Counter
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any

from phase5.classifier_v2 import classify_v2


class IntakeError(ValueError):
    pass


def _locked(method):
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapper


REQUIRED_FIELDS = {
    "tenant_id",
    "channel_account_id",
    "event_id",
    "conversation_id",
    "occurred_at",
    "direction",
}

ALLOWED_MEDIA = {"image", "audio", "video", "document"}

ROUTE_ACTION = {
    "H1_INFORMATION_INQUIRY": ("WAITING_WAKU", "H1", "WAKUWAKU_CS"),
    "H2_HUMAN_DECISION": ("WAITING_BRAND", "H2", "BRAND_APPROVER"),
    "H3_SECURITY_HOLD": ("MANUAL", "H3", "SECURITY_OWNER"),
    "SALES_OR_H2_REVIEW": ("ROUTED_SALES", "SALES", "SALES_OWNER"),
    "HOLD_OR_NO_ACTION": ("CLOSED", None, None),
    "HOLD_FOR_POLICY": ("MANUAL", "H3", "POLICY_OWNER"),
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AssistEngine:
    """Metadata-persistent, content-ephemeral decision engine.

    Customer content is held only in memory until the bundle is processed. The
    SQLite store contains routing metadata, redacted handoff excerpts and an
    HMAC digest. There is deliberately no send method.
    """

    def __init__(self, db_path: str | Path, kb_path: str | Path, secret: bytes | None = None):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if not secret or len(secret) < 32:
            raise IntakeError("external_hmac_secret_of_at_least_32_bytes_required")
        self.secret = secret
        self._lock = threading.RLock()
        self._buffers: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        self.kb_entries = self._load_kb(Path(kb_path))
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    @_locked
    def close(self) -> None:
        self.conn.close()

    def _load_kb(self, path: Path) -> list[dict[str, Any]]:
        data = json.loads(path.read_text(encoding="utf-8"))
        entries = data.get("entries", [])
        return [x for x in entries if x.get("status") == "published" and x.get("approved") is True]

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS inbound_event (
              tenant_id TEXT NOT NULL, channel_account_id TEXT NOT NULL,
              event_id TEXT NOT NULL, conversation_key TEXT NOT NULL,
              occurred_at TEXT NOT NULL, received_at TEXT NOT NULL,
              content_hmac TEXT NOT NULL, text_chars INTEGER NOT NULL,
              media_count INTEGER NOT NULL, processing_status TEXT NOT NULL,
              PRIMARY KEY (tenant_id, channel_account_id, event_id)
            );
            CREATE TABLE IF NOT EXISTS assist_case (
              case_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL,
              channel_account_id TEXT NOT NULL, conversation_key TEXT NOT NULL,
              status TEXT NOT NULL, state_version INTEGER NOT NULL,
              primary_intent TEXT, route TEXT, manual_owner TEXT,
              customer_auto_send INTEGER NOT NULL DEFAULT 0,
              opened_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS message_bundle (
              bundle_id TEXT PRIMARY KEY, case_id TEXT NOT NULL,
              message_count INTEGER NOT NULL, media_count INTEGER NOT NULL,
              completeness TEXT NOT NULL, status TEXT NOT NULL,
              opened_at TEXT NOT NULL, closed_at TEXT NOT NULL,
              FOREIGN KEY(case_id) REFERENCES assist_case(case_id)
            );
            CREATE TABLE IF NOT EXISTS handoff (
              handoff_id TEXT PRIMARY KEY, case_id TEXT NOT NULL,
              handoff_type TEXT NOT NULL, assigned_role TEXT NOT NULL,
              status TEXT NOT NULL, packet_json TEXT NOT NULL,
              created_at TEXT NOT NULL,
              FOREIGN KEY(case_id) REFERENCES assist_case(case_id)
            );
            CREATE TABLE IF NOT EXISTS telemetry (
              seq INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT NOT NULL,
              tenant_id TEXT NOT NULL, case_id TEXT, correlation_id TEXT NOT NULL,
              occurred_at TEXT NOT NULL, attributes_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS system_metric (
              metric_name TEXT PRIMARY KEY, metric_value INTEGER NOT NULL
            );
            INSERT OR IGNORE INTO system_metric(metric_name,metric_value) VALUES('duplicates_rejected',0);
            """
        )
        self.conn.commit()

    def _digest(self, text: str) -> str:
        return hmac.new(self.secret, text.encode("utf-8"), hashlib.sha256).hexdigest()

    def _emit(self, event_type: str, tenant_id: str, case_id: str | None, correlation_id: str, **attrs: Any) -> None:
        forbidden = {"text", "summary", "payload", "recipient_id", "channel_user_id"}
        safe = {k: v for k, v in attrs.items() if k not in forbidden}
        self.conn.execute(
            "INSERT INTO telemetry(event_type,tenant_id,case_id,correlation_id,occurred_at,attributes_json) VALUES(?,?,?,?,?,?)",
            (event_type, tenant_id, case_id, correlation_id, _utc_now(), json.dumps(safe, ensure_ascii=False, sort_keys=True)),
        )

    def _validate(self, event: dict[str, Any]) -> None:
        missing = sorted(REQUIRED_FIELDS - set(event))
        if missing:
            raise IntakeError(f"missing_required_fields:{','.join(missing)}")
        if event["direction"] != "inbound":
            raise IntakeError("only_inbound_events_are_allowed")
        if not isinstance(event.get("text", ""), str):
            raise IntakeError("text_must_be_string")
        media = event.get("media", [])
        if not isinstance(media, list):
            raise IntakeError("media_must_be_list")
        if not event.get("text", "").strip() and not media:
            raise IntakeError("text_or_media_required")
        for item in media:
            if not isinstance(item, dict) or item.get("type") not in ALLOWED_MEDIA:
                raise IntakeError("unsupported_media_metadata")
            if "bytes" in item and (not isinstance(item["bytes"], int) or item["bytes"] < 0):
                raise IntakeError("invalid_media_bytes")

    @_locked
    def ingest(self, event: dict[str, Any]) -> dict[str, Any]:
        self._validate(event)
        tenant = str(event["tenant_id"])
        account = str(event["channel_account_id"])
        external_conversation = str(event["conversation_id"])
        conversation_key = self._digest(f"{tenant}|{account}|{external_conversation}")[:24]
        correlation_id = "p6-" + uuid.uuid4().hex[:16]
        text = event.get("text", "")
        media = event.get("media", [])
        try:
            self.conn.execute(
                "INSERT INTO inbound_event VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    tenant,
                    account,
                    str(event["event_id"]),
                    conversation_key,
                    str(event["occurred_at"]),
                    _utc_now(),
                    self._digest(text),
                    len(text),
                    len(media),
                    "BUFFERED",
                ),
            )
        except sqlite3.IntegrityError:
            self.conn.execute("UPDATE system_metric SET metric_value=metric_value+1 WHERE metric_name='duplicates_rejected'")
            self._emit("message.duplicate_rejected", tenant, None, correlation_id, event_id=str(event["event_id"]))
            self.conn.commit()
            return {"accepted": False, "duplicate": True, "event_id": str(event["event_id"])}
        key = (tenant, account, conversation_key)
        self._buffers.setdefault(key, []).append({**event, "correlation_id": correlation_id})
        self._emit("message.received", tenant, None, correlation_id, event_id=str(event["event_id"]), media_count=len(media))
        self.conn.commit()
        return {
            "accepted": True,
            "duplicate": False,
            "event_id": str(event["event_id"]),
            "conversation_key": conversation_key,
            "buffered_message_count": len(self._buffers[key]),
            "customer_send_attempt_count": 0,
        }

    def _find_case(self, tenant: str, account: str, conversation_key: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM assist_case WHERE tenant_id=? AND channel_account_id=? AND conversation_key=? ORDER BY opened_at DESC LIMIT 1",
            (tenant, account, conversation_key),
        ).fetchone()

    @_locked
    def flush_conversation(self, tenant_id: str, channel_account_id: str, conversation_id: str) -> dict[str, Any]:
        conversation_key = self._digest(f"{tenant_id}|{channel_account_id}|{conversation_id}")[:24]
        key = (tenant_id, channel_account_id, conversation_key)
        items = self._buffers.pop(key, [])
        if not items:
            raise IntakeError("no_buffered_messages_for_conversation")
        items.sort(key=lambda x: (str(x["occurred_at"]), str(x["event_id"])))
        correlation_id = items[0]["correlation_id"]
        existing = self._find_case(tenant_id, channel_account_id, conversation_key)
        case_id = existing["case_id"] if existing else "case-" + uuid.uuid4().hex[:16]
        manual_owner = existing["manual_owner"] if existing else None
        combined_text = "\n".join(x.get("text", "") for x in items if x.get("text", "")).strip() or "(ไม่มีข้อความลูกค้า)"
        legacy = next((str(x.get("legacy_category")) for x in reversed(items) if x.get("legacy_category")), "")
        media = [m for x in items for m in x.get("media", [])]
        media_missing = sum(1 for m in media if m.get("status") in {"failed", "expired", "unsupported"})
        completeness = "partial" if media_missing else ("unknown" if media else "complete")

        # Manual ownership is a hard processing fence. New inbound metadata is
        # recorded, but classification, KB lookup, route mutation and new
        # handoff creation do not occur until an explicit release exists.
        if manual_owner:
            now = _utc_now()
            bundle_id = "bundle-" + uuid.uuid4().hex[:16]
            self.conn.execute(
                "INSERT INTO message_bundle VALUES(?,?,?,?,?,?,?,?)",
                (bundle_id, case_id, len(items), len(media), completeness, "held_manual", now, now),
            )
            event_ids = [str(x["event_id"]) for x in items]
            placeholders = ",".join("?" for _ in event_ids)
            self.conn.execute(
                f"UPDATE inbound_event SET processing_status='HELD_MANUAL' WHERE tenant_id=? AND channel_account_id=? AND event_id IN ({placeholders})",
                (tenant_id, channel_account_id, *event_ids),
            )
            self._emit("bundle.held_manual_owner", tenant_id, case_id, correlation_id, bundle_id=bundle_id, message_count=len(items), media_count=len(media), completeness=completeness)
            self.conn.commit()
            return {
                "case_id": case_id,
                "bundle_id": bundle_id,
                "status": "MANUAL",
                "classification": None,
                "kb": {"status": "not_run_manual_owner_lock", "match": False, "candidate_count": 0, "entry_ids": [], "answer_generation_enabled": False},
                "handoff_id": None,
                "message_count": len(items),
                "media_count": len(media),
                "media_completeness": completeness,
                "customer_auto_send": False,
                "provider_send_attempt_count": 0,
                "ai_api_call_count_observed": 0,
                "manual_owner_lock": True,
            }

        result = classify_v2(combined_text, legacy)
        if media:
            # Phase 6 never analyzes media bytes. Any attachment is therefore
            # unknown evidence and must be reviewed by a human.
            prior_intents = [result["primary_intent"], *result["secondary_intents"]]
            result["primary_intent"] = "I14"
            result["secondary_intents"] = [x for x in dict.fromkeys(prior_intents) if x != "I14"]
            result["route"] = "H2_HUMAN_DECISION"
            result["event_flags"] = list(dict.fromkeys([*result["event_flags"], "F_MEDIA_UNANALYZED"]))
            result["classification_evidence"] = "media_fail_closed_override"
        kb = self._retrieve_kb(result["primary_intent"], combined_text)

        if result["route"] == "KB_CANDIDATE_HOLD":
            # Approved response generation is excluded from Phase 6. Even a KB
            # match remains a human suggestion and cannot produce an outbound.
            status, handoff_type, role = "WAITING_WAKU", "H1", "WAKUWAKU_CS"
            action_reason = "kb_candidate_requires_human_review" if kb["match"] else "no_approved_kb_entry"
        else:
            status, handoff_type, role = ROUTE_ACTION.get(result["route"], ("MANUAL", "H3", "POLICY_OWNER"))
            action_reason = "route_policy"

        now = _utc_now()
        if existing:
            self.conn.execute(
                "UPDATE assist_case SET status=?,state_version=state_version+1,primary_intent=?,route=?,customer_auto_send=0,updated_at=? WHERE case_id=?",
                (status, result["primary_intent"], result["route"], now, case_id),
            )
        else:
            self.conn.execute(
                "INSERT INTO assist_case VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (case_id, tenant_id, channel_account_id, conversation_key, status, 1, result["primary_intent"], result["route"], None, 0, now, now),
            )
        bundle_id = "bundle-" + uuid.uuid4().hex[:16]
        self.conn.execute(
            "INSERT INTO message_bundle VALUES(?,?,?,?,?,?,?,?)",
            (bundle_id, case_id, len(items), len(media), completeness, "closed", now, now),
        )
        event_ids = [str(x["event_id"]) for x in items]
        placeholders = ",".join("?" for _ in event_ids)
        self.conn.execute(
            f"UPDATE inbound_event SET processing_status='PROCESSED' WHERE tenant_id=? AND channel_account_id=? AND event_id IN ({placeholders})",
            (tenant_id, channel_account_id, *event_ids),
        )

        handoff_id = None
        if handoff_type and role:
            handoff_id = "handoff-" + uuid.uuid4().hex[:16]
            packet = {
                "case_id": case_id,
                "intent": result["primary_intent"],
                "secondary_intents": result["secondary_intents"],
                "route": result["route"],
                "risk_flags": result["event_flags"],
                "reason": action_reason,
                "message_count": len(items),
                "media": {
                    "count": len(media),
                    "types": dict(Counter(x.get("type", "unknown") for x in media)),
                    "total_bytes": sum(int(x.get("bytes", 0)) for x in media),
                    "completeness": completeness,
                },
                "content_reference": "not_persisted_phase6",
                "content_persisted_in_handoff": False,
                "kb_lookup_status": kb["status"],
                "customer_send_allowed": False,
            }
            self.conn.execute(
                "INSERT INTO handoff VALUES(?,?,?,?,?,?,?)",
                (handoff_id, case_id, handoff_type, role, "OPEN", json.dumps(packet, ensure_ascii=False), now),
            )

        self._emit("bundle.closed", tenant_id, case_id, correlation_id, bundle_id=bundle_id, message_count=len(items), media_count=len(media), completeness=completeness)
        self._emit("classification.completed", tenant_id, case_id, correlation_id, classifier_version=result["classifier_version"], primary_intent=result["primary_intent"], route=result["route"], deterministic_rule_runs=1, ai_api_call_count=0, estimated_future_input_tokens=max(1, len(combined_text) // 3))
        self._emit("kb.lookup.completed", tenant_id, case_id, correlation_id, status=kb["status"], candidate_count=kb["candidate_count"])
        self._emit("routing.decided", tenant_id, case_id, correlation_id, status=status, handoff_type=handoff_type, customer_auto_send=False, provider_send_attempt_count=0)
        self.conn.commit()
        return {
            "case_id": case_id,
            "bundle_id": bundle_id,
            "status": status,
            "classification": result,
            "kb": kb,
            "handoff_id": handoff_id,
            "message_count": len(items),
            "media_count": len(media),
            "media_completeness": completeness,
            "customer_auto_send": False,
            "provider_send_attempt_count": 0,
            "ai_api_call_count_observed": 0,
        }

    def _retrieve_kb(self, intent: str, text: str) -> dict[str, Any]:
        candidates = [x for x in self.kb_entries if intent in x.get("intents", [])]
        matched = [x for x in candidates if any(k.lower() in text.lower() for k in x.get("keywords", []))]
        return {
            "status": "approved_candidate_found_human_review_required" if matched else "blocked_no_approved_entry",
            "match": bool(matched),
            "candidate_count": len(matched),
            "entry_ids": [x["id"] for x in matched],
            "answer_generation_enabled": False,
        }

    @_locked
    def set_manual_owner(self, case_id: str, owner: str) -> None:
        cur = self.conn.execute(
            "UPDATE assist_case SET manual_owner=?,status='MANUAL',state_version=state_version+1,updated_at=? WHERE case_id=?",
            (owner, _utc_now(), case_id),
        )
        if cur.rowcount != 1:
            raise IntakeError("case_not_found")
        self.conn.commit()

    @_locked
    def get_case(self, case_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM assist_case WHERE case_id=?", (case_id,)).fetchone()
        if not row:
            raise IntakeError("case_not_found")
        handoffs = [dict(x) for x in self.conn.execute("SELECT * FROM handoff WHERE case_id=? ORDER BY created_at", (case_id,))]
        for h in handoffs:
            h["packet"] = json.loads(h.pop("packet_json"))
        result = dict(row)
        result["customer_auto_send"] = bool(result["customer_auto_send"])
        result["handoffs"] = handoffs
        return result

    @_locked
    def event_processing_status(self, tenant_id: str, channel_account_id: str, event_id: str) -> str | None:
        row = self.conn.execute(
            "SELECT processing_status FROM inbound_event WHERE tenant_id=? AND channel_account_id=? AND event_id=?",
            (tenant_id, channel_account_id, event_id),
        ).fetchone()
        return row[0] if row else None

    @_locked
    def rehydrate_buffer(self, event: dict[str, Any]) -> bool:
        """Restore an accepted-but-unflushed event after a process restart."""
        self._validate(event)
        tenant = str(event["tenant_id"])
        account = str(event["channel_account_id"])
        status = self.event_processing_status(tenant, account, str(event["event_id"]))
        if status != "BUFFERED":
            return False
        conversation_key = self._digest(f"{tenant}|{account}|{event['conversation_id']}")[:24]
        key = (tenant, account, conversation_key)
        items = self._buffers.setdefault(key, [])
        if any(str(x.get("event_id")) == str(event["event_id"]) for x in items):
            return False
        items.append({**event, "correlation_id": "p6-recovery-" + uuid.uuid4().hex[:12]})
        return True

    @_locked
    def recover_case_snapshot(self, tenant_id: str, channel_account_id: str, conversation_id: str) -> dict[str, Any] | None:
        conversation_key = self._digest(f"{tenant_id}|{channel_account_id}|{conversation_id}")[:24]
        case = self._find_case(tenant_id, channel_account_id, conversation_key)
        if not case:
            return None
        bundle = self.conn.execute(
            "SELECT bundle_id,message_count,media_count,completeness,status FROM message_bundle WHERE case_id=? ORDER BY closed_at DESC LIMIT 1",
            (case["case_id"],),
        ).fetchone()
        return {
            "case_id": case["case_id"],
            "status": case["status"],
            "route": case["route"],
            "primary_intent": case["primary_intent"],
            "bundle_id": bundle["bundle_id"] if bundle else None,
            "message_count": bundle["message_count"] if bundle else 0,
            "media_count": bundle["media_count"] if bundle else 0,
            "completeness": bundle["completeness"] if bundle else "unknown",
        }

    @_locked
    def metrics(self) -> dict[str, Any]:
        q = self.conn.execute
        return {
            "inbound_events": q("SELECT COUNT(*) FROM inbound_event").fetchone()[0],
            "duplicates_rejected": q("SELECT metric_value FROM system_metric WHERE metric_name='duplicates_rejected'").fetchone()[0],
            "cases": q("SELECT COUNT(*) FROM assist_case").fetchone()[0],
            "bundles": q("SELECT COUNT(*) FROM message_bundle").fetchone()[0],
            "handoffs": q("SELECT COUNT(*) FROM handoff").fetchone()[0],
            "customer_auto_send_count": q("SELECT COUNT(*) FROM assist_case WHERE customer_auto_send != 0").fetchone()[0],
            "provider_send_attempt_count": 0,
            "route_counts": {r[0]: r[1] for r in q("SELECT route,COUNT(*) FROM assist_case GROUP BY route")},
            "state_counts": {r[0]: r[1] for r in q("SELECT status,COUNT(*) FROM assist_case GROUP BY status")},
        }
