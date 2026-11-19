# คู่มือดึงแชท Messenger ของเพจ (90 วัน) เพื่อวิเคราะห์ประเภทการคุย

เอกสารนี้อธิบายวิธีดึงแชทลูกค้าจากเพจ Facebook (Tulip) แยกรายคนย้อนหลัง 90 วัน
เพื่อเอามา **แยกประเภทของการคุย** (ถามราคา / ช่องทางซื้อ / เคลม ฯลฯ) ตามเป้าหมายในโปรเจกต์

> 🔴 **ข้อมูลลูกค้ามี PII (ชื่อ/เบอร์/เลขบัตร)** — ทำตาม README ข้อ 8 เสมอ
> - รันสคริปต์บน **เครื่องของคุณ** เท่านั้น
> - ผลลัพธ์ทั้งหมดถูก `.gitignore` ไว้แล้ว — **ห้าม commit ข้อมูลดิบเข้า repo**

---

## เงื่อนไขก่อนเริ่ม

- [ ] คุณเป็น **แอดมินเพจ Tulip** (เข้า Business Suite เห็น Inbox ได้) ✅ ยืนยันแล้ว
- [ ] มี **Python 3.9+** บนเครื่อง (`python3 --version`)
- [ ] (โหมด AI เท่านั้น) มี `ANTHROPIC_API_KEY`

---

## ขั้น 1 — ขอ Page Access Token (ทำครั้งเดียว ~10 นาที)

