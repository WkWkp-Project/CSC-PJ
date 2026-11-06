#!/usr/bin/env python3
"""
analyze_line.py — วิเคราะห์ไฟล์ export แชทกลุ่ม LINE (แยกทีละไฟล์ ไม่รวมกัน)

รองรับ 2 ฟอร์แมตที่เจอจริง:
  A) "Sino/แบรนด์"  — date header `2023.10.09 Monday`,  บรรทัดข้อความ `HH:MM ชื่อ ข้อความ...`
  B) "LINE WORKS/CS" — date header `Tuesday, September 23, 2025`, บรรทัด `HH:MM ชื่อ` แล้วข้อความบรรทัดถัดไป

วิเคราะห์อะไร (ต่อ 1 ไฟล์):
  - ช่วงเวลา / จำนวนวันที่คุยกัน / จำนวนข้อความ
  - ปริมาณข้อความรายเดือน (timeline)
  - จำนวนสื่อ/ไฟล์แนบ (รูป/วิดีโอ/สติกเกอร์/ไฟล์)
  - จำนวนข้อความรายคน (เฉพาะฟอร์แมต B ที่ชื่อคนแยกได้ชัด)
  - เวลาตอบกลับ (turnaround): CS ถาม → Wakuwaku ตอบ นานแค่ไหน (ฟอร์แมต B)
  - นับหัวข้อที่คุยกันด้วยคีย์เวิร์ด

⚠️ พิมพ์เฉพาะ "ตัวเลขสรุป" ไม่พ่นข้อความดิบ (มี PII) — ห้าม commit ไฟล์ดิบเข้า repo

การใช้งาน:
    python scripts/analyze_line.py <ไฟล์.txt> [<ไฟล์2.txt> ...]
    python scripts/analyze_line.py chat.txt --json out.json   # เก็บผลเป็น JSON (ตัวเลขล้วน)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, date
from pathlib import Path

# --- ตัวจับรูปแบบวันที่ 2 แบบ ---
RE_DATE_A = re.compile(r"^(\d{4})\.(\d{2})\.(\d{2})\s+\w+\s*$")            # 2023.10.09 Monday
RE_DATE_B = re.compile(r"^\w+,\s+([A-Za-z]+)\s+(\d{1,2}),\s+(\d{4})\s*$")   # Tuesday, September 23, 2025
RE_TIME = re.compile(r"^(\d{1,2}):(\d{2})\s?(.*)$")                          # HH:MM (เนื้อที่เหลือ)

MONTHS = {m: i for i, m in enumerate(
    ["January","February","March","April","May","June","July",
     "August","September","October","November","December"], 1)}

# สื่อ/ระบบ ที่ LINE แสดงเป็นข้อความ
MEDIA_MARKERS = ["Photos", "Photo", "Videos", "Video", "Sticker", "Stickers",
                 "[Photo]", "[Sticker]", "[Video]", "[File]", "Voice message", "Call",
                 "Location", "Contact"]
FILE_EXT = re.compile(r"\.(pptx|pdf|xlsx|docx|zip|rar|png|jpg|jpeg|mp4|csv)\b", re.I)

# หัวข้อที่คุยกัน (นับแบบหยาบ ปรับได้)
TOPICS = {
    "โปรโมชั่น/แคมเปญ": ["โปรโมชั่น", "โปรโมชัน", "แคมเปญ", "campaign", "promotion", "โปร"],
    "คอนเทนต์/โพสต์": ["content", "คอนเทนต์", "โพส", "โพสต์", "aw", "seeding", "artwork", "album"],
    "ของรางวัล/แลกของ": ["รางวัล", "แลกของ", "ของแถม", "truemoney", "ทรูมันนี่", "บัตร", "แต้ม", "สะสม"],
    "พัสดุ/จัดส่ง": ["พัสดุ", "จัดส่ง", "เลขไปรษณีย์", "tracking", "ขนส่ง", "ส่งของ"],
    "ราคา/สั่งซื้อ": ["ราคา", "สั่งซื้อ", "ยกลัง", "ขายส่ง", "สต็อก", "stock", "order"],
    "กิจกรรม/เวิร์คช็อป": ["กิจกรรม", "เวิร์คช็อป", "เวิร์กช็อป", "workshop", "อบรม", "เชฟ", "คลาส"],
    "เคลม/ปัญหา": ["เคลม", "ปัญหา", "ร้องเรียน", "ของเสีย", "ไม่ได้รับ"],
    "ประสานงาน/นัดหมาย": ["ประสาน", "นัด", "ติดตาม", "รบกวน", "อัพเดท", "อัปเดต", "สรุป"],
}


def parse_file(path: Path):
    """คืน (fmt, messages) โดย messages = list ของ dict {dt, sender, text}."""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()

    # ตรวจฟอร์แมตจาก date header ที่เจอมากกว่า
    a = sum(1 for ln in lines if RE_DATE_A.match(ln))
    b = sum(1 for ln in lines if RE_DATE_B.match(ln))
    fmt = "A" if a >= b else "B"

    messages = []
    cur_date = None
    cur = None  # ข้อความที่กำลังต่อบรรทัด

    def flush():
        nonlocal cur
        if cur:
            messages.append(cur)
            cur = None

    for ln in lines:
        mA = RE_DATE_A.match(ln)
        mB = RE_DATE_B.match(ln)
        if mA:
            flush()
            cur_date = date(int(mA.group(1)), int(mA.group(2)), int(mA.group(3)))
            continue
        if mB:
            flush()
            cur_date = date(int(mB.group(3)), MONTHS.get(mB.group(1), 1), int(mB.group(2)))
            continue

        mt = RE_TIME.match(ln)
        if mt and cur_date:
            flush()
            hh, mm, rest = int(mt.group(1)), int(mt.group(2)), mt.group(3).strip()
            dt = datetime(cur_date.year, cur_date.month, cur_date.day, min(hh, 23), mm)
            if fmt == "B":
                # rest = ชื่อผู้ส่ง (ข้อความอยู่บรรทัดถัดไป)
                cur = {"dt": dt, "sender": rest, "text": ""}
            else:
                # fmt A: "ชื่อ ข้อความ" ปนกัน — แยกชื่อไม่ชัด เก็บทั้งก้อนเป็น text
                cur = {"dt": dt, "sender": None, "text": rest}
            continue

        # บรรทัดต่อเนื่องของข้อความเดิม
        if cur is not None:
            cur["text"] = (cur["text"] + "\n" + ln).strip() if cur["text"] else ln.strip()
    flush()
    return fmt, messages


def is_media(text: str) -> bool:
    t = text.strip()
    if t in MEDIA_MARKERS:
        return True
    if FILE_EXT.search(t):
        return True
    return False


def analyze(path: Path) -> dict:
    fmt, msgs = parse_file(path)
    msgs = [m for m in msgs if m["dt"]]
    if not msgs:
        return {"file": path.name, "error": "ไม่พบข้อความ"}

    msgs.sort(key=lambda m: m["dt"])
    dates = sorted({m["dt"].date() for m in msgs})
    monthly = Counter(m["dt"].strftime("%Y-%m") for m in msgs)
    media = sum(1 for m in msgs if is_media(m["text"]))

    # หัวข้อ
    topic = Counter()
    for m in msgs:
        low = m["text"].lower()
        for name, kws in TOPICS.items():
            if any(k in low for k in kws):
                topic[name] += 1

    result = {
        "file": path.name,
        "format": fmt,
        "date_range": [dates[0].isoformat(), dates[-1].isoformat()],
        "active_days": len(dates),
        "total_messages": len(msgs),
        "media_messages": media,
        "text_messages": len(msgs) - media,
        "avg_chars": round(sum(len(m["text"]) for m in msgs) / len(msgs), 1),
        "monthly": dict(sorted(monthly.items())),
        "topics": dict(topic.most_common()),
    }

    # ฟอร์แมต B: ผู้ส่ง + เวลาตอบกลับ
    if fmt == "B":
        senders = Counter(m["sender"] for m in msgs if m["sender"])
        result["participants"] = dict(senders.most_common())

        # ฝั่ง CS = ชื่อมีคำว่า CS ; ฝั่ง Wakuwaku = ที่เหลือ
        def side(s): return "cs" if s and re.search(r"\bcs\b|cs", s, re.I) else "waku"
        turnarounds = []  # นาที: CS พูด → ฝั่งตรงข้ามตอบ
        last_cs = None
        for m in msgs:
            s = side(m["sender"])
            if s == "cs":
                last_cs = m["dt"]
            elif s == "waku" and last_cs is not None:
                delta = (m["dt"] - last_cs).total_seconds() / 60.0
                if 0 <= delta <= 60 * 24 * 30:  # กันค่าเพี้ยน >30 วัน
                    turnarounds.append(delta)
                last_cs = None
        if turnarounds:
            turnarounds.sort()
            n = len(turnarounds)
            result["response"] = {
                "pairs": n,
                "median_min": round(turnarounds[n // 2], 1),
                "p90_min": round(turnarounds[min(n - 1, int(n * 0.9))], 1),
                "within_1h_pct": round(sum(1 for t in turnarounds if t <= 60) * 100 / n, 1),
                "within_24h_pct": round(sum(1 for t in turnarounds if t <= 1440) * 100 / n, 1),
                "over_24h_pct": round(sum(1 for t in turnarounds if t > 1440) * 100 / n, 1),
            }
    return result


def print_report(r: dict):
    print("=" * 60)
    print(f"📄 {r['file']}  (ฟอร์แมต {r.get('format','?')})")
    if "error" in r:
        print("   ⚠️", r["error"]); return
    d0, d1 = r["date_range"]
    print(f"   ช่วงเวลา: {d0} → {d1}  ·  วันที่มีแชท: {r['active_days']} วัน")
    print(f"   ข้อความรวม: {r['total_messages']:,}  (สื่อ/ไฟล์ {r['media_messages']:,} · ข้อความ {r['text_messages']:,})")
    print(f"   ความยาวเฉลี่ย: {r['avg_chars']} ตัวอักษร/ข้อความ")
    if "participants" in r:
        print("   ผู้ส่งข้อความ (สูงสุด 6):")
        for name, c in list(r["participants"].items())[:6]:
            print(f"      {c:>5}  {name}")
    if "response" in r:
        rp = r["response"]
        print("   ⏱️ เวลา CS รอ Wakuwaku ตอบ:")
        print(f"      คู่ถาม-ตอบ {rp['pairs']} ครั้ง · กลาง {rp['median_min']} นาที · p90 {rp['p90_min']} นาที")
        print(f"      ตอบใน 1 ชม.: {rp['within_1h_pct']}%  ·  ใน 24 ชม.: {rp['within_24h_pct']}%  ·  เกิน 24 ชม.: {rp['over_24h_pct']}%")
    print("   หัวข้อที่คุยกัน (บนสุด):")
    for name, c in list(r["topics"].items())[:6]:
        print(f"      {c:>5}  {name}")


def main() -> int:
    ap = argparse.ArgumentParser(description="วิเคราะห์แชทกลุ่ม LINE แยกทีละไฟล์")
    ap.add_argument("files", nargs="+")
    ap.add_argument("--json", help="เขียนผลรวมเป็นไฟล์ JSON (ตัวเลขล้วน ไม่มีข้อความดิบ)")
    args = ap.parse_args()

    results = []
    for f in args.files:
        r = analyze(Path(f))
        results.append(r)
        print_report(r)
    if args.json:
        Path(args.json).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n💾 เขียนผลลง {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
