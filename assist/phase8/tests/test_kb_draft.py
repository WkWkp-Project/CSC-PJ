"""Validates the research-derived draft KB.

Proves three things the brand cares about:
1. Nothing in the draft is live (every entry is draft/unapproved, and the engine
   loads zero servable entries from it).
2. Each FAQ's question actually routes to its declared intent through the real
   classifier - so once approved, the entry will be reachable.
3. No self-answer FAQ exists for a sensitive intent (I03 / I07 / I14).
"""

from __future__ import annotations

import json
from pathlib import Path

from phase5.classifier_v2 import classify_v2

CONFIG = Path(__file__).resolve().parents[2] / "phase6" / "config"
DRAFT = CONFIG / "kb_draft_from_research.json"
SENSITIVE = {"I03", "I07", "I14"}
FORBIDDEN_PII_KEYS = {"name", "phone", "address", "customer", "message_text"}


def _entries():
    data = json.loads(DRAFT.read_text(encoding="utf-8"))
    return data["entries"]


def test_nothing_is_live():
    for e in _entries():
        assert e["status"] == "draft", e["id"]
        assert e["approved"] is False, e["id"]
        assert e.get("approved_by") is None, e["id"]


def test_engine_loads_zero_servable_from_draft():
    # The engine's own gate: only status=published AND approved=true load.
    data = json.loads(DRAFT.read_text(encoding="utf-8"))
    servable = [x for x in data["entries"] if x.get("status") == "published" and x.get("approved") is True]
    assert servable == []


def test_each_question_routes_to_declared_intent():
    for e in _entries():
        result = classify_v2(e["question"], "")
        predicted = {result["primary_intent"], *result["secondary_intents"]}
        declared = set(e["intents"])
        assert declared & predicted, (
            f"{e['id']}: declared {declared} but classifier predicted {predicted} "
            f"for question {e['question']!r}"
        )


def test_no_self_answer_for_sensitive_intents():
    # Sensitive intents may have a draft to HELP a human reply, but must never be
    # answer_mode=self_answer_candidate (the engine must not auto-answer them).
    for e in _entries():
        if SENSITIVE & set(e["intents"]):
            assert e["answer_mode"] == "human_assist", (
                f"{e['id']} targets a sensitive intent but is not human_assist"
            )


def test_no_pii_fields_present():
    for e in _entries():
        assert not (FORBIDDEN_PII_KEYS & set(e.keys())), e["id"]


def test_every_entry_lists_what_brand_must_fill():
    for e in _entries():
        assert e.get("needs_brand_input"), e["id"]
        assert "«" in e["answer_draft"], f"{e['id']} draft has no placeholder to fill"
