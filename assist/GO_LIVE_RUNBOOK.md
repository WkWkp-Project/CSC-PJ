# WakuFlow Assist — Go-Live Runbook (เฟส 1: รับ → จัดหมวด → ส่งใบแจ้งงานเข้า LINE)

> เป้าหมายเฟส 1: ระบบ **รับข้อความ → จัดหมวด → ส่ง "ใบแจ้งงาน" เข้า LINE กลุ่มทีม**
> (ยังไม่ตอบลูกค้าเอง = ไม่ต้องรอแบรนด์เติม FAQ)

สัญลักษณ์: 👤=คุณ/ทีม · 🏢=พาร์ทเนอร์/แอดมินเพจ · 🤖=โค้ด(เสร็จแล้ว) · ✅=จุดตรวจ

---

## STAGE 0 — เตรียม (ก่อนเริ่ม)
- [ ] 👤 ตัดสินใจ **host** ที่จะรันเซิร์ฟเวอร์ (ต้องมี HTTPS + รัน 24ชม.) เช่น Render / Railway / Fly.io / VPS + Caddy
- [ ] 👤 เลือก/สร้าง **LINE กลุ่มทีม** ที่จะรับใบแจ้งงาน (เชิญ bot เข้ากลุ่มทีหลัง)
- [ ] 👤 กำหนดคน: ใครเฝ้ากลุ่ม, SLA กี่นาที, ใครมีสิทธิ์แอดมินเพจ FB/LINE
- [ ] 👤 สุ่ม `ASSIST_HMAC_SECRET` (≥32 ตัว): `python3 -c "import secrets;print(secrets.token_hex(24))"`

---

## STAGE 1 — สร้างฝั่ง Facebook (Meta)  🏢
1. [ ] ไป **developers.facebook.com** → My Apps → **Create App** → ประเภท **Business**
2. [ ] ในแอป → **Add Product** → **Messenger** และ **Webhooks**
3. [ ] Messenger → Settings → **Generate Page Access Token** (เลือกเพจ Tulip)
       → ⚠️ **แปลงเป็น Page Token ถาวร** (ใช้ Graph API Explorer / long-lived flow)
4. [ ] จดค่า: **App Secret** (Settings → Basic), **Page ID**, ตั้ง **Verify Token** เอง (string อะไรก็ได้)
5. [ ] (ทำหลัง Deploy มี URL แล้ว) Webhooks → **Callback URL** = `https://<โดเมน>/webhook/meta`,
       **Verify Token** = ที่ตั้งไว้ → กด Verify → **Subscribe เพจ** → ติ๊ก field **messages**
6. [ ] ถ้าจะรับจาก **ลูกค้าทั่วไป** (ไม่ใช่แค่แอดมิน) → ยื่น **App Review → Advanced Access** ของ `pages_messaging` (เริ่มเลยยิ่งดี เพราะรอนาน)

**ได้มา 4 ค่า:** `FB_APP_SECRET` `FB_PAGE_TOKEN` `FB_PAGE_ID` `FB_VERIFY_TOKEN`

---

## STAGE 2 — สร้างฝั่ง LINE  🏢
1. [ ] ไป **developers.line.biz** → สร้าง/เลือก Provider → สร้าง **Messaging API channel** ให้ OA ของ Tulip
2. [ ] Basic settings → จด **Channel Secret**
3. [ ] Messaging API → **Issue Channel Access Token** (แบบ long-lived) → จดไว้
4. [ ] **manager.line.biz** → OA ของ Tulip → Response settings → ปิด **Auto-reply** / **Greeting**, ตั้ง response mode = **Bot/Webhook**
5. [ ] (ทำหลัง Deploy) Messaging API → **Webhook URL** = `https://<โดเมน>/webhook/line` → เปิด **Use webhook = ON** → Verify
6. [ ] เชิญ **bot (OA) เข้า LINE กลุ่มทีม** → หา **groupId** (ดูได้จาก log webhook ตอนมีข้อความในกลุ่ม)

