#!/usr/bin/env python3
"""
classify_conversations.py — แยกประเภทการคุยของแต่ละบทสนทนา

รับไฟล์ JSON รายคนจาก export_messenger.py แล้วจัดหมวดว่าเป็นการคุยประเภทไหน
(ถามราคา / ช่องทางซื้อ / เคลม / ขายส่ง / ต้องส่งแบรนด์ ฯลฯ) ตามที่ README วิเคราะห์ไว้

โหมด:
  - rule-based (ค่าเริ่มต้น): จับคีย์เวิร์ด ฟรี รันได้ทันที ไม่ต้องต่อเน็ต
  - ai (--mode ai): ส่งแต่ละแชทให้ Claude API จัดหมวด + สรุป intent (แม่นกว่า เคสกำกวม)

การใช้งาน:
    python scripts/classify_conversations.py --in exports
    python scripts/classify_conversations.py --in exports --mode ai   # ต้องมี ANTHROPIC_API_KEY

ผลลัพธ์:
    exports/classified.csv   ← ตารางสรุป: ลูกค้า | ประเภท | จำนวนข้อความ | สรุปสั้น
    exports/category_stats.csv ← สรุป %: ประเภท | จำนวน | % | ตอบเองได้ไหม
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

# --------------------------------------------------------------------------- #
# นิยามประเภท + คีย์เวิร์ด (rule-based) — ปรับแก้ได้ตามข้อมูลจริง
# ลำดับสำคัญ: เช็คจากบนลงล่าง เจ้าแรกที่ match ชนะ (เรียงจากเฉพาะเจาะจง→ทั่วไป)
# --------------------------------------------------------------------------- #
CATEGORIES = [
    # (ชื่อประเภท, [คีย์เวิร์ด], AI ตอบเองได้ไหม)
    ("เคลม/ปัญหาสินค้า", ["เคลม", "ของเสีย", "ชำรุด", "แตก", "ไม่ทำงาน", "คืนเงิน", "เปลี่ยนสินค้า", "ปัญหา"], "🟠 ต้องส่งคน"),
    ("บัตร/ของรางวัล", ["บัตร", "รางวัล", "แลกของ", "truemoney", "ทรูมันนี่", "โค้ด", "สแกนไม่ได้", "code"], "🟠 ต้องส่งคน"),
    ("ติดตามพัสดุ", ["พัสดุ", "เลขแทร็ค", "tracking", "ส่งของ", "ของยัง", "ได้ของ", "ขนส่ง", "kerry", "flash", "ไปรษณีย์"], "🟡 กึ่งอัตโนมัติ"),
    ("ขายส่ง/ราคาส่ง", ["ขายส่ง", "ราคาส่ง", "ส่งมีไหม", "ตัวแทน", "จำนวนมาก", "ขั้นต่ำ", "wholesale"], "✅ AI ตอบได้"),
    ("ช่องทางซื้อ", ["ซื้อที่ไหน", "ที่ไหน", "shopee", "ช้อปปี้", "lazada", "ลาซาด้า", "สาขา", "หน้าร้าน", "มีขายที่"], "✅ AI ตอบได้"),
    ("ถามราคา", ["ราคา", "เท่าไหร่", "เท่าไร", "กี่บาท", "กี่บ", "price", "โปร", "ลด", "ส่วนลด"], "✅ AI ตอบได้"),
    ("ข้อมูลสินค้า", ["ส่วนผสม", "ใช้ยังไง", "วิธีใช้", "สรรพคุณ", "เลิกผลิต", "มีสี", "ขนาด", "รุ่น", "สเปค", "มีกลิ่น"], "✅ AI ตอบได้"),
    ("สอบถามทั่วไป/ทักทาย", ["สวัสดี", "สอบถาม", "ขอถาม", "hello", "hi", "ครับ", "ค่ะ"], "✅ AI ตอบได้"),
]
FALLBACK = ("อื่นๆ/จัดหมวดไม่ได้", "🟠 ต้องส่งคน")


def classify_rule(messages: list[dict]) -> tuple[str, str]:
    """รวมข้อความฝั่งลูกค้าแล้วจับคีย์เวิร์ด."""
    cust_text = " ".join(
        m.get("text", "").lower() for m in messages if m.get("from") == "ลูกค้า"
    )
    for name, keywords, answerable in CATEGORIES:
        if any(kw.lower() in cust_text for kw in keywords):
            return name, answerable
    return FALLBACK


def summarize_rule(messages: list[dict]) -> str:
    """สรุปสั้นแบบง่าย = ข้อความแรกของลูกค้า."""
    for m in messages:
        if m.get("from") == "ลูกค้า" and m.get("text"):
            t = m["text"].strip().replace("\n", " ")
            return t[:80] + ("…" if len(t) > 80 else "")
    return "(ไม่มีข้อความลูกค้า)"


# --------------------------------------------------------------------------- #
# โหมด AI — ใช้ Claude API (ทางเลือก)
# --------------------------------------------------------------------------- #
def classify_ai(messages: list[dict], api_key: str) -> tuple[str, str, str]:
    """คืน (ประเภท, ตอบเองได้ไหม, สรุปสั้น) โดยให้ Claude จัดหมวด."""
    try:
        from anthropic import Anthropic
    except ImportError:
        print("❌ โหมด ai ต้องติดตั้งก่อน: pip install anthropic", file=sys.stderr)
        raise SystemExit(1)

    client = Anthropic(api_key=api_key)
    cat_list = "\n".join(f"- {c[0]} ({c[2]})" for c in CATEGORIES)
    transcript = "\n".join(f"{m['from']}: {m.get('text','')}" for m in messages)[:4000]

    prompt = (
        "คุณเป็นผู้ช่วยวิเคราะห์แชทลูกค้าของแบรนด์เครื่องสำอาง Tulip\n"
        "จัดประเภทบทสนทนาต่อไปนี้เป็น 1 ประเภทจากรายการนี้ (เลือกที่ตรงที่สุด):\n"
        f"{cat_list}\n- อื่นๆ/จัดหมวดไม่ได้ (🟠 ต้องส่งคน)\n\n"
        f"บทสนทนา:\n{transcript}\n\n"
        'ตอบเป็น JSON เท่านั้น: {"category": "...", "summary": "สรุปสั้น 1 ประโยค"}'
    )
    resp = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    text = resp.content[0].text.strip()
    # ดึง JSON ออกมา (เผื่อมีข้อความห่อ)
    start, end = text.find("{"), text.rfind("}")
    obj = json.loads(text[start:end + 1])
    category = obj.get("category", FALLBACK[0])
    answerable = next((c[2] for c in CATEGORIES if c[0] == category), FALLBACK[1])
    return category, answerable, obj.get("summary", "")


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description="แยกประเภทการคุยจากไฟล์แชทรายคน")
    ap.add_argument("--in", dest="indir", default="exports")
    ap.add_argument("--mode", choices=["rule", "ai"], default="rule")
    args = ap.parse_args()

    conv_dir = Path(args.indir) / "conversations"
    if not conv_dir.exists():
        print(f"❌ ไม่พบโฟลเดอร์ {conv_dir} (รัน export_messenger.py ก่อน)", file=sys.stderr)
        return 1

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if args.mode == "ai" and not api_key:
        print("❌ โหมด ai ต้องตั้งค่า ANTHROPIC_API_KEY ก่อน", file=sys.stderr)
        return 1

    files = sorted(conv_dir.glob("*.json"))
    print(f"🔎 กำลังแยกประเภท {len(files)} บทสนทนา (โหมด: {args.mode})")

    rows = []
    cat_counter = Counter()
    answerable_map = {}

    for i, fp in enumerate(files, 1):
        conv = json.loads(fp.read_text(encoding="utf-8"))
        messages = conv.get("messages", [])

        if args.mode == "ai":
            category, answerable, summary = classify_ai(messages, api_key)
        else:
            category, answerable = classify_rule(messages)
            summary = summarize_rule(messages)

        rows.append({
            "customer": conv.get("customer", fp.stem),
            "category": category,
            "answerable": answerable,
            "message_count": conv.get("message_count", len(messages)),
            "summary": summary,
        })
        cat_counter[category] += 1
        answerable_map[category] = answerable
        if i % 10 == 0 or i == len(files):
            print(f"  ...{i}/{len(files)}")

    out = Path(args.indir)
    # classified.csv — รายคน
    with (out / "classified.csv").open("w", encoding="utf-8-sig") as f:
        f.write("customer,category,answerable,message_count,summary\n")
        for r in rows:
            s = r["summary"].replace('"', "'")
            f.write(f'"{r["customer"]}","{r["category"]}","{r["answerable"]}",{r["message_count"]},"{s}"\n')

    # category_stats.csv — สรุป %
    total = sum(cat_counter.values()) or 1
    with (out / "category_stats.csv").open("w", encoding="utf-8-sig") as f:
        f.write("category,count,percent,answerable\n")
        for cat, cnt in cat_counter.most_common():
            f.write(f'"{cat}",{cnt},{cnt*100/total:.1f}%,"{answerable_map[cat]}"\n')

    print(f"\n✅ เสร็จ — สรุปประเภทการคุย:")
    for cat, cnt in cat_counter.most_common():
        print(f"   {cnt*100/total:5.1f}%  {cat:22s} ({cnt}) {answerable_map[cat]}")
    print(f"\n   รายคน: {out/'classified.csv'}")
    print(f"   สรุป%: {out/'category_stats.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
