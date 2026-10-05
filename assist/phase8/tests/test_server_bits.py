"""Tests for the debounce flush loop and Meta webhook verification."""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

from phase8.config import Config
from phase8.pipeline import AssistPipeline

ROOT = Path(__file__).resolve().parents[2]
APPROVED = str(ROOT / "phase6" / "config" / "approved_kb.json")
DRAFT = str(ROOT / "phase6" / "config" / "kb_draft_from_research.json")


def _pipe(tmp_path):
    cfg = Config(
        fb_app_secret="APPSECRET", fb_page_token="t", fb_page_id="PAGE1", fb_verify_token="VTOK",
        line_channel_secret="", line_channel_access_token="", line_target_group_id="",
        assist_hmac_secret="z" * 32, tenant_id="tulip",
        db_path=str(tmp_path / "p.db"), kb_approved_path=APPROVED, kb_draft_path=DRAFT,
    )
    return AssistPipeline.from_config(cfg)


def test_meta_challenge():
    assert AssistPipeline.meta_verify_challenge(
        {"hub.mode": "subscribe", "hub.verify_token": "VTOK", "hub.challenge": "123"}, "VTOK") == "123"
    assert AssistPipeline.meta_verify_challenge(
        {"hub.mode": "subscribe", "hub.verify_token": "WRONG", "hub.challenge": "123"}, "VTOK") is None
    assert AssistPipeline.meta_verify_challenge({}, "") is None  # unconfigured fails


def test_debounce_flush_delivers_after_window(tmp_path):
    pipe = _pipe(tmp_path)
    payload = {"entry": [{"id": "PAGE1", "messaging": [
        {"sender": {"id": "U1"}, "timestamp": 1, "message": {"mid": "m1", "text": "ขายส่งยกลัง ขั้นต่ำกี่ลัง"}},
    ]}]}
    raw = json.dumps(payload).encode("utf-8")
    sig = "sha256=" + hmac.new(b"APPSECRET", raw, hashlib.sha256).hexdigest()
    pipe.receive_meta(raw, sig, now=0.0)

    # Before the debounce window: nothing flushes.
    assert pipe.flush_due(debounce_seconds=30, now=0.0) == []
    assert len(pipe.deliverer.sent) == 0

    # After the window: the conversation flushes and a ticket is delivered.
    out = pipe.flush_due(debounce_seconds=30, now=100.0)
    assert len(out) == 1
    assert pipe.deliverer.sent, "a ticket should have been delivered (dry-run)"
    assert "เคสใหม่" in pipe.deliverer.sent[0]["text"]
