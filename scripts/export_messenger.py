#!/usr/bin/env python3
"""
export_messenger.py — ดึงแชท Messenger ของเพจ (แยกรายคน) ย้อนหลัง N วัน

เป้าหมาย: ดึงบทสนทนาลูกค้าจากเพจ Facebook ผ่าน Graph API (Conversations API)
โดยได้ "ข้อความจริง" ครบทุกข้อความ + โหลดรูป/ไฟล์แนบเก็บทันที (กันลิงก์หมดอายุ)
และปิดบัง (mask) ข้อมูลส่วนตัวก่อนบันทึก ตามข้อกำหนด PDPA ใน README ข้อ 8

⚠️ รันบน "เครื่องของคุณ" เท่านั้น — ข้อมูลลูกค้าจริงไม่ควรผ่านที่อื่น
⚠️ output ทั้งหมดถูก .gitignore ไว้ — ห้าม commit ข้อมูลดิบเข้า repo

การใช้งาน:
    export FB_PAGE_TOKEN="xxxx"      # Page Access Token (ดูคู่มือ docs/messenger-export-guide.md)
    export FB_PAGE_ID="xxxx"         # Page ID (ตัวเลข)
    python scripts/export_messenger.py --days 90

ตัวเลือก:
    --days N         จำนวนวันย้อนหลัง (ค่าเริ่มต้น 90)
    --out DIR        โฟลเดอร์ผลลัพธ์ (ค่าเริ่มต้น ./exports)
    --no-images      ไม่ต้องโหลดรูป (ดึงเฉพาะข้อความ เร็วกว่า)
    --no-mask        ไม่ต้อง mask PII (ไม่แนะนำ — ใช้เฉพาะ debug)
    --api-version V  เวอร์ชัน Graph API (ค่าเริ่มต้น v21.0)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError

GRAPH = "https://graph.facebook.com"
# ดึงข้อความทีละหน้า หน่วงเวลากัน rate limit
PAGE_DELAY_SEC = 0.6
RETRY = 4


# --------------------------------------------------------------------------- #
# ยูทิลิตี้เรียก Graph API
# --------------------------------------------------------------------------- #
def api_get(url: str) -> dict:
    """เรียก URL เต็ม (รวม access_token แล้ว) พร้อม retry แบบ exponential backoff."""
    last_err = None
    for attempt in range(RETRY):
        try:
            req = Request(url, headers={"User-Agent": "csc-pj-exporter/1.0"})
            with urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            # 4 = rate limit, 17 = user request limit, 613 = calls limit
            if e.code in (429, 500, 503) or '"code":4' in body or '"code":17' in body:
                wait = 2 ** attempt
                print(f"  ⏳ โดน rate limit / server error รอ {wait}s แล้วลองใหม่...", file=sys.stderr)
                time.sleep(wait)
                last_err = RuntimeError(f"HTTP {e.code}: {body[:300]}")
                continue
            raise RuntimeError(f"Graph API error HTTP {e.code}: {body[:500]}") from e
        except URLError as e:
            wait = 2 ** attempt
            print(f"  ⏳ network error ({e.reason}) รอ {wait}s...", file=sys.stderr)
            time.sleep(wait)
            last_err = e
    raise RuntimeError(f"เรียก API ไม่สำเร็จหลัง retry {RETRY} ครั้ง: {last_err}")


def build_url(path: str, token: str, api_version: str, **params) -> str:
    params["access_token"] = token
    return f"{GRAPH}/{api_version}/{path}?{urlencode(params)}"


# --------------------------------------------------------------------------- #
# การ mask ข้อมูลส่วนตัว (PII) — ตาม README ข้อ 8
# --------------------------------------------------------------------------- #
# เบอร์โทรไทย, เลข TrueMoney/บัตร, เลขพัสดุ ฯลฯ
_PHONE_RE = re.compile(r"(?<!\d)(0\d{1,2}[-\s]?\d{3}[-\s]?\d{3,4})(?!\d)")
_LONGNUM_RE = re.compile(r"(?<!\d)(\d{9,})(?!\d)")            # เลขยาว (บัตร/บัญชี)
_TRACKING_RE = re.compile(r"\b([A-Z]{2}\d{6,}[A-Z]{2})\b")   # เลขพัสดุ เช่น RN646...TH
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def mask_pii(text: str | None) -> str | None:
    if not text:
        return text
    text = _EMAIL_RE.sub("[EMAIL]", text)
    text = _TRACKING_RE.sub(lambda m: f"[TRACKING:{m.group(1)[:2]}…{m.group(1)[-2:]}]", text)
    text = _PHONE_RE.sub("[PHONE]", text)
    # เก็บ 4 ตัวท้ายไว้พอให้ผูกเคสได้ แต่ไม่เผยเต็ม
    text = _LONGNUM_RE.sub(lambda m: f"[NUM…{m.group(1)[-4:]}]", text)
    return text


def mask_name(name: str | None, idx: int) -> str:
    """แทนชื่อลูกค้าด้วยรหัสนิรนาม (คงลำดับเดิมไว้ผูกเคส)."""
    return f"ลูกค้า_{idx:03d}"


# --------------------------------------------------------------------------- #
# โหลดรูป/ไฟล์แนบเก็บทันที (ลิงก์ Facebook หมดอายุเร็ว)
# --------------------------------------------------------------------------- #
def download_attachment(url: str, dest: Path) -> bool:
    try:
        req = Request(url, headers={"User-Agent": "csc-pj-exporter/1.0"})
        with urlopen(req, timeout=60) as resp:
            dest.write_bytes(resp.read())
        return True
    except Exception as e:  # noqa: BLE001 — เก็บรูปพลาดไม่ควรล้มทั้งงาน
        print(f"    ⚠️ โหลดไฟล์แนบไม่สำเร็จ: {e}", file=sys.stderr)
        return False


# --------------------------------------------------------------------------- #
# ดึงบทสนทนาทั้งหมด (ไล่ pagination จนเกิน cutoff)
# --------------------------------------------------------------------------- #
def iter_conversations(token: str, page_id: str, api_version: str):
    """yield conversation dict ทีละอัน (เรียงใหม่→เก่า)."""
    url = build_url(
        f"{page_id}/conversations",
        token,
        api_version,
        platform="messenger",
        fields="id,updated_time,participants,message_count",
        limit=50,
    )
    while url:
        data = api_get(url)
        for conv in data.get("data", []):
            yield conv
        url = data.get("paging", {}).get("next")
        if url:
            time.sleep(PAGE_DELAY_SEC)


def fetch_messages(token: str, conv_id: str, api_version: str, cutoff: datetime):
    """ดึงข้อความทั้งหมดของ 1 บทสนทนา จนถึง cutoff (หยุดเมื่อเจอข้อความเก่ากว่า)."""
    url = build_url(
        f"{conv_id}/messages",
        token,
        api_version,
        fields="id,message,created_time,from,attachments{name,mime_type,image_data,file_url}",
        limit=100,
    )
    messages = []
    reached_cutoff = False
    while url and not reached_cutoff:
        data = api_get(url)
        for msg in data.get("data", []):
            created = parse_time(msg.get("created_time"))
            if created and created < cutoff:
                reached_cutoff = True
                break
            messages.append(msg)
        if reached_cutoff:
            break
        url = data.get("paging", {}).get("next")
        if url:
            time.sleep(PAGE_DELAY_SEC)
    return messages


def parse_time(s: str | None) -> datetime | None:
    if not s:
        return None
    # Facebook ส่งรูปแบบ 2026-08-15T14:32:00+0000
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S%z")
    except ValueError:
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None


def fmt_time(dt: datetime | None) -> str:
    if not dt:
        return ""
    return dt.astimezone(timezone(timedelta(hours=7))).strftime("%Y-%m-%d %H:%M")  # เวลาไทย


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description="ดึงแชท Messenger ของเพจแยกรายคน")
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--out", default="exports")
    ap.add_argument("--no-images", action="store_true")
    ap.add_argument("--no-mask", action="store_true")
    ap.add_argument("--api-version", default="v21.0")
    args = ap.parse_args()

    token = os.environ.get("FB_PAGE_TOKEN")
    page_id = os.environ.get("FB_PAGE_ID")
    if not token or not page_id:
        print("❌ ต้องตั้งค่า FB_PAGE_TOKEN และ FB_PAGE_ID ก่อน (ดู docs/messenger-export-guide.md)",
              file=sys.stderr)
        return 1

    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
    out_dir = Path(args.out)
    conv_dir = out_dir / "conversations"
    img_dir = out_dir / "images"
    conv_dir.mkdir(parents=True, exist_ok=True)
    if not args.no_images:
        img_dir.mkdir(parents=True, exist_ok=True)

    print(f"🚀 เริ่มดึงแชทเพจ {page_id} ย้อนหลัง {args.days} วัน (ตั้งแต่ {fmt_time(cutoff)})")
    print(f"   mask PII: {'ปิด ⚠️' if args.no_mask else 'เปิด ✅'} | โหลดรูป: {'ปิด' if args.no_images else 'เปิด'}")

    summary_rows = []
    total_msgs = 0
    idx = 0

    for conv in iter_conversations(token, page_id, args.api_version):
        conv_id = conv["id"]
        idx += 1
        print(f"[{idx}] {conv_id} ...", end=" ", flush=True)

        try:
            raw_messages = fetch_messages(token, conv_id, args.api_version, cutoff)
        except Exception as e:  # noqa: BLE001
            print(f"ข้าม (error: {e})")
            continue

        if not raw_messages:
            print("ไม่มีข้อความในช่วงเวลา ข้าม")
            continue

        # ชื่อลูกค้า = participant ที่ไม่ใช่เพจ
        participants = conv.get("participants", {}).get("data", [])
        cust_name = next((p.get("name") for p in participants if p.get("id") != page_id), None)
        display_name = mask_name(cust_name, idx) if not args.no_mask else (cust_name or f"user_{idx}")

        messages_out = []
        for m in reversed(raw_messages):  # เรียงเก่า→ใหม่ให้อ่านง่าย
            sender = m.get("from", {}) or {}
            is_page = sender.get("id") == page_id
            text = m.get("message", "")
            if not args.no_mask:
                text = mask_pii(text)

            attachments_out = []
            for att in (m.get("attachments", {}) or {}).get("data", []):
                url = None
                img = att.get("image_data") or {}
                if img.get("url"):
                    url = img["url"]
                elif att.get("file_url"):
                    url = att["file_url"]
                fname = None
                if url and not args.no_images:
                    ext = ".jpg" if (att.get("mime_type") or "").startswith("image") else ".bin"
                    fname = f"{conv_id[:12]}_{m['id'][:10]}{ext}"
                    download_attachment(url, img_dir / fname)
                attachments_out.append({
                    "type": att.get("mime_type", "unknown"),
                    "saved_file": fname,
                })

            messages_out.append({
                "from": "เพจ" if is_page else "ลูกค้า",
                "time": fmt_time(parse_time(m.get("created_time"))),
                "text": text,
                "attachments": attachments_out,
            })

        conv_out = {
            "conversation_id": conv_id,
            "customer": display_name,
            "message_count": len(messages_out),
            "first_message": messages_out[0]["time"] if messages_out else "",
            "last_message": messages_out[-1]["time"] if messages_out else "",
            "messages": messages_out,
        }

        safe_name = re.sub(r"[^\w฀-๿-]", "_", display_name)
        (conv_dir / f"{safe_name}.json").write_text(
            json.dumps(conv_out, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        total_msgs += len(messages_out)
        summary_rows.append((display_name, len(messages_out),
                             conv_out["first_message"], conv_out["last_message"]))
        print(f"บันทึก {len(messages_out)} ข้อความ")

    # เขียน summary.csv
    summary_path = out_dir / "summary.csv"
    with summary_path.open("w", encoding="utf-8-sig") as f:
        f.write("customer,message_count,first_message,last_message\n")
        for name, cnt, first, last in summary_rows:
            f.write(f'"{name}",{cnt},"{first}","{last}"\n')

    print(f"\n✅ เสร็จ: {idx} บทสนทนา, {total_msgs} ข้อความ")
    print(f"   ไฟล์รายคน: {conv_dir}/")
    print(f"   สรุป: {summary_path}")
    print(f"\nขั้นต่อไป: python scripts/classify_conversations.py --in {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
