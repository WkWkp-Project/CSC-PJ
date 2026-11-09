"""The /export/* download: off by default, password protected, no identity in files."""

from __future__ import annotations

import base64
from pathlib import Path

from phase8.collector import TextCollector
from phase8.config import Config
from phase8.export_http import export_response

ROOT = Path(__file__).resolve().parents[2]


def _cfg(tmp_path, **kw):
    base = dict(
        fb_app_secret="", fb_page_token="", fb_page_id="", fb_verify_token="",
        line_channel_secret="", line_channel_access_token="", line_target_group_id="",
        assist_hmac_secret="z" * 32, tenant_id="tulip", db_path=str(tmp_path / "p.db"),
        kb_approved_path=str(ROOT / "phase6/config/approved_kb.json"),
        kb_draft_path=str(ROOT / "phase6/config/kb_draft_from_research.json"),
    )
    base.update(kw)
    return Config(**base)


def _basic(password, user="anyone"):
    return "Basic " + base64.b64encode(("%s:%s" % (user, password)).encode()).decode()


def test_disabled_without_password(tmp_path):
    status, _, _ = export_response("/export/summary", _basic("x"), _cfg(tmp_path))
    assert status == 404


def test_wrong_or_missing_password_is_refused(tmp_path):
    cfg = _cfg(tmp_path, export_password="secret-pass")
    assert export_response("/export/summary", "", cfg)[0] == 401
    assert export_response("/export/summary", _basic("nope"), cfg)[0] == 401
    status, headers, _ = export_response("/export/summary", "", cfg)
    assert "WWW-Authenticate" in headers


def test_collected_csv_downloads_when_collecting(tmp_path):
    cfg = _cfg(tmp_path, export_password="secret-pass", store_text=True)
    TextCollector(cfg.db_path).add("line:user", "ราคาเท่าไหร่", "I04", None)
    status, headers, body = export_response("/export/collected.csv", _basic("secret-pass"), cfg)
    assert status == 200 and "attachment" in headers["Content-Disposition"]
    assert "ราคาเท่าไหร่" in body.decode("utf-8-sig")


def test_collected_csv_is_hidden_when_not_collecting(tmp_path):
    cfg = _cfg(tmp_path, export_password="secret-pass", store_text=False)
    assert export_response("/export/collected.csv", _basic("secret-pass"), cfg)[0] == 404


def test_view_page_shows_names_and_escapes_customer_text(tmp_path):
    from phase8.pipeline import AssistPipeline
    cfg = _cfg(tmp_path, export_password="secret-pass", store_text=True)
    pipe = AssistPipeline.from_config(cfg)
    pipe.collector.add("line:user", "<script>alert(1)</script> ราคาเท่าไหร่", "I04", None)
    pipe.engine.conn.execute(
        "INSERT INTO assist_case(case_id,tenant_id,channel_account_id,conversation_key,status,state_version,"
        "primary_intent,route,opened_at,updated_at) VALUES('c1','t','a','k','WAITING_WAKU',1,'I04','R','2026-11-09T01:00:00','2026-11-09T01:00:00')")
    pipe.engine.conn.commit()
    status, headers, body = export_response("/export", _basic("secret-pass"), cfg)
    html = body.decode("utf-8")
    assert status == 200 and "text/html" in headers["Content-Type"]
    assert "ราคา/ค่าส่ง (I04)" in html
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "default-src 'none'" in headers["Content-Security-Policy"]


def test_view_page_needs_login(tmp_path):
    cfg = _cfg(tmp_path, export_password="secret-pass")
    assert export_response("/export", "", cfg)[0] == 401
