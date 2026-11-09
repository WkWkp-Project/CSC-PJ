"""Adversarial matching experiment.

Runs tricky Thai messages (decoys, typos, polysemy, slang, multi-context,
contradiction/negation) through the real classifier + suggestion layer, under the
WORST CASE for safety: a KB where every self-answer FAQ is already filled and
approved (so auto-send is maximally enabled). The point is to see whether the
guards keep dangerous auto-sends at zero while clean questions still automate.

Each case carries ``needs_human`` = the TRUE business judgment: does a correct
system have to hand this to a person (health / complaint / safety / vegan-halal
claim / wholesale)?  The experiment then checks what actually happened:

  AUTO     - the system would auto-reply (route=KB_CANDIDATE_HOLD and auto_sendable)
  HUMAN    - the system hands it to a person (any other outcome)

Verdicts:
  DANGEROUS   needs_human AND AUTO   -> a wrong answer would reach the customer
  AUTO_OK     not needs_human AND AUTO
  SAFE_HUMAN  needs_human AND HUMAN  -> correctly caught for a person
  HUMAN_FALL  not needs_human AND HUMAN -> safe; just not automated

Run:  PYTHONPATH=. python3 phase8/experiments/adversarial.py
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from phase5.classifier_v2 import classify_v2
from phase8.suggestion import SuggestionEngine

ROOT = Path(__file__).resolve().parents[2]
DRAFT = ROOT / "phase6" / "config" / "kb_draft_from_research.json"
REPORT = ROOT / "adversarial_report.csv"

# (category, text, needs_human, note)
CASES = [
    # ---- คำหลอก (decoy: looks like a keyword, isn't that intent) ----
    ("decoy", "ราคาคุยกันได้ไหมคะ", False, "benign price"),
    ("decoy", "ลังเลว่าจะซื้อตัวไหนดี", False, "'ลังเล' มี substring 'ลัง' (ขายส่ง)"),
    ("decoy", "เซลล์บริการดีมากประทับใจ", False, "'เซลล์' = คำชม ไม่ใช่ขอติดต่อ"),
    ("decoy", "แพ้ทางเลย อร่อยมากกก", False, "'แพ้ทาง' = สแลงชอบ ไม่ใช่ภูมิแพ้"),

    # ---- คำผิด (typos) ----
    ("typo", "ราคาเทาไรคับ", False, "typo เทาไร (ตกไม้เอก) แต่มี 'ราคา'"),
    ("typo", "ซื้อที่ไหนหรอคะ มีช่องทางไหน", False, "สะกดห้วน"),
    ("typo", "มีฮาลานไหม", True, "ฮาลาล สะกดผิด -> ควรถึงคน"),
    ("typo", "แพ้กลูเตนมั้ย", True, "allergy สะกดถูก"),

    # ---- คำหลายความหมาย (polysemy) ----
    ("polysemy", "โกโก้เจไหม ราคาเท่าไหร่", True, "เจ = อาหารเจ (claim)"),
    ("polysemy", "ฝากส่งให้เจด้วยนะคะ", False, "เจ = ชื่อคน ไม่ใช่อาหารเจ"),
    ("polysemy", "สั่งยกลังหนึ่งกี่กล่อง", True, "ลัง = หน่วยขายส่งจริง"),
    ("polysemy", "เพิ่งแพ้บอลมาเลยเซ็ง", False, "แพ้ = แพ้การแข่งขัน"),

    # ---- คำแสลง (slang) ----
    ("slang", "ตัวนี้ปังมาก ขอราคาหน่อย", False, "ปัง = ดี (สแลง) + ราคา"),
    ("slang", "จัดส่งงับ รอเลขพัสดุอยู่", True, "งับ สแลง + ติดตามพัสดุ"),
    ("slang", "คือดีย์ มีโปรไหมอ่ะ", False, "สแลง + ถามโปร (ไม่มี keyword ตรง)"),
    ("slang", "อยากได้อ่ะ สั่งไงอ่ะ", False, "สแลง สั่งไง"),

    # ---- คำหลายบริบท (multi-intent in one message) ----
    ("multi", "โกโก้เจไหม ราคาเท่าไหร่ ส่งฟรีปะ", True, "เจ(claim)+ราคา+ส่ง"),
    ("multi", "อยากสั่ง 10 ลัง ราคาส่ง แล้วมีฮาลาลไหม", True, "ขายส่ง + ฮาลาล"),
    ("multi", "ซื้อที่ไหน แล้วกินแล้วแพ้ถั่วไหม", True, "ซื้อ + allergy"),
    ("multi", "มี workshop ไหม สมัครยังไง", True, "อีเวนต์ + สมัคร(ข้อมูลส่วนตัว)"),

    # ---- ข้อความขัดแย้ง (contradiction / negation) ----
    ("contradiction", "ไม่ได้จะร้องเรียนนะ แค่สงสัยราคา", False, "ปฏิเสธร้องเรียน + ถามราคา"),
    ("contradiction", "ไม่ได้แพ้อะไรนะ แค่ถามราคา", False, "ปฏิเสธภูมิแพ้ + ถามราคา"),
    ("contradiction", "สินค้าไม่เสียหรอก แต่กล่องบุบมา", True, "บ่นเบาๆ (กล่องบุบ)"),
    ("contradiction", "ตอนแรกแย่ แต่ตอนนี้โอเคแล้ว ขอบคุณ", False, "เคลียร์แล้ว คำชม"),

    # ---- hidden safety (คำถามความปลอดภัยซ่อนหลังคำไม่มีพิษภัย) ----
    ("hidden_safety", "เด็กกินได้ไหม ราคาเท่าไหร่", True, "ความเหมาะสมกับเด็ก ซ่อนหลังราคา"),
    ("hidden_safety", "คนท้องทานได้ไหมคะ ซื้อที่ไหน", True, "คนท้อง ซ่อนหลังช่องทาง"),
    ("hidden_safety", "ลูกกินแล้วขึ้นผื่น ซื้อเพิ่มที่ไหน", True, "ผื่น (อาการ) ซ่อน"),
    ("hidden_safety", "กินแล้วคลื่นไส้ ตัวนี้ราคาเท่าไร", True, "คลื่นไส้ ซ่อน"),
    ("hidden_safety", "ผู้สูงอายุทานได้ไหม มีขนาดเล็กไหม", True, "ผู้สูงอายุ ซ่อนหลังขนาด"),
    ("hidden_safety", "เบาหวานกินได้ไหม", True, "เบาหวาน = I03 ตรง"),

    # ---- hidden complaint (ร้องเรียนซ่อนหลังคำถามทั่วไป) ----
    ("hidden_complaint", "ได้ของแล้วแต่ไม่โอเคเลย ซื้อเพิ่มที่ไหน", True, "ไม่โอเค ซ่อน"),
    ("hidden_complaint", "อยากได้เงินคืน สั่งผิดรุ่น", True, "คืนเงิน"),
    ("hidden_complaint", "ของที่ได้รสชาติแปลกๆ ซื้อเพิ่มได้ที่ไหน", True, "รสชาติ (I14) ตรง"),
    ("hidden_complaint", "สั่งไปนานแล้วไม่โอเคเลยบริการ", True, "ไม่โอเค บริการ"),
    ("hidden_complaint", "โดนโกงรึเปล่าเนี่ย เงินหักแล้วของไม่มา", True, "โกง"),

    # ---- spam / suspect ----
    ("spam", "เพจของคุณจึงถูกบล็อก กรุณายืนยันบัญชี", None, "ฟิชชิ่ง -> H3"),
    ("spam", "verify account now or page blocked", None, "ฟิชชิ่งอังกฤษ -> H3"),
    ("spam", "คลิกลิงก์รับเครดิตฟรี", False, "สแปมทั่วไป"),

    # ---- emoji / สั้น / noise ----
    ("noise", "👍", False, "อีโมจิล้วน"),
    ("noise", "???", False, "เครื่องหมายล้วน"),
    ("noise", "สนใจค่ะ", False, "สั้น ไม่มีบริบท"),
    ("noise", ".", False, "จุดเดียว"),
    ("noise", "ค่ะ", False, "คำรับล้วน"),

    # ---- english / mixed ----
    ("english", "how much is it", False, "อังกฤษล้วน (ไม่มี keyword ไทย)"),
    ("english", "where to buy online", False, "อังกฤษ where/buy/online"),
    ("english", "is it vegan?", True, "vegan = claim (I03)"),
    ("english", "halal certified?", True, "halal = claim (I03)"),

    # ---- decoy เพิ่ม ----
    ("decoy", "สั่งสมใจจริงๆ ตัวนี้", False, "'สั่งสม' มี 'สั่ง'? ไม่ตรง keyword"),
    ("decoy", "ราคาคุยกันได้ไหม อยากได้จริงๆ", False, "ต่อราคา"),
    ("decoy", "โปรดปรานตัวนี้มาก", False, "'โปรด' ไม่ใช่ 'โปรโมชัน'"),
    ("decoy", "ช่องทางติดต่อเพจมีไหม", False, "ช่องทาง -> I05 (ถูก)"),

    # ---- typo เพิ่ม ----
    ("typo", "ซื้อยังงัยคับ", False, "สั่งยังไง สะกดเพี้ยน"),
    ("typo", "มีโปรโมชั่นไหม", False, "โปรโมชั่น (ไม้ไต่คู้) vs โปรโมชัน"),
    ("typo", "ราคาส่งถูกมั้ยย", True, "ราคาส่ง = ขายส่ง"),
    ("typo", "เวิร์คช็อปมีไหม", False, "เวิร์คช็อป (ค) vs เวิร์กช็อป (ก)"),

    # ---- polysemy เพิ่ม ----
    ("polysemy", "ตัวนี้เปรี้ยวปากอยากกิน", False, "'เปรี้ยว' (I14) แต่บริบทอยากกิน"),
    ("polysemy", "ขมแบบผู้ใหญ่ชอบ อร่อย", False, "'ขม' (I14) แต่เป็นคำชม"),
    ("polysemy", "ส่งเป็นของขวัญได้ไหม", False, "'ส่ง' ไม่ใช่ติดตามพัสดุ"),

    # ---- slang เพิ่ม ----
    ("slang", "เริ่ดอ่ะ ขอราคาจุก ๆ", False, "สแลง + ราคา"),
    ("slang", "มีของมะ อยากซอย", False, "สแลง 'ซอย'=ซื้อ ไม่มี keyword"),
    ("slang", "เทพมาก ส่งไวปะ", False, "สแลง ไม่มี keyword ชัด"),

    # ---- contradiction เพิ่ม ----
    ("contradiction", "ไม่ได้ว่าของไม่ดีนะ แต่ส่งช้าไปหน่อย", True, "บ่นส่งช้า แบบอ้อม"),
    ("contradiction", "ไม่เคลมหรอก แค่อยากบอกว่ากล่องบุบ", True, "ปฏิเสธเคลมแต่แจ้งปัญหา"),
    ("contradiction", "ไม่ได้โกรธนะ แต่ผิดหวังมาก", True, "ผิดหวัง (sentiment ลบ)"),

    # ---- clean control (ควร auto ได้จริง) ----
    ("clean", "ราคาเท่าไหร่คะ", False, "ถามราคาล้วน"),
    ("clean", "ซื้อที่ไหนได้บ้าง มีช่องทางไหน", False, "ถามช่องทางล้วน"),
    ("clean", "มี workshop ไหม", False, "ถามอีเวนต์ล้วน"),
    ("clean", "ขนาด 500 กรัม ราคาเท่าไหร่", False, "ถามขนาด+ราคา"),
    ("clean", "สั่งซื้อผ่าน tiktok ได้ไหม", False, "ถามช่องทาง tiktok"),
    ("clean", "เก็บในตู้เย็นได้ไหม", False, "ถามวิธีเก็บ"),
]


def _synthetic_filled_kb() -> SuggestionEngine:
    """Worst case: every draft entry filled + approved, so auto is fully enabled."""
    data = json.loads(DRAFT.read_text(encoding="utf-8"))
    entries = []
    for e in data["entries"]:
        e = dict(e)
        e["answer"] = "[คำตอบตัวอย่างที่กรอก+อนุมัติแล้ว]"
        e["status"] = "published"
        e["approved"] = True
        entries.append(e)
    return SuggestionEngine(entries)


def run() -> int:
    sugg = _synthetic_filled_kb()
    rows = []
    counts = {"DANGEROUS": 0, "AUTO_OK": 0, "SAFE_HUMAN": 0, "HUMAN_FALL": 0}
    for category, text, needs_human, note in CASES:
        cls = classify_v2(text, "")
        primary, route = cls["primary_intent"], cls["route"]
        best = sugg.best(primary, text)
        reaches_auto = route == "KB_CANDIDATE_HOLD" and bool(best) and best["auto_sendable"]
        if reaches_auto and needs_human:
            verdict = "DANGEROUS"
        elif reaches_auto:
            verdict = "AUTO_OK"
        elif needs_human:
            verdict = "SAFE_HUMAN"
        else:
            verdict = "HUMAN_FALL"
        counts[verdict] += 1
        risk = best["risk_sentinel_hits"] if best else []
        rows.append({
            "category": category, "text": text, "needs_human": needs_human,
            "primary_intent": primary, "route": route,
            "reaches_auto": reaches_auto, "risk_hits": "|".join(risk),
            "verdict": verdict, "note": note,
        })

    # Console report
    icon = {"DANGEROUS": "🔴", "AUTO_OK": "🟢", "SAFE_HUMAN": "🟢", "HUMAN_FALL": "🟡"}
    cur = None
    for r in rows:
        if r["category"] != cur:
            cur = r["category"]
            print("\n### %s" % cur)
        auto = "AUTO" if r["reaches_auto"] else "คน "
        print("  %s %-10s [%3s|%-5s] %s" % (
            icon[r["verdict"]], r["verdict"], r["primary_intent"], auto, r["text"]))
        if r["risk_hits"]:
            print("        ↳ ดักคำเสี่ยง: %s" % r["risk_hits"])

    total = len(rows)
    print("\n" + "=" * 60)
    print("สรุป %d เคส:" % total)
    print("  🔴 DANGEROUS (ตอบผิดถึงลูกค้า): %d   <-- ต้องเป็น 0" % counts["DANGEROUS"])
    print("  🟢 AUTO_OK   (ตอบเองถูกต้อง):   %d" % counts["AUTO_OK"])
    print("  🟢 SAFE_HUMAN(ดักส่งคนถูกต้อง): %d" % counts["SAFE_HUMAN"])
    print("  🟡 HUMAN_FALL(ส่งคน/ไม่ auto):  %d" % counts["HUMAN_FALL"])
    safe_rate = (total - counts["DANGEROUS"]) / total * 100
    print("  อัตราปลอดภัย (ไม่ตอบผิดถึงลูกค้า): %.1f%%" % safe_rate)

    with REPORT.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print("\nรายงาน CSV: %s" % REPORT)
    return 0 if counts["DANGEROUS"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(run())
