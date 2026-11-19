"""Locks in the adversarial experiment's core guarantee: zero dangerous auto-sends.

A dangerous outcome = a message that truly needs a human (health / complaint /
safety / claim / wholesale) that the system would nonetheless auto-reply to.
This must stay 0 as keywords and FAQs grow.
"""

from __future__ import annotations

from phase5.classifier_v2 import classify_v2
from phase8.experiments.adversarial import CASES, _synthetic_filled_kb


def test_no_dangerous_auto_send():
    sugg = _synthetic_filled_kb()
    dangerous = []
    for category, text, needs_human, note in CASES:
        cls = classify_v2(text, "")
        best = sugg.best(cls["primary_intent"], text)
        reaches_auto = (
            cls["route"] == "KB_CANDIDATE_HOLD" and bool(best) and best["auto_sendable"]
        )
        if reaches_auto and needs_human:
            dangerous.append((text, cls["primary_intent"], note))
    assert not dangerous, f"dangerous auto-sends: {dangerous}"


def test_clean_questions_still_automate():
    # Automation must not be so cautious it never fires: the clean controls auto.
    sugg = _synthetic_filled_kb()
    clean = [c for c in CASES if c[0] == "clean"]
    automated = 0
    for _category, text, _needs_human, _note in clean:
        cls = classify_v2(text, "")
        best = sugg.best(cls["primary_intent"], text)
        if cls["route"] == "KB_CANDIDATE_HOLD" and best and best["auto_sendable"]:
            automated += 1
    assert automated == len(clean), "clean control questions should all auto-send"
