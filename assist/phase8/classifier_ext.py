"""Phase 8 - keyword recall extension for the rule-based classifier.

Without an AI model, classification is pure keyword matching, so a real customer
who phrases a question in words the rules don't list falls through to I99
(unclassified). This file adds synonyms and natural phrasings observed in the
chat research, so more messages land on the right intent on the keyword path
alone.

SAFETY: additions only go to LOW-priority intents (product info, price, channel,
usage, availability, campaign info, events). Because the classifier chooses the
PRIMARY intent by a fixed priority order, adding keywords to a low-priority
intent can never steal a message away from a higher-priority one - a safety or
complaint or wholesale message that also matches a new keyword still routes to
its original, higher-priority intent. The regression test in
``tests/test_classifier_ext.py`` proves this on a sentinel set.

``classifier_v2`` merges these at import time; if this module is absent the
classifier is unchanged.
"""

from __future__ import annotations

# intent -> extra keyword/phrasing variants (substring match, already lowercased)
KEYWORD_ADDITIONS: dict[str, list[str]] = {
    # I01 product facts / composition
    "I01": ["dutch process", "cocoa", "ผงโกโก้", "เนื้อโกโก้", "แคลอรี", "ไขมัน", "โปรตีน"],
    # I02 usage / preparation / storage
    "I02": ["ละลาย", "แช่แข็ง", "อัตราส่วน", "วิธีชง", "เสิร์ฟ", "อุ่น"],
    # I04 retail price / shipping fee / promotion
    "I04": ["กี่บาท", "แพงไหม", "ลดราคา", "โปรโมชัน", "ส่วนลด", "ส่งฟรี"],
    # I05 where / how to buy
    "I05": ["สั่งซื้อ", "สั่งยังไง", "สาขา", "tiktok", "เว็บไซต์", "มีขายที่ไหน"],
    # I06 availability / restock
    "I06": ["restock", "สินค้าหมด", "พร้อมส่ง", "ของขาด"],
    # I09 campaign / reward info
    "I09": ["แคมเปญ", "ลุ้นรางวัล", "สแกน", "ร่วมสนุก"],
    # I15 events / workshops / booths
    "I15": ["อีเวนต์", "event", "งานแฟร์", "สาธิต", "เทศกาล", "สอนทำ"],
}