**ได้มา 3 ค่า:** `LINE_CHANNEL_SECRET` `LINE_CHANNEL_ACCESS_TOKEN` `LINE_TARGET_GROUP_ID`

---

## STAGE 3 — Deploy เซิร์ฟเวอร์  👤
1. [ ] คัดลอก `.env.example` → `.env` แล้วเติมค่าที่ได้จาก Stage 1-2 (ที่มี; ที่ยังไม่มีเว้นว่างได้)
2. [ ] `docker compose up -d --build`  (หรือ deploy โค้ดนี้ขึ้น host ที่เลือก)
3. [ ] ✅ เปิด `https://<โดเมน>/healthz` → ดู JSON สถานะ (บอกว่าเหลือต้องเติมอะไร)

---

## STAGE 4 — ต่อ Webhook (กลับไปทำข้อ 5 ของ Stage 1 และ 2)  🏢👤
1. [ ] ตั้ง Callback URL ฝั่ง Meta + กด Verify (เซิร์ฟเวอร์จะตอบ challenge อัตโนมัติ)
2. [ ] ตั้ง Webhook URL ฝั่ง LINE + เปิด Use webhook + Verify
3. [ ] ✅ ทั้งสองฝั่งขึ้น "Success/Verified"

---

## STAGE 5 — Smoke test (ยิงข้อความจริงจากแอดมิน)  👤
1. [ ] ทักเพจ Tulip ด้วยบัญชีแอดมิน: พิมพ์ "ราคาเท่าไหร่"
2. [ ] รอ ~30 วินาที (debounce)
3. [ ] ✅ ใบแจ้งงานเด้งเข้า **LINE กลุ่มทีม** (ถ้ายังไม่ใส่ LINE token = ดูใน log แบบ dry-run)
4. [ ] ทดสอบเคสอ่อนไหว: "แพ้ถั่วไหม" → ✅ ใบแจ้งงานติดธง "ส่งคน/ทีมแบรนด์"

---

## STAGE 6 — Shadow observe 3-5 วัน  👤
- [ ] เปิดรับจริงแต่ **คนยังตอบลูกค้าเองทุกเคส** — ใช้ใบแจ้งงานเป็นตัวช่วย
- [ ] ดูว่าจัดหมวดแม่นไหม, มีเคสหลุด/ผิดหมวดไหม, ปริมาณต่อวันเท่าไร
- [ ] ✅ ปรับ keyword/FAQ เพิ่มตามที่เจอจริง (แก้ `classifier_ext.py` / `build_kb_draft.py` แล้วรันใหม่)

---

## STAGE 7 — เปิดใช้เฟส 1 เต็มตัว  👤
- [ ] ✅ `healthz` แสดง `can_go_live_phase1: true`
- [ ] ประกาศทีม: ใบแจ้งงานเข้า LINE กลุ่มแล้ว ใช้แทนการสรุปด้วยมือ
- [ ] ตั้งการเฝ้า server ล่ม (uptime monitor ยิง `/healthz`)

---

## ถัดไป (เฟส 2-3 — ทำเมื่อพร้อม)
- เฟส 2: แบรนด์เติมคำตอบใน `kb_brand_fill.csv` → เปิดโหมด **suggest** (คนกดส่ง)
- เฟส 3: เปิดโหมด **auto** เฉพาะ FAQ ที่ชัวร์ + ผ่านเกณฑ์ (confidence สูง, ไม่มีคำเสี่ยง)

---

## สรุป critical path
```
🤖 โค้ด: เสร็จแล้ว (49 เทสต์ผ่าน)
🏢 token FB+LINE  ─┐
👤 host/deploy    ─┼─► Stage 3-5 (~1 วัน) ─► Shadow 3-5 วัน ─► เปิดเฟส 1
🏢 App Review*    ─┘   (*เฉพาะรับลูกค้าทั่วไป: +3-14 วัน)
```
```
ถ้าได้ token+host แล้วทดสอบในทีม → ส่งใบแจ้งงานได้ ~1 สัปดาห์
ถ้าต้องรอ Meta review (ลูกค้าทั่วไป) → ~2-3 สัปดาห์
```
