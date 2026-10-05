"""Proves the keyword extension (1) gains recall and (2) breaks no existing routing.

The critical property: adding keywords to low-priority intents must NOT change how
any higher-priority (safety / complaint / wholesale / security) message routes.
"""

from __future__ import annotations

import pytest

from phase5.classifier_v2 import classify_v2

# Messages that were previously unclassified (I99) and must now land correctly.
RECALL_GAINS = [
    ("ขอผงโกโก้ dutch process", "I01"),
    ("มีกี่แคลอรี ไขมันเท่าไร", "I01"),
    ("ละลายในน้ำร้อนไหมคะ", "I02"),
    ("ส่งฟรีไหม มีโปรโมชันหรือลดราคาไหม", "I04"),
    ("สั่งซื้อยังไง มีขายใน tiktok ไหม", "I05"),
    ("restock ยัง สินค้าหมดตลอดเลย", "I06"),
    ("มีแคมเปญอะไร ร่วมสนุกยังไง", "I09"),
    ("มีอีเวนต์ หรืองานแฟร์ที่ไหนบ้าง", "I15"),
]

# Higher-priority messages whose routing MUST be unchanged by the additions.
NO_REGRESSION = [
    ("แพ้ถั่วไหม กินแล้วปลอดภัยไหม", "I03", "H2_HUMAN_DECISION"),
    ("สินค้าเสีย รสชาติผิดปกติ ขอร้องเรียนคุณภาพ", "I14", "H2_HUMAN_DECISION"),
    ("ขายส่งยกลัง ขั้นต่ำเท่าไหร่", "I07", "SALES_OR_H2_REVIEW"),
    ("ยังไม่ได้รับของเลย ขอเลขพัสดุ", "I12", "H1_INFORMATION_INQUIRY"),
    ("ขอเปลี่ยนที่อยู่ผู้รับ", "I13", "H1_INFORMATION_INQUIRY"),
    ("รหัสไม่ถูก ใส่ code ไม่ได้", "I10", "H1_INFORMATION_INQUIRY"),
    ("สมัครเข้าร่วมกิจกรรม", "I16", "H1_INFORMATION_INQUIRY"),
    ("เพจของคุณจึงถูกบล็อก ยืนยันบัญชี", None, "H3_SECURITY_HOLD"),
]


@pytest.mark.parametrize("text,expected_intent", RECALL_GAINS)
def test_recall_gained(text, expected_intent):
    result = classify_v2(text, "")
    predicted = {result["primary_intent"], *result["secondary_intents"]}
    assert expected_intent in predicted, f"{text!r} -> {predicted}, route={result['route']}"
    assert result["primary_intent"] != "I99"


@pytest.mark.parametrize("text,expected_intent,expected_route", NO_REGRESSION)
def test_no_regression(text, expected_intent, expected_route):
    result = classify_v2(text, "")
    if expected_intent is not None:
        assert result["primary_intent"] == expected_intent, (
            f"{text!r} -> primary {result['primary_intent']} (expected {expected_intent})"
        )
    assert result["route"] == expected_route, (
        f"{text!r} -> route {result['route']} (expected {expected_route})"
    )
