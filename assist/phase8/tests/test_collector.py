"""Collection of question types: scrubbed, anonymous, expiring, exportable."""

from __future__ import annotations

import csv
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from phase8.collector import TextCollector
from phase8.config import Config
from phase8.pipeline import AssistPipeline
from phase8.tools.export_collected import fetch, summary, write_csv

ROOT = Path(__file__).resolve().parents[2]


def test_collector_scrubs_and_stores_no_identity(tmp_path):
    c = TextCollector(str(tmp_path / "c.db"))
    assert c.add("line:user", "โทร 081-234-5678 ราคาเท่าไหร่", "I04", "KB_CANDIDATE_HOLD")
    (at, channel, text, pred, route), = c.rows()
    assert "081" not in text and "[PHONE]" in text and "ราคาเท่าไหร่" in text
    assert channel == "line" and pred == "I04"
    cols = [r[1] for r in c.conn.execute("PRAGMA table_info(collected_text)")]
    assert not {"user_id", "conversation_id", "case_id", "sender"} & set(cols)


def test_collector_skips_empty_and_expires_old_rows(tmp_path):
    c = TextCollector(str(tmp_path / "c.db"), retention_days=30)
    assert c.add("meta:P", "   ", None, None) is False
    old = datetime.now(timezone.utc) - timedelta(days=45)
    c.add("meta:P", "ซื้อที่ไหน", "I05", None, now=old)
    c.add("meta:P", "ราคาเท่าไหร่", "I04", None)  # purges the 45-day-old row
    assert [r[2] for r in c.rows()] == ["ราคาเท่าไหร่"]


def _cfg(tmp_path, **kw):
    base = dict(
        fb_app_secret="S", fb_page_token="", fb_page_id="PAGE1", fb_verify_token="",
        line_channel_secret="", line_channel_access_token="", line_target_group_id="",
        assist_hmac_secret="z" * 32, tenant_id="tulip", db_path=str(tmp_path / "p.db"),
        kb_approved_path=str(ROOT / "phase6/config/approved_kb.json"),
        kb_draft_path=str(ROOT / "phase6/config/kb_draft_from_research.json"),
    )
    base.update(kw)
    return Config(**base)


def _send(pipe, text, mid="m1"):
    raw = json.dumps({"entry": [{"id": "PAGE1", "messaging": [
        {"sender": {"id": "U1"}, "timestamp": 1, "message": {"mid": mid, "text": text}}]}]}).encode()
    pipe.receive_meta(raw, "sha256=" + hmac.new(b"S", raw, hashlib.sha256).hexdigest(), now=0.0)


def test_pipeline_collects_only_when_switched_on(tmp_path):
    off = AssistPipeline.from_config(_cfg(tmp_path / "off"))
    assert off.collector is None

    on = AssistPipeline.from_config(_cfg(tmp_path, store_text=True))
    _send(on, "ราคาเท่าไหร่ โทร 0812345678")
    on.flush_due(debounce_seconds=30, now=100.0)
    (row,) = on.collector.rows()
    assert row[3] == "I04" and "0812345678" not in row[2]


def test_export_csv_and_summary(tmp_path):
    db = str(tmp_path / "c.db")
    c = TextCollector(db)
    c.add("line:user", "ราคาเท่าไหร่", "I04", None)
    c.add("line:user", "ซื้อที่ไหน", "I05", None)
    out = tmp_path / "out.csv"
    write_csv(fetch(db), str(out))
    rows = list(csv.DictReader(open(out, encoding="utf-8-sig")))
    assert [r["text"] for r in rows] == ["ราคาเท่าไหร่", "ซื้อที่ไหน"]
    assert all(r["true_intent"] == "" for r in rows)
    assert "I04" in summary(fetch(db))


def test_cases_export_needs_no_text_collection(tmp_path):
    from phase8.tools.export_collected import cases_summary, fetch_cases, write_cases_csv
    pipe = AssistPipeline.from_config(_cfg(tmp_path))  # store_text OFF
    _send(pipe, "ราคาเท่าไหร่")
    pipe.flush_due(debounce_seconds=30, now=100.0)
    pipe.engine.conn.commit()
    rows = fetch_cases(str(tmp_path / "p.db"))
    assert len(rows) == 1 and rows[0][1] == "I04"
    out = tmp_path / "cases.csv"
    write_cases_csv(rows, str(out))
    csv_text = out.read_text(encoding="utf-8-sig")
    assert "ราคาเท่าไหร่" not in csv_text  # no message text in it
    assert "ราคา/ค่าส่ง" in csv_text  # but the readable category name is
    assert "I04" in cases_summary(rows)
