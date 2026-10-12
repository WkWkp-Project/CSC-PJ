"""Phase 8 - staff-side operation reliability layer.

The Phase 6 ``AssistEngine`` deliberately has no send method: it writes a
routing decision and (sometimes) a handoff packet into SQLite and stops. That
is correct for the *customer* boundary - the engine must never auto-reply to a
customer. But to actually replace the person who dispatches work today, the
*staff* ticket has to leave the database and reach a human, exactly once, and
never be allowed to die unnoticed.

This layer sits on top of the engine's database and adds three guarantees,
without modifying the engine:

1.  DELIVERY - every human-bound handoff is queued in an outbox and delivered
    to a staff channel (LINE group / console / webhook) exactly once, with
    automatic retry on transient failure. Delivery is idempotent: a ticket is
    never sent twice for the same handoff.

2.  NO SILENT CLOSE - a processed inbound that produced no handoff and was not a
    clean greeting / system / empty event becomes a low-priority TRIAGE ticket.
    This closes the "case died silently" failure mode (the C22 pattern) that
    happens when the classifier is unsure (I99) and the route collapses to
    HOLD_OR_NO_ACTION.

3.  NOTHING SITS FOREVER - a watchdog escalates any delivered ticket that no
    staff member has acknowledged within an SLA window, re-nagging the channel
    with rising priority until someone picks it up.

This layer never contacts the customer. Every delivery target is a staff
destination, and every payload is PII-free (it carries the same redacted packet
the engine already produced: intents, route, risk flags, media counts - no
message text, name, phone or address).
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Any, Callable, Protocol


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Intents/flags that make a no-handoff close genuinely safe. Anything else that
# closes without a handoff is treated as a missed case and sent to triage.
_SAFE_CLOSE_FLAGS = {"E_GREETING", "E_SYSTEM"}
_EMPTY_TEXT_MARKER = "(ไม่มีข้อความลูกค้า)"

# Backoff schedule (seconds) for delivery retries, indexed by attempt number.
_RETRY_BACKOFF = [0, 30, 120, 600, 1800]

# Human-readable Thai labels for the role each ticket is dispatched to.
ROLE_LABEL = {
    "WAKUWAKU_CS": "ทีม Wakuwaku CS",
    "BRAND_APPROVER": "ทีมแบรนด์ (อนุมัติ)",
    "SECURITY_OWNER": "ทีมความปลอดภัย",
    "SALES_OWNER": "ทีมขายส่ง",
    "POLICY_OWNER": "ทีมนโยบาย",
    "TRIAGE_DESK": "โต๊ะคัดแยก (ตรวจเคสที่ระบบไม่มั่นใจ)",
}

# Human-readable Thai labels for the business intent, for the ticket title.
INTENT_LABEL = {
    "I03": "ถามข้อมูลสินค้า", "I05": "ถามจุดจำหน่าย", "I06": "ถามสต็อก/ของเข้า",
    "I07": "ขอรับไปขาย", "I11": "ของรางวัล/กิจกรรม", "I14": "ร้องเรียนคุณภาพ",
    "I15": "สอบถามงานอีเวนต์", "I16": "ลงทะเบียน/สมัคร", "I99": "ระบบไม่มั่นใจ (ต้องให้คนดู)",
}


class DeliveryError(RuntimeError):
    """Raised by a Deliverer to signal a transient failure that should retry."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _locked(method):
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# Deliverers - pluggable staff destinations. None of these touch the customer.
# ---------------------------------------------------------------------------

class Deliverer(Protocol):
    channel: str

    def deliver(self, ticket: dict[str, Any]) -> str:
        """Send one ticket to staff. Return a provider reference string.

        Raise ``DeliveryError`` for a transient failure (will be retried).
        """
        ...


class ConsoleDeliverer:
    """Default deliverer: records the ticket to an in-memory staff queue.

    Always succeeds, so it is safe as the baseline destination and in tests. In
    production this stands in for "the staff console queue".
    """

    channel = "console"

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    def deliver(self, ticket: dict[str, Any]) -> str:
        self.sent.append(ticket)
        return f"console-{len(self.sent)}"


