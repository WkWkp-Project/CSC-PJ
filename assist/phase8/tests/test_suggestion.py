"""Tests for mode B - KB-driven reply suggestion, and its ticket integration."""

from __future__ import annotations

from pathlib import Path

from phase5.classifier_v2 import classify_v2
from phase6.assist_mvp.engine import AssistEngine
from phase8.ops_delivery import ConsoleDeliverer, OpsDelivery
from phase8.suggestion import SuggestionEngine

SECRET = b"x" * 32
KB_PATH = Path(__file__).resolve().parents[2] / "phase6" / "config" / "approved_kb.json"
DRAFT_PATH = Path(__file__).resolve().parents[2] / "phase6" / "config" / "kb_draft_from_research.json"


def _approved(intent, keywords, answer, mode="self_answer_candidate"):
    return {
        "id": f"appr-{intent}", "intents": [intent], "keywords": keywords,
        "answer": answer, "answer_mode": mode, "status": "published", "approved": True,
    }


# -- draft-only KB: suggestions exist but are never send-ready ---------------

def test_draft_only_is_not_ready_to_send():
    eng = SuggestionEngine.from_files(KB_PATH, DRAFT_PATH)  # approved empty + drafts
    best = eng.best("I05", "ซื้อที่ไหนได้บ้าง มีช่องทางไหน")
    assert best is not None
    assert best["is_placeholder_draft"] is True
    assert best["ready_to_send"] is False
    assert best["auto_sendable"] is False
    assert best["requires_human_review"] is True


# -- a filled, approved self-answer entry becomes send-ready & auto-capable --

def test_filled_approved_self_answer_is_ready():
    eng = SuggestionEngine([
        _approved("I05", ["ซื้อที่ไหน", "ช่องทาง"], "สั่งซื้อได้ที่ Shopee: example.com ค่ะ"),
    ])
    best = eng.best("I05", "ซื้อที่ไหนได้บ้าง มีช่องทางไหน")
    assert best["ready_to_send"] is True
    assert best["auto_sendable"] is True
    assert best["requires_human_review"] is False
    assert "Shopee" in best["suggested_text"]


# -- sensitive intents never auto-sendable, even when filled & approved ------

def test_sensitive_intent_never_auto_sendable():
    eng = SuggestionEngine([
        _approved("I14", ["ร้องเรียนคุณภาพ"], "เรารับเรื่องแล้วค่ะ จะติดต่อกลับ", mode="human_assist"),
    ])
    best = eng.best("I14", "ขอร้องเรียนคุณภาพ")
    assert best["ready_to_send"] is True          # it is approved + filled
    assert best["auto_sendable"] is False          # but must never auto-send
    assert best["requires_human_review"] is True


# -- confidence ranks by keyword overlap ------------------------------------

def test_hidden_risk_word_blocks_auto_send():
    # Harmless-looking price question that hides a health signal. Even with a
    # filled, approved self-answer entry, auto-send must be blocked.
    eng = SuggestionEngine([_approved("I04", ["ราคา"], "ราคา 120 บาทค่ะ")])
    best = eng.best("I04", "กินแล้วไม่สบายท้อง ตัวนี้ราคาเท่าไหร่")
    assert best["ready_to_send"] is True
    assert best["auto_sendable"] is False
    assert best["requires_human_review"] is True
    assert "ไม่สบาย" in best["risk_sentinel_hits"]
    assert best["auto_block_reason"] == "risk_sentinel_present"


def test_clean_question_still_auto_sendable():
    eng = SuggestionEngine([_approved("I04", ["ราคา"], "ราคา 120 บาทค่ะ")])
    best = eng.best("I04", "ราคาเท่าไหร่คะ")
    assert best["auto_sendable"] is True
    assert best["risk_sentinel_hits"] == []


def test_confidence_and_ranking():
    eng = SuggestionEngine([
        _approved("I04", ["ราคา"], "A"),
        _approved("I04", ["ราคา", "ค่าส่ง"], "B"),
    ])
    out = eng.suggest("I04", "ราคาเท่าไหร่ ค่าส่งกี่บาท")
    assert out[0]["suggested_text"] == "B"         # more keyword matches ranks first
    assert out[0]["confidence"] == "high"


# -- integration: suggestion rides on the staff ticket (mode B) -------------

def test_suggestion_attached_to_ticket(tmp_path):
    engine = AssistEngine(tmp_path / "s.db", KB_PATH, secret=SECRET)
    ops = OpsDelivery(engine.conn)
    sugg_engine = SuggestionEngine([
        _approved("I05", ["ซื้อที่ไหน", "ช่องทาง"], "สั่งซื้อที่ Shopee ค่ะ"),
    ])

    text = "ซื้อที่ไหนได้บ้าง มีช่องทางไหน"
    engine.ingest({
        "tenant_id": "tulip", "channel_account_id": "fb", "event_id": "e1",
        "conversation_id": "c1", "occurred_at": "2026-01-01T00:00:00Z",
        "direction": "inbound", "text": text,
    })
    res = engine.flush_conversation("tulip", "fb", "c1")

    # Runner computes the suggestion at flush time and passes it in.
    cls = classify_v2(text, "")
    suggestion = sugg_engine.best(cls["primary_intent"], text)
    ops.enqueue_from_flush(res, suggestion=suggestion)

    console = ConsoleDeliverer()
    ops.deliver_pending(console)
    ticket = console.sent[0]
    assert ticket["has_suggestion"] is True
    assert "Shopee" in ticket["suggested_reply"]["suggested_text"]
    assert ticket["customer_send_allowed"] is False  # still staff-only; human sends
