from __future__ import annotations

import re
from copy import deepcopy

from phase3.run_offline_shadow import FAQ_CANDIDATE, INTENT_RULES, LEGACY_FALLBACK, SALES, norm


RULES = deepcopy(INTENT_RULES)
RULES["I03"] += ["เป็นเจ", "โกโก้เจ", "มังสวิรัติ", "vegetarian", "plant-based", "plant based", "keto"]
RULES["I05"] = [x for x in RULES["I05"] if x != "ร้าน"] + ["ร้านไหน", "ขายที่ไหน", "มีขายที่", "ซื้อที่", "จุดจำหน่าย", "ร้านเปิดกี่โมง", "เปิดกี่โมง"]
RULES["I06"] += ["ขาดตลาด", "ของเข้าเมื่อไหร่", "ของเข้าเมื่อไร", "มีของไหม", "มีของมั้ย", "มีสินค้าไหม", "มีช็อกโกแลตไหม", "สต็อก", "stock"]
RULES["I07"] += ["รับไปขาย", "สำหรับร้าน"]
RULES["I11"] += ["ผู้โชคดี", "ส่งผลงานรับของรางวัล", "ติดตามแลกของรางวัล"]
RULES["I14"] = [x for x in RULES["I14"] if x != "เสีย"] + ["สินค้าเสีย", "ของเสีย", "ร้องเรียนคุณภาพ", "สติกเกอร์ลอก", "ฉลากลอก"]
RULES["I15"] += ["สถานที่จัดงาน", "จัดงาน", "รอบเพิ่ม"]

# Optional Phase 8 keyword recall extension. Additions target only low-priority
# intents, so they cannot steal a message from a higher-priority (safety /
# complaint / wholesale) intent. Absent module => classifier unchanged.
try:
    from phase8.classifier_ext import KEYWORD_ADDITIONS as _KW_EXT

    for _iid, _extra in _KW_EXT.items():
        RULES[_iid] = list(dict.fromkeys(RULES.get(_iid, []) + _extra))
except ModuleNotFoundError:
    pass

PERSONAL_SAFETY_TERMS = ["แพ้", "ภูมิแพ้", "เบาหวาน", "น้ำตาลในเลือด", "โลหะหนัก", "heavy metal", "ปลอดภัย"]
INDIVIDUAL_LABEL_TERMS = ["วันหมดอายุ", "สติกเกอร์ลอก", "ฉลากลอก"]
QUALITY_DECISION_TERMS = ["ร้องเรียนคุณภาพ", "คุณภาพลดลง", "ผิดปกติ", "รสชาติ", "ขม", "เปรี้ยว", "ไม่หอม", "ไม่อร่อย", "สินค้าเสีย", "ของเสีย", "รั่ว", "แตก"]
GENERAL_REGISTRATION_QUESTIONS = ["ต้องลงทะเบียนไหม", "ต้องลงทะเบียนหรือไม่"]


def _is_greeting(text: str) -> bool:
    cleaned = re.sub(r"[.!?…\s]+", "", text)
    return bool(re.fullmatch(r"(?:สวัสดี(?:ค่ะ|ครับ|คะ|ค่า|ค้าบ)?|หวัดดี|hi|hello)", cleaned, re.I))


def classify_v2(summary: str, legacy: str) -> dict:
    text = norm(summary)
    system = text.startswith("facebook สร้างแชท")
    no_text = text == "(ไม่มีข้อความลูกค้า)"
    greeting = _is_greeting(text)
    suspect = any(x in text for x in ["เพจของคุณจึงถูกบล็อก", "ยืนยันบัญชี", "verify account", "page blocked"])
    truncated_introduction = "…" in text and any(x in text for x in ["มาจากชมรม", "มาจากมหาวิทยาลัย", "มาจากบริษัท"])
    truncated_event_intro = "…" in text and "workshop" in text and any(x in text for x in ["ได้ไป", "เคยไป", "เมื่อ"])

    intents = [iid for iid, terms in RULES.items() if any(term in text for term in terms)]
    if truncated_event_intro and "I15" in intents:
        intents.remove("I15")
    if "I16" in intents and any(term in text for term in GENERAL_REGISTRATION_QUESTIONS) and "สมัคร" not in text:
        intents.remove("I16")
    evidence = "keyword_v2"
    if not intents and legacy in LEGACY_FALLBACK and not (system or no_text or greeting or truncated_introduction):
        intents = [LEGACY_FALLBACK[legacy]]
        evidence = "legacy_fallback"
    if not intents:
        intents = ["I99"]
        evidence = "insufficient_summary"

    priority = ["I14", "I03", "I13", "I11", "I12", "I10", "I16", "I07", "I17", "I08", "I18", "I06", "I09", "I02", "I15", "I05", "I04", "I01", "I99"]
    primary = next(i for i in priority if i in intents)
    secondary = [i for i in intents if i != primary]

    flags = []
    if system:
        flags.append("E_SYSTEM")
    if greeting:
        flags.append("E_GREETING")
    if suspect:
        flags.append("E_SUSPECT_SPAM")
    if any(x in text for x in ["ที่อยู่", "เบอร์โทร", "ชื่อผู้รับ"]):
        flags.append("F_PERSONAL_POSSIBLE")
    if primary == "I03" and not any(x in text for x in PERSONAL_SAFETY_TERMS):
        flags.append("F_FORMAL_PRODUCT_FACT_REQUIRED")
    if primary == "I14" and any(x in text for x in INDIVIDUAL_LABEL_TERMS):
        flags.append("F_INDIVIDUAL_ITEM_VERIFICATION")

    if suspect:
        route = "H3_SECURITY_HOLD"
    elif primary in SALES:
        route = "SALES_OR_H2_REVIEW"
    elif primary == "I03":
        route = "H2_HUMAN_DECISION" if any(x in text for x in PERSONAL_SAFETY_TERMS) else "H1_INFORMATION_INQUIRY"
    elif primary == "I14":
        has_decision_risk = any(x in text for x in QUALITY_DECISION_TERMS + PERSONAL_SAFETY_TERMS)
        route = "H1_INFORMATION_INQUIRY" if "F_INDIVIDUAL_ITEM_VERIFICATION" in flags and not has_decision_risk else "H2_HUMAN_DECISION"
    elif primary in {"I06", "I10", "I11", "I12", "I13", "I16", "I18"}:
        route = "H1_INFORMATION_INQUIRY"
    elif primary == "I99" or system or no_text or greeting:
        route = "HOLD_OR_NO_ACTION"
    elif primary in FAQ_CANDIDATE:
        route = "KB_CANDIDATE_HOLD"
    else:
        route = "HOLD_FOR_POLICY"

    return {
        "primary_intent": primary,
        "secondary_intents": secondary,
        "event_flags": flags,
        "route": route,
        "classification_evidence": evidence,
        "customer_auto_send": False,
        "auto_send_block_reason": "APPROVED_KB_AND_RESPONSE_POLICY_NOT_AVAILABLE",
        "classifier_version": "v2_phase5_safety_remediation",
    }