class CallableDeliverer:
    """Adapter that delivers through an injected ``send_fn``.

    Use this for the LINE Wakuwaku group or a staff webhook: pass a function
    that takes the already-rendered, PII-free ticket text and posts it. The real
    credential lives in the caller's ``send_fn`` closure, never here.
    """

    def __init__(self, channel: str, send_fn: Callable[[dict[str, Any]], str]) -> None:
        self.channel = channel
        self._send_fn = send_fn

    def deliver(self, ticket: dict[str, Any]) -> str:
        return self._send_fn(ticket)


# ---------------------------------------------------------------------------
# The operation layer
# ---------------------------------------------------------------------------

class OpsDelivery:
    """Reliable staff-side delivery + safety net over an AssistEngine DB."""

    def __init__(self, conn: sqlite3.Connection, *, default_role: str = "TRIAGE_DESK") -> None:
        self.conn = conn
        self.conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._default_role = default_role
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS handoff_outbox (
              outbox_id TEXT PRIMARY KEY,
              dedupe_key TEXT NOT NULL UNIQUE,
              case_id TEXT NOT NULL,
              handoff_id TEXT,
              kind TEXT NOT NULL,
              assigned_role TEXT NOT NULL,
              priority TEXT NOT NULL,
              status TEXT NOT NULL,
              attempts INTEGER NOT NULL DEFAULT 0,
              escalations INTEGER NOT NULL DEFAULT 0,
              next_attempt_at TEXT NOT NULL,
              delivered_channel TEXT,
              delivered_ref TEXT,
              payload_json TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_outbox_status ON handoff_outbox(status, next_attempt_at);
            CREATE TABLE IF NOT EXISTS handoff_ack (
              outbox_id TEXT PRIMARY KEY,
              staff_id TEXT NOT NULL,
              acked_at TEXT NOT NULL,
              FOREIGN KEY(outbox_id) REFERENCES handoff_outbox(outbox_id)
            );
            """
        )
        self.conn.commit()

    # -- enqueue -----------------------------------------------------------

    @_locked
    def enqueue_from_flush(self, flush_result: dict[str, Any], *,
                           suggestion: dict[str, Any] | None = None) -> dict[str, Any]:
        """Turn one engine flush result into a staff ticket (or none).

        Pass ``suggestion`` (from SuggestionEngine.best) to carry a suggested reply
        on the ticket - mode B. It is advisory only: a human still sends it.
        Returns ``{"queued": bool, "outbox_id": str|None, "kind": str|None}``.
        Idempotent per handoff / per bundle via ``dedupe_key``.
        """
        self._pending_suggestion = suggestion
        case_id = flush_result.get("case_id")
        handoff_id = flush_result.get("handoff_id")
        classification = flush_result.get("classification") or {}
        status = flush_result.get("status")

        if flush_result.get("manual_owner_lock"):
            # A human already owns this case; the engine is intentionally quiet.
            return {"queued": False, "outbox_id": None, "kind": None}

        if handoff_id:
            role = self._role_for_case(case_id) or self._default_role
            payload = self._build_payload(
                case_id, handoff_id, classification, flush_result, kind="HANDOFF", role=role
            )
            return self._insert_outbox(
                dedupe_key=f"handoff:{handoff_id}", case_id=case_id, handoff_id=handoff_id,
                kind="HANDOFF", role=role, priority=self._priority_for(classification), payload=payload,
            )

        # No handoff. Only a clean greeting / system / empty event may close
        # silently; everything else is a missed case and goes to triage.
        if self._is_safe_silent_close(classification, status):
            return {"queued": False, "outbox_id": None, "kind": None}

        bundle_id = flush_result.get("bundle_id") or case_id
        payload = self._build_payload(
            case_id, None, classification, flush_result, kind="TRIAGE", role="TRIAGE_DESK"
        )
        return self._insert_outbox(
            dedupe_key=f"triage:{bundle_id}", case_id=case_id, handoff_id=None,
            kind="TRIAGE", role="TRIAGE_DESK", priority="LOW", payload=payload,
        )

    def _role_for_case(self, case_id: str) -> str | None:
        row = self.conn.execute(
            "SELECT assigned_role FROM handoff WHERE case_id=? ORDER BY created_at DESC LIMIT 1",
            (case_id,),
        ).fetchone()
        return row["assigned_role"] if row else None

    @staticmethod
    def _priority_for(classification: dict[str, Any]) -> str:
        flags = set(classification.get("event_flags", []))
        if {"E_SUSPECT_SPAM", "F_PERSONAL_POSSIBLE"} & flags:
            return "HIGH"
        if classification.get("primary_intent") == "I14":  # quality complaint
            return "HIGH"
        return "NORMAL"

    @staticmethod
    def _is_safe_silent_close(classification: dict[str, Any], status: str | None) -> bool:
        if status != "CLOSED":
            return False
        flags = set(classification.get("event_flags", []))
        if flags & _SAFE_CLOSE_FLAGS:
            return True
        # An empty / no-text event is safe to close; an unsure classification on
        # real text (I99 by insufficient_summary) is NOT - that is a missed case.
        if classification.get("classification_evidence") == "insufficient_summary":
            return False
        return False

    def _build_payload(
        self, case_id: str, handoff_id: str | None, classification: dict[str, Any],
        flush_result: dict[str, Any], *, kind: str, role: str,
    ) -> dict[str, Any]:
        intent = classification.get("primary_intent", "I99")
        suggestion = getattr(self, "_pending_suggestion", None)
        payload = {
            "kind": kind,
            "case_id": case_id,
            "handoff_id": handoff_id,
            "assigned_role": role,
            "role_label": ROLE_LABEL.get(role, role),
            "intent": intent,
            "intent_label": INTENT_LABEL.get(intent, intent),
            "secondary_intents": classification.get("secondary_intents", []),
            "route": classification.get("route"),
            "risk_flags": classification.get("event_flags", []),
            "message_count": flush_result.get("message_count", 0),
            "media_count": flush_result.get("media_count", 0),
            "media_completeness": flush_result.get("media_completeness"),
            "customer_send_allowed": False,  # staff ticket only - never a customer reply
        }
        if suggestion:
            # Mode B: advisory suggested reply. A human reviews and sends it.
            payload["suggested_reply"] = suggestion
            payload["has_suggestion"] = True
        return payload

    def _insert_outbox(
        self, *, dedupe_key: str, case_id: str, handoff_id: str | None,
        kind: str, role: str, priority: str, payload: dict[str, Any],
    ) -> dict[str, Any]:
        now = _utc_now()
        outbox_id = "ob-" + uuid.uuid4().hex[:16]
        try:
            self.conn.execute(
                "INSERT INTO handoff_outbox VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    outbox_id, dedupe_key, case_id, handoff_id, kind, role, priority,
                    "PENDING", 0, 0, _iso(now), None, None,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True), _iso(now), _iso(now),
                ),
            )
        except sqlite3.IntegrityError:
            self.conn.commit()
            existing = self.conn.execute(
                "SELECT outbox_id, kind FROM handoff_outbox WHERE dedupe_key=?", (dedupe_key,)
            ).fetchone()
            return {"queued": False, "outbox_id": existing["outbox_id"], "kind": existing["kind"]}
        self.conn.commit()
        return {"queued": True, "outbox_id": outbox_id, "kind": kind}

    # -- deliver -----------------------------------------------------------

    @_locked
    def deliver_pending(self, deliverer: Deliverer, *, now: datetime | None = None,
                        max_attempts: int = 5, limit: int = 50) -> dict[str, Any]:
        """Deliver due PENDING tickets. Idempotent: SENT/ACKED rows are skipped."""
        now = now or _utc_now()
        rows = self.conn.execute(
            "SELECT * FROM handoff_outbox WHERE status='PENDING' AND next_attempt_at<=? "
            "ORDER BY CASE priority WHEN 'HIGH' THEN 0 WHEN 'NORMAL' THEN 1 ELSE 2 END, created_at "
            "LIMIT ?",
            (_iso(now), limit),
        ).fetchall()
        sent = failed = retried = 0
        for row in rows:
            ticket = json.loads(row["payload_json"])
            ticket["outbox_id"] = row["outbox_id"]
            ticket["priority"] = row["priority"]
            ticket["escalation_level"] = row["escalations"]
            attempts = row["attempts"] + 1
            try:
                ref = deliverer.deliver(ticket)
            except DeliveryError:
                if attempts >= max_attempts:
                    self.conn.execute(
                        "UPDATE handoff_outbox SET status='FAILED',attempts=?,updated_at=? WHERE outbox_id=?",
                        (attempts, _iso(now), row["outbox_id"]),
                    )
                    failed += 1
                else:
                    backoff = _RETRY_BACKOFF[min(attempts, len(_RETRY_BACKOFF) - 1)]
                    nxt = now + timedelta(seconds=backoff)
                    self.conn.execute(
                        "UPDATE handoff_outbox SET attempts=?,next_attempt_at=?,updated_at=? WHERE outbox_id=?",
                        (attempts, _iso(nxt), _iso(now), row["outbox_id"]),
                    )
                    retried += 1
                continue
            self.conn.execute(
                "UPDATE handoff_outbox SET status='SENT',attempts=?,delivered_channel=?,"
                "delivered_ref=?,updated_at=? WHERE outbox_id=?",
                (attempts, deliverer.channel, str(ref), _iso(now), row["outbox_id"]),
            )
            sent += 1
        self.conn.commit()
        return {"sent": sent, "retried": retried, "failed": failed, "considered": len(rows)}

    # -- acknowledge + watchdog -------------------------------------------

    @_locked
    def acknowledge(self, outbox_id: str, staff_id: str, *, now: datetime | None = None) -> None:
        """Staff picks up a ticket. Stops escalation for that ticket."""
        now = now or _utc_now()
        cur = self.conn.execute(
            "UPDATE handoff_outbox SET status='ACKED',updated_at=? WHERE outbox_id=? AND status IN ('SENT','PENDING')",
            (_iso(now), outbox_id),
        )
        if cur.rowcount != 1:
            raise DeliveryError("outbox_not_found_or_not_ackable")
        self.conn.execute(
            "INSERT OR REPLACE INTO handoff_ack VALUES(?,?,?)",
            (outbox_id, staff_id, _iso(now)),
        )
        self.conn.commit()

    @_locked
    def sweep(self, *, sla_seconds: int = 900, now: datetime | None = None) -> dict[str, Any]:
        """Re-nag any SENT ticket unacknowledged past the SLA, with rising priority.

        A ticket that nobody picks up is the C22 failure mode; this makes it
        impossible for one to sit silently - it keeps coming back, louder.
        """
        now = now or _utc_now()
        cutoff = _iso(now - timedelta(seconds=sla_seconds))
        rows = self.conn.execute(
            "SELECT outbox_id, escalations FROM handoff_outbox WHERE status='SENT' AND updated_at<=?",
            (cutoff,),
        ).fetchall()
        for row in rows:
            self.conn.execute(
                "UPDATE handoff_outbox SET status='PENDING',priority='HIGH',escalations=?,"
                "next_attempt_at=?,updated_at=? WHERE outbox_id=?",
                (row["escalations"] + 1, _iso(now), _iso(now), row["outbox_id"]),
            )
        self.conn.commit()
        return {"escalated": len(rows)}

    # -- introspection -----------------------------------------------------

    @_locked
    def queue_stats(self) -> dict[str, Any]:
        q = self.conn.execute
        return {
            "by_status": {r[0]: r[1] for r in q("SELECT status,COUNT(*) FROM handoff_outbox GROUP BY status")},
            "by_kind": {r[0]: r[1] for r in q("SELECT kind,COUNT(*) FROM handoff_outbox GROUP BY kind")},
            "pending": q("SELECT COUNT(*) FROM handoff_outbox WHERE status='PENDING'").fetchone()[0],
            "acked": q("SELECT COUNT(*) FROM handoff_ack").fetchone()[0],
            "escalated_ever": q("SELECT COUNT(*) FROM handoff_outbox WHERE escalations>0").fetchone()[0],
        }
