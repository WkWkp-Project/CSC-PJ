"""Phase 8 - reply suggestion from the KB (the "suggest" operating mode).

The KB can drive three operating modes, selectable per entry by the brand:

  A. route-only   - the ticket just says what the case is; a human writes the reply.
  B. suggest      - the ticket carries a SUGGESTED reply pulled from the KB; a human
                    reviews it and clicks send (or edits first). No AI needed.
  C. auto         - the engine sends the approved answer itself (only for
                    self-answer intents, only once the brand approves).

This module implements mode B: given a classified message, it finds the best KB
entries for that intent, scores them by keyword overlap, and returns a suggestion
the staff ticket can carry. It is deliberately conservative:

  * ``ready_to_send`` is True only when the answer is published, approved, and has
    no unfilled «...» placeholder. A draft (brand not done) is returned as a
    not-ready preview, never as a send-ready reply.
  * ``auto_sendable`` is True only for a self-answer intent whose answer is ready;
    sensitive intents (I03/I07/I14) are always ``requires_human_review`` and never
    auto_sendable, whatever their approval state.

Nothing here sends anything. It produces a suggestion object; delivery stays with
OpsDelivery, and sending stays with a human (mode B) or a future, explicitly
enabled auto path (mode C).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PLACEHOLDER = "«"
SENSITIVE_INTENTS = {"I03", "I07", "I14"}

# Risk-sentinel words. If any appears in the message, the suggestion must NOT be
# auto-sendable even when the primary intent looks harmless (e.g. a price
# question that also says "ไม่สบายท้อง"). This catches the dangerous case where a
# health / complaint / refund signal is hidden behind a benign keyword. A hit
# forces human review; it only ever makes the system MORE cautious.
RISK_SENTINELS = [
    # health / safety
    "ไม่สบาย", "ท้องเสีย", "ปวดท้อง", "ผื่น", "คัน", "อาเจียน", "แพ้", "เวียนหัว",
    "ไม่ย่อย", "ป่วย", "แสบ", "คลื่นไส้",
    # suitability / vulnerable groups (a "can X eat this?" safety question)
    "เด็กกิน", "เด็กทาน", "ให้เด็ก", "สำหรับเด็ก", "กี่ขวบ", "คนท้อง", "ตั้งครรภ์",
    "ให้นมบุตร", "ผู้สูงอายุ",
    # strong dissatisfaction / complaint / fraud / refund / legal
    "ไม่โอเค", "คืนเงิน", "คืนสินค้า", "หลอก", "โกง", "ห่วย", "แย่มาก",
    "ร้องเรียน", "ปลอม", "ฟ้อง", "เรียกร้อง", "ชดเชย", "เยียวยา",
]


def risk_sentinel_hits(text: str) -> list[str]:
    """Return risk words present in the message (empty if none)."""
    low = text.lower()
    return [w for w in RISK_SENTINELS if w in low]


def _answer_text(entry: dict[str, Any]) -> tuple[str, bool]:
    """Return (text, is_filled). Prefer a filled `answer`; fall back to the draft."""
    answer = (entry.get("answer") or "").strip()
    if answer and PLACEHOLDER not in answer:
        return answer, True
    draft = (entry.get("answer_draft") or "").strip()
    return draft, False


def _is_published_approved(entry: dict[str, Any]) -> bool:
    return entry.get("status") == "published" and entry.get("approved") is True


class SuggestionEngine:
    def __init__(self, entries: list[dict[str, Any]]):
        self.entries = entries

    @classmethod
    def from_files(cls, approved_path: str | Path, draft_path: str | Path | None = None,
                   include_draft: bool = True) -> "SuggestionEngine":
        entries: list[dict[str, Any]] = []
        ap = Path(approved_path)
        if ap.exists():
            entries += json.loads(ap.read_text(encoding="utf-8")).get("entries", [])
        if include_draft and draft_path and Path(draft_path).exists():
            entries += json.loads(Path(draft_path).read_text(encoding="utf-8")).get("entries", [])
        return cls(entries)

    def suggest(self, intent: str, text: str, *, limit: int = 3) -> list[dict[str, Any]]:
        text_l = text.lower()
        risk_hits = risk_sentinel_hits(text)
        scored = []
        for e in self.entries:
            if intent not in e.get("intents", []):
                continue
            matched = [k for k in e.get("keywords", []) if k.lower() in text_l]
            answer, filled = _answer_text(e)
            sensitive = bool(SENSITIVE_INTENTS & set(e.get("intents", [])))
            ready = filled and _is_published_approved(e)
            mode = e.get("answer_mode", "human_assist")
            # A hidden risk signal blocks auto-send and forces human review, even
            # when the matched intent is a harmless self-answer one.
            auto_sendable = (
                ready and mode == "self_answer_candidate" and not sensitive and not risk_hits
            )
            scored.append({
                "source_id": e.get("id"),
                "intent": intent,
                "suggested_text": answer,
                "matched_keywords": matched,
                "confidence": "high" if len(matched) >= 2 else ("medium" if matched else "low"),
                "ready_to_send": ready,
                "auto_sendable": auto_sendable,
                "requires_human_review": sensitive or mode != "self_answer_candidate" or not ready or bool(risk_hits),
                "risk_sentinel_hits": risk_hits,
                "auto_block_reason": "risk_sentinel_present" if (risk_hits and ready and not sensitive) else None,
                "status": e.get("status"),
                "approved": bool(e.get("approved")),
                "is_placeholder_draft": not filled,
                "safety_note": e.get("safety_note", ""),
            })
        # Rank: ready first, then more keyword matches, then approved.
        scored.sort(key=lambda s: (s["ready_to_send"], len(s["matched_keywords"]), s["approved"]), reverse=True)
        return scored[:limit]

    def best(self, intent: str, text: str) -> dict[str, Any] | None:
        out = self.suggest(intent, text, limit=1)
        return out[0] if out else None
