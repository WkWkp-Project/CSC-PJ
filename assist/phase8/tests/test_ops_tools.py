"""Backup, watchdog and public policy pages."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from phase8.config import Config
from phase8.legal_pages import legal_response
from phase8.tools import backup_db, watchdog

ROOT = Path(__file__).resolve().parents[2]


def _db(path, rows=3):
    c = sqlite3.connect(path)
    c.execute("create table t(x)")
    c.executemany("insert into t values (?)", [(i,) for i in range(rows)])
    c.commit()
    c.close()


# ---- backup ----------------------------------------------------------------

def test_backup_is_readable_and_prunes(tmp_path):
    src = tmp_path / "assist.db"
    _db(src)
    dest = tmp_path / "bk"
    made = [backup_db.backup(src, dest, keep=2, now=datetime(2026, 11, d, 3, 0, 0)) for d in (1, 2, 3)]
    left = sorted(p.name for p in dest.iterdir())
    assert left == [made[1].name, made[2].name]            # oldest pruned, no .partial left
    assert sqlite3.connect(made[2]).execute("select count(*) from t").fetchone()[0] == 3


def test_backup_refuses_missing_source_and_creates_nothing(tmp_path):
    with pytest.raises(backup_db.BackupError):
        backup_db.backup(tmp_path / "nope.db", tmp_path / "bk")
    assert not (tmp_path / "nope.db").exists()


def test_backup_rejects_a_non_database(tmp_path):
    bad = tmp_path / "assist.db"
    bad.write_bytes(b"this is not sqlite" * 50)
    with pytest.raises(backup_db.BackupError):
        backup_db.backup(bad, tmp_path / "bk")
    assert list((tmp_path / "bk").glob("assist-*")) == []


def test_backup_cli_exit_codes(tmp_path):
    src = tmp_path / "a.db"
    _db(src)
    assert backup_db.main(["--src", str(src), "--dest", str(tmp_path / "o")]) == 0
    assert backup_db.main(["--src", str(tmp_path / "none"), "--dest", str(tmp_path / "o")]) == 1


# ---- watchdog --------------------------------------------------------------

def test_watchdog_alerts_once_after_misses_then_recovery(tmp_path):
    said, state = [], tmp_path / "s.json"
    down, up = (lambda u: (False, "refused")), (lambda u: (True, "ok"))
    r = [watchdog.run_once("u", state, said.append, failures=2, probe=p) for p in (down, down, down, up, up)]
    assert r == ["up", "newly_down", "down", "recovered", "up"]
    assert len(said) == 2 and "ไม่ตอบสนอง" in said[0] and "กลับมา" in said[1]


def test_watchdog_one_blip_is_silent(tmp_path):
    said, state = [], tmp_path / "s.json"
    for p in ((lambda u: (False, "x")), (lambda u: (True, "ok")), (lambda u: (False, "x"))):
        watchdog.run_once("u", state, said.append, failures=2, probe=p)
    assert said == []


def test_watchdog_failed_alert_is_retried_next_minute(tmp_path):
    state, calls = tmp_path / "s.json", []

    def flaky(text):
        calls.append(text)
        if len(calls) == 1:
            raise OSError("line down")

    down = lambda u: (False, "x")  # noqa: E731
    watchdog.run_once("u", state, flaky, failures=1, probe=down) if False else None
    with pytest.raises(OSError):
        watchdog.run_once("u", state, flaky, failures=1, probe=down)
    assert watchdog.run_once("u", state, flaky, failures=1, probe=down) == "newly_down"
    assert len(calls) == 2


def test_check_against_a_real_healthz(tmp_path):
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    ready = {"v": True}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            b = json.dumps({"engine_ready": ready["v"]}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = "http://127.0.0.1:%d/healthz" % srv.server_port
    assert watchdog.check(url) == (True, "ok")
    ready["v"] = False
    assert watchdog.check(url)[0] is False
    srv.shutdown()
    assert watchdog.check(url, timeout=1)[0] is False        # nothing listening


def test_line_notifier_posts_to_group_and_dry_runs_when_blank(capsys):
    seen = []
    watchdog.line_notifier("TOK", "Cgroup", post=lambda u, b, h: seen.append((u, json.loads(b), h)))("hi")
    url, body, headers = seen[0]
    assert url.endswith("/message/push") and body["to"] == "Cgroup" and headers["Authorization"] == "Bearer TOK"
    watchdog.line_notifier("", "", post=lambda *a: seen.append("BAD"))("hi")
    assert len(seen) == 1 and "LINE not configured" in capsys.readouterr().out


# ---- policy pages ----------------------------------------------------------

def _cfg(**kw):
    base = dict(
        fb_app_secret="", fb_page_token="", fb_page_id="", fb_verify_token="",
        line_channel_secret="", line_channel_access_token="", line_target_group_id="",
        assist_hmac_secret="z" * 32, tenant_id="tulip", db_path=":memory:",
        kb_approved_path=str(ROOT / "phase6/config/approved_kb.json"),
        kb_draft_path=str(ROOT / "phase6/config/kb_draft_from_research.json"),
    )
    base.update(kw)
    return Config(**base)


def test_pages_are_off_until_company_and_email_are_set():
    assert legal_response("/privacy", _cfg())[0] == 404
    assert legal_response("/data-deletion", _cfg(company_name="X")) [0] == 404
    assert legal_response("/other", _cfg()) is None


def test_pages_render_details_and_escape_them():
    cfg = _cfg(company_name="Acme <b>Co</b>", contact_email="a@b.co", store_text=True, text_retention_days=45)
    for path in ("/privacy", "/data-deletion"):
        status, headers, body = legal_response(path, cfg)
        text = body.decode()
        assert status == 200 and "a@b.co" in text and "<b>Co</b>" not in text and "Acme &lt;b&gt;" in text
        assert "45" in text and "Content-Security-Policy" in headers


def test_policy_text_follows_the_collection_switch():
    off = legal_response("/privacy", _cfg(company_name="X", contact_email="a@b.co"))[2].decode()
    on = legal_response("/privacy", _cfg(company_name="X", contact_email="a@b.co", store_text=True))[2].decode()
    assert "ไม่มีการเก็บข้อความของลูกค้า" in off and "ไม่มีการเก็บข้อความของลูกค้า" not in on
