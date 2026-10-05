"""End-to-end tests for the Phase 8 staff-delivery + safety-net layer.

These run against the REAL Phase 6 AssistEngine so the guarantees are proven on
the actual decision path, not a mock.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from phase6.assist_mvp.engine import AssistEngine
from phase8.ops_delivery import (
    CallableDeliverer,
    ConsoleDeliverer,
    DeliveryError,
    OpsDelivery,
)

SECRET = b"x" * 32
KB_PATH = Path(__file__).resolve().parents[2] / "phase6" / "config" / "approved_kb.json"


def _engine(tmp_path) -> AssistEngine:
    return AssistEngine(tmp_path / "ops.db", KB_PATH, secret=SECRET)


def _event(event_id: str, conversation_id: str, text: str, **extra):
    base = {
        "tenant_id": "tulip",
        "channel_account_id": "fb-page-1",
        "event_id": event_id,
        "conversation_id": conversation_id,
        "occurred_at": "2026-01-01T00:00:00Z",
        "direction": "inbound",
        "text": text,
    }
    base.update(extra)
    return base


def _run(engine: AssistEngine, event: dict):
    engine.ingest(event)
    return engine.flush_conversation(
        event["tenant_id"], event["channel_account_id"], event["conversation_id"]
    )


# -- Guarantee 1: delivery, exactly once, with retry -----------------------

def test_handoff_is_delivered_once(tmp_path):
    engine = _engine(tmp_path)
    ops = OpsDelivery(engine.conn)
    # A wholesale enquiry -> SALES handoff.
    res = _run(engine, _event("e1", "c1", "สนใจรับไปขาย เปิดร้าน ขายส่ง"))
    assert res["handoff_id"] is not None

    enq = ops.enqueue_from_flush(res)
    assert enq["queued"] is True and enq["kind"] == "HANDOFF"

    console = ConsoleDeliverer()
    out = ops.deliver_pending(console)
    assert out["sent"] == 1
    assert len(console.sent) == 1
    assert console.sent[0]["customer_send_allowed"] is False  # staff-only

    # Re-running delivery must NOT send again (idempotent).
    out2 = ops.deliver_pending(console)
    assert out2["sent"] == 0
    assert len(console.sent) == 1

    # Re-enqueue of the same handoff must dedupe.
    enq2 = ops.enqueue_from_flush(res)
    assert enq2["queued"] is False


def test_transient_failure_retries_then_succeeds(tmp_path):
    engine = _engine(tmp_path)
    ops = OpsDelivery(engine.conn)
    res = _run(engine, _event("e1", "c1", "สนใจรับไปขาย ขายส่ง"))
    ops.enqueue_from_flush(res)

    calls = {"n": 0}

    def flaky(ticket):
        calls["n"] += 1
        if calls["n"] == 1:
            raise DeliveryError("boom")
        return "ok-ref"

    deliverer = CallableDeliverer("line_group", flaky)
    t0 = datetime.now(timezone.utc)

    first = ops.deliver_pending(deliverer, now=t0)
    assert first["retried"] == 1 and first["sent"] == 0

    # Too soon -> still backing off.
    assert ops.deliver_pending(deliverer, now=t0 + timedelta(seconds=5))["sent"] == 0

    # After backoff window -> delivered.
    later = ops.deliver_pending(deliverer, now=t0 + timedelta(seconds=120))
    assert later["sent"] == 1
    stats = ops.queue_stats()
    assert stats["by_status"].get("SENT") == 1


# -- Guarantee 2: no silent close (the C22 pattern) ------------------------

def test_unsure_message_becomes_triage_not_silent_close(tmp_path):
    engine = _engine(tmp_path)
    ops = OpsDelivery(engine.conn)
    # Real text the keyword rules cannot classify -> I99 / HOLD_OR_NO_ACTION,
    # which the engine CLOSES with no handoff. The safety net must catch it.
    res = _run(engine, _event("e1", "c1", "อยากทราบรายละเอียดหน่อยนะคะ ขอบคุณค่ะ"))
    assert res["handoff_id"] is None
    assert res["status"] == "CLOSED"

    enq = ops.enqueue_from_flush(res)
    assert enq["queued"] is True
    assert enq["kind"] == "TRIAGE"

    console = ConsoleDeliverer()
    ops.deliver_pending(console)
    assert console.sent[0]["intent_label"] == "ระบบไม่มั่นใจ (ต้องให้คนดู)"
    assert console.sent[0]["assigned_role"] == "TRIAGE_DESK"


def test_pure_greeting_is_allowed_to_close_silently(tmp_path):
    engine = _engine(tmp_path)
    ops = OpsDelivery(engine.conn)
    res = _run(engine, _event("e1", "c1", "สวัสดีค่ะ"))
    assert res["handoff_id"] is None
    enq = ops.enqueue_from_flush(res)
    assert enq["queued"] is False  # a greeting is not a missed case


# -- Guarantee 3: nothing sits forever -------------------------------------

def test_unacked_ticket_is_escalated_then_an_ack_stops_it(tmp_path):
    engine = _engine(tmp_path)
    ops = OpsDelivery(engine.conn)
    res = _run(engine, _event("e1", "c1", "สนใจรับไปขาย ขายส่ง"))
    ops.enqueue_from_flush(res)

    console = ConsoleDeliverer()
    t0 = datetime.now(timezone.utc)
    ops.deliver_pending(console, now=t0)
    assert len(console.sent) == 1

    # Before SLA -> no escalation.
    assert ops.sweep(sla_seconds=900, now=t0 + timedelta(seconds=300))["escalated"] == 0

    # Past SLA with no ack -> escalates and re-nags.
    assert ops.sweep(sla_seconds=900, now=t0 + timedelta(seconds=1000))["escalated"] == 1
    ops.deliver_pending(console, now=t0 + timedelta(seconds=1001))
    assert len(console.sent) == 2  # re-nagged
    assert console.sent[1]["priority"] == "HIGH"
    assert console.sent[1]["escalation_level"] == 1

    # Staff acknowledges -> no further escalation ever.
    outbox_id = console.sent[1]["outbox_id"]
    ops.acknowledge(outbox_id, "staff-A", now=t0 + timedelta(seconds=1100))
    assert ops.sweep(sla_seconds=900, now=t0 + timedelta(seconds=5000))["escalated"] == 0
    assert ops.queue_stats()["acked"] == 1


def test_quality_complaint_is_high_priority(tmp_path):
    engine = _engine(tmp_path)
    ops = OpsDelivery(engine.conn)
    res = _run(engine, _event("e1", "c1", "ร้องเรียนคุณภาพ สินค้าเสีย รสชาติผิดปกติ"))
    ops.enqueue_from_flush(res)
    row = ops.conn.execute("SELECT priority FROM handoff_outbox").fetchone()
    assert row["priority"] == "HIGH"


def test_manual_owner_lock_is_not_queued(tmp_path):
    engine = _engine(tmp_path)
    ops = OpsDelivery(engine.conn)
    res = _run(engine, _event("e1", "c1", "สนใจรับไปขาย ขายส่ง"))
    engine.set_manual_owner(res["case_id"], "human-1")
    # A follow-up message while a human owns the case is held, not re-queued.
    res2 = _run(engine, _event("e2", "c1", "มีคำถามเพิ่มค่ะ"))
    assert res2.get("manual_owner_lock") is True
    assert ops.enqueue_from_flush(res2)["queued"] is False