1. เข้า [developers.facebook.com/apps](https://developers.facebook.com/apps) → **Create App** → ประเภท **Business**
2. ในแอป เพิ่ม product **Messenger**
3. เปิด [Graph API Explorer](https://developers.facebook.com/tools/explorer)
   - เลือกแอปที่สร้าง
   - **User or Page** → เลือก **เพจ Tulip** → กด **Get Page Access Token**
   - ติ๊ก permission: `pages_messaging`, `pages_read_engagement`, `pages_manage_metadata`
4. คัดลอก **token** ที่ได้
5. หา **Page ID**: ใน Explorer เรียก `GET /me?fields=id,name` ขณะเลือกเพจอยู่ → ได้เลข id

> ⏱️ Token จาก Explorer อายุสั้น (~1–2 ชม.) พอสำหรับรัน 1 รอบ
> ถ้าจะรันหลายรอบ/ยาว ให้แลกเป็น **long-lived token** (อายุ ~60 วัน):
> ```
> GET /oauth/access_token?grant_type=fb_exchange_token
>     &client_id={APP_ID}&client_secret={APP_SECRET}&fb_exchange_token={SHORT_TOKEN}
> ```

---

## ขั้น 2 — รันสคริปต์ดึงแชท (บนเครื่องคุณ)

```bash
# ตั้งค่าความลับ (อย่า commit ค่าเหล่านี้)
export FB_PAGE_TOKEN="วาง_token_ที่ได้"
export FB_PAGE_ID="วาง_page_id"

# ดึงย้อนหลัง 90 วัน (โหลดรูป + mask PII อัตโนมัติ)
python scripts/export_messenger.py --days 90
```

ตัวเลือกเพิ่มเติม:

| ตัวเลือก | ความหมาย |
| --- | --- |
| `--days 90` | จำนวนวันย้อนหลัง (ค่าเริ่มต้น 90) |
| `--out exports` | โฟลเดอร์ผลลัพธ์ |
| `--no-images` | ดึงเฉพาะข้อความ ไม่โหลดรูป (เร็วกว่า) |
| `--no-mask` | ไม่ mask PII (⚠️ ใช้เฉพาะ debug — ห้ามแชร์ผลลัพธ์) |

**ผลลัพธ์ที่ได้:**

```
exports/
├── conversations/
│   ├── ลูกค้า_001.json   ← แชทรายคน: ทุกข้อความ + เวลา + ใครส่ง + ไฟล์แนบ
│   ├── ลูกค้า_002.json
│   └── ...
├── images/               ← รูป/ไฟล์แนบที่โหลดเก็บทันที (กันลิงก์หมดอายุ)
└── summary.csv           ← สรุป: ใครคุยกี่ข้อความ ช่วงวันไหน
```

ตัวอย่างไฟล์รายคน:

```json
{
  "conversation_id": "t_xxx",
  "customer": "ลูกค้า_001",
  "message_count": 3,
  "messages": [
    { "from": "ลูกค้า", "time": "2026-08-15 14:32", "text": "ราคาส่งมีไหมคะ" },
    { "from": "เพจ",    "time": "2026-08-15 14:35", "text": "มีค่ะ ขั้นต่ำ 10 ชิ้น" }
  ]
}
```

---

## ขั้น 3 — แยกประเภทการคุย

### โหมด rule-based (ฟรี รันได้ทันที — แนะนำเริ่มตรงนี้)

```bash
python scripts/classify_conversations.py --in exports
```

### โหมด AI (แม่นกว่าในเคสกำกวม)

```bash
pip install anthropic
export ANTHROPIC_API_KEY="sk-ant-..."
python scripts/classify_conversations.py --in exports --mode ai
```

**ผลลัพธ์:**

```
exports/
├── classified.csv        ← รายคน: ลูกค้า | ประเภท | ตอบเองได้ไหม | สรุปสั้น
└── category_stats.csv     ← สรุป %: ประเภท | จำนวน | % | ตอบเองได้ไหม
```

ตัวอย่างสรุป (`category_stats.csv`):

| ประเภท | จำนวน | % | ตอบเองได้ไหม |
| --- | --- | --- | --- |
| ถามราคา | 38 | 32% | ✅ AI ตอบได้ |
| ช่องทางซื้อ | 25 | 21% | ✅ AI ตอบได้ |
| เคลม/ปัญหาสินค้า | 20 | 17% | 🟠 ต้องส่งคน |

ตารางนี้ตอบคำถามใหญ่ของโปรเจกต์: **"คำถามกี่ % ที่ AI ตอบเองได้"**
เอาไปทำสไลด์นำเสนอได้ (README ข้อ 7)

---

## ปรับแต่งประเภท

หมวดและคีย์เวิร์ดอยู่ในตัวแปร `CATEGORIES` ที่หัวไฟล์
`scripts/classify_conversations.py` — แก้/เพิ่มได้ตามข้อมูลจริงที่เจอ

---

## ข้อจำกัดที่ควรรู้

| เรื่อง | สถานะ |
| --- | --- |
| ข้อความตัวอักษร | ✅ ได้ครบ |
| รูป/ไฟล์แนบ | ✅ โหลดเก็บทันที |
| ข้อความที่ถูกลบ/unsend | ❌ Facebook ไม่คืนให้ |
| สติกเกอร์/GIF | 🟡 ขึ้นเป็น attachment ไม่ใช่ text |
| ย้อนหลัง 90 วันครบ 100% | 🟡 ขึ้นกับ retention ของเพจ — ต้องลองรันจริง |

---

## แก้ปัญหาที่พบบ่อย

| อาการ | วิธีแก้ |
| --- | --- |
| `ต้องตั้งค่า FB_PAGE_TOKEN` | ยังไม่ได้ `export` ตัวแปร (ขั้น 2) |
| โดน rate limit บ่อย | สคริปต์ retry อัตโนมัติอยู่แล้ว รอสักครู่ / ลด limit |
| Token หมดอายุกลางคัน | แลกเป็น long-lived token (ขั้น 1) แล้วรันใหม่ |
| รูปโหลดไม่ได้บางไฟล์ | ลิงก์อาจหมดอายุ — สคริปต์ข้ามให้ ไม่ล้มทั้งงาน |
| ภาษาไทยเพี้ยนตอนเปิด CSV | เปิดด้วย Excel แล้วเลือก encoding UTF-8 (ไฟล์ใส่ BOM ให้แล้ว) |
