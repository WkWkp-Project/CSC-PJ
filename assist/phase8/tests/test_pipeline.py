"""Phase 1 structure tests: works with blank tokens (dry-run) and with fake creds."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from pathlib import Path

from phase8.config import Config
from phase8.line_deliverer import LineGroupDeliverer, render_ticket
from phase8.pipeline import AssistPipeline, normalize_line, normalize_meta
from phase8.signatures import verify_line, verify_meta

ROOT = Path(__file__).resolve().parents[2]
APPROVED = str(ROOT / "phase6" / "config" / "approved_kb.json")
DRAFT = str(ROOT / "phase6" / "config" / "kb_draft_from_research.json")


def _cfg(tmp_path, **over) -> Config:
    base = dict(
        fb_app_secret="", fb_page_token="", fb_page_id="", fb_verify_token="",
        line_channel_secret="", line_channel_access_token="", line_target_group_id="",
        assist_hmac_secret="y" * 32, tenant_id="tulip",
        db_path=str(tmp_path / "p.db"), kb_approved_path=APPROVED, kb_draft_path=DRAFT,
    )
    base.update(over)
    return Config(**base)


# -- readiness with blanks ---------------------------------------------------

def test_blank_config_reports_not_ready():
    cfg = _cfg(Path("/tmp"))
    st = cfg.status()
    assert st["meta_ready"] is False
    assert st["line_ready"] is False
    assert st["can_go_live_phase1"] is False
    assert "FB_APP_SECRET" in cfg.missing()["facebook"]


def test_filled_config_reports_ready():
    cfg = _cfg(Path("/tmp"), fb_app_secret="s", fb_page_token="t", fb_page_id="1",
               fb_verify_token="v", line_channel_access_token="la", line_target_group_id="G1")
    st = cfg.status()
    assert st["meta_ready"] is True
    assert st["delivery_ready"] is True
    assert st["can_go_live_phase1"] is True


# -- signatures fail closed when unconfigured --------------------------------

def test_signatures_fail_closed_and_roundtrip():
    body = b'{"hello":"world"}'
    assert verify_meta(body, "sha256=deadbeef", "") is False   # no secret
    assert verify_line(body, "x", "") is False
    meta_sig = "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    assert verify_meta(body, meta_sig, "secret") is True
    line_sig = base64.b64encode(hmac.new(b"cs", body, hashlib.sha256).digest()).decode()
    assert verify_line(body, line_sig, "cs") is True


# -- deliverer dry-run with blank token --------------------------------------

def test_line_deliverer_dry_run():
    d = LineGroupDeliverer("", "")  # no token => dry-run
    assert d.dry_run is True
    ref = d.deliver({"case_id": "case-abcdef123456", "intent": "I04",
                     "intent_label": "ราคา", "role_label": "ทีม CS", "priority": "NORMAL"})
    assert ref.startswith("dryrun-")
    assert "เคสใหม่" in d.sent[0]["text"]


def test_line_deliverer_real_post_uses_injected_http():
    calls = {}
    def fake_post(url, body, headers):
        calls["url"] = url
        calls["auth"] = headers["Authorization"]
        return "line-200"
    d = LineGroupDeliverer("TOKEN", "G123", http_post=fake_post)
    assert d.dry_run is False
    ref = d.deliver({"case_id": "c1", "intent": "I04", "priority": "HIGH"})
    assert ref == "line-200"
    assert calls["url"].endswith("/message/push")
    assert calls["auth"] == "Bearer TOKEN"


# -- webhook normalizers -----------------------------------------------------

def test_normalize_meta():
    payload = {"entry": [{"id": "PAGE1", "messaging": [
        {"sender": {"id": "U9"}, "timestamp": 123, "message": {"mid": "m1", "text": "ราคาเท่าไหร่"}},
    ]}]}
    evs = normalize_meta(payload, "tulip")
    assert len(evs) == 1 and evs[0]["text"] == "ราคาเท่าไหร่" and evs[0]["direction"] == "inbound"


def test_normalize_line():
    payload = {"events": [
        {"type": "message", "timestamp": 1, "source": {"type": "user", "userId": "U1"},
         "message": {"id": "m1", "type": "text", "text": "ซื้อที่ไหน"}},
    ]}
    evs = normalize_line(payload, "tulip")
    assert evs[0]["text"] == "ซื้อที่ไหน"


# -- end to end with fake creds: webhook -> ticket delivered -----------------

def test_end_to_end_meta_to_ticket(tmp_path):
    cfg = _cfg(tmp_path, fb_app_secret="APPSECRET", fb_page_token="t", fb_page_id="PAGE1",
               fb_verify_token="v")
    pipe = AssistPipeline.from_config(cfg)  # deliverer dry-run (no LINE token)

    payload = {"entry": [{"id": "PAGE1", "messaging": [
        {"sender": {"id": "U9"}, "timestamp": 123,
         "message": {"mid": "m1", "text": "สนใจรับไปขาย เปิดร้าน ขายส่ง"}},
    ]}]}
    raw = json.dumps(payload).encode("utf-8")
    sig = "sha256=" + hmac.new(b"APPSECRET", raw, hashlib.sha256).hexdigest()

    recv = pipe.receive_meta(raw, sig)
    assert recv == {"accepted": True, "ingested": 1}

    out = pipe.flush_and_deliver_with_text("meta:PAGE1", "U9", "สนใจรับไปขาย เปิดร้าน ขายส่ง")
    assert out["delivered"]["sent"] == 1
    assert pipe.deliverer.sent[0]["text"].startswith("🟡 เคสใหม่") or "เคสใหม่" in pipe.deliverer.sent[0]["text"]


def test_bad_signature_rejected(tmp_path):
    cfg = _cfg(tmp_path, fb_app_secret="APPSECRET")
    pipe = AssistPipeline.from_config(cfg)
    raw = b'{"entry":[]}'
    assert pipe.receive_meta(raw, "sha256=wrong")["accepted"] is False
