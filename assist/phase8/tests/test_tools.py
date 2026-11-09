"""Tests for the data tools: anonymizer and accuracy evaluator."""

from __future__ import annotations

import csv
from collections import Counter

from phase8.tools.anonymize import anonymize_file, scrub
from phase8.tools.evaluate import evaluate, load


def test_scrub_removes_fixed_format_identifiers():
    c = Counter()
    out = scrub("โทร 081-234-5678 อีเมล a.b@mail.com ไลน์ @somchai ดู https://x.co/abc บัญชี 123-4-56789-0 ออเดอร์ 20231105001", c)
    for raw in ("081-234-5678", "a.b@mail.com", "@somchai", "https://x.co/abc", "20231105001"):
        assert raw not in out
    assert c["PHONE"] == 1 and c["EMAIL"] == 1 and c["URL"] == 1


def test_scrub_keeps_ordinary_text_and_small_numbers():
    assert scrub("ซื้อ 2 กล่อง ราคา 159 บาท", Counter()) == "ซื้อ 2 กล่อง ราคา 159 บาท"


def test_anonymize_file_roundtrip(tmp_path):
    src, dst = tmp_path / "in.csv", tmp_path / "out.csv"
    src.write_text("text,true_intent\nโทร 0812345678,I99\n", encoding="utf-8")
    counts = anonymize_file(str(src), str(dst), ["text"])
    assert counts["PHONE"] == 1
    assert "[PHONE]" in list(csv.DictReader(open(dst, encoding="utf-8")))[0]["text"]


def test_evaluate_scores_and_flags_bad_labels(tmp_path):
    p = tmp_path / "l.csv"
    p.write_text("text,true_intent\nราคาเท่าไหร่,I04\nสวัสดี,I99\nอะไรก็ได้,I77\n", encoding="utf-8")
    res = evaluate(load(str(p)))
    assert res["n"] == 2 and res["accuracy"] == 1.0
    assert res["bad_labels"] == [(4, "I77")]


def test_evaluate_reports_missed_sensitive(tmp_path):
    p = tmp_path / "l.csv"
    p.write_text("text,true_intent\nสวัสดีค่ะ,I07\n", encoding="utf-8")
    res = evaluate(load(str(p)))
    assert res["sensitive_total"] == 1 and len(res["sensitive_missed"]) == 1


def test_simulated_line_message_passes_signature_check(tmp_path):
    from phase8.config import Config
    from phase8.pipeline import AssistPipeline
    from phase8.tools.simulate import build_request
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    cfg = Config(
        fb_app_secret="", fb_page_token="", fb_page_id="", fb_verify_token="",
        line_channel_secret="cs", line_channel_access_token="", line_target_group_id="",
        assist_hmac_secret="z" * 32, tenant_id="tulip", db_path=str(tmp_path / "p.db"),
        kb_approved_path=str(root / "phase6/config/approved_kb.json"),
        kb_draft_path=str(root / "phase6/config/kb_draft_from_research.json"),
    )
    body, sig = build_request("ราคาเท่าไหร่", "cs")
    assert AssistPipeline.from_config(cfg).receive_line(body, sig)["ingested"] == 1
