# Deploy บน Railway (เทส / เฟส 1)

ระบบต้องรัน **instance เดียวเท่านั้น** (state อยู่ในหน่วยความจำ + SQLite ไฟล์เดียว) ห้ามตั้ง replica > 1
ข้อความที่ยังไม่ถึง debounce 30 วินาทีจะหายถ้ารีสตาร์ท → deploy ช่วงที่ไม่มีลูกค้าทัก

## สิ่งที่โค้ดเตรียมไว้แล้ว
- `railway.json` — build จาก Dockerfile, 1 replica, healthcheck `/healthz`, restart เมื่อล้ม
- อ่าน `PORT` จาก env เอง, bind `0.0.0.0`
- DB default `/app/data/assist.db` (ตรงกับจุด mount volume)

## ขั้นตอน (ต้องทำในบัญชี Railway ของคุณ)
1. railway.app → ล็อกอินด้วย GitHub → New Project → Deploy from GitHub repo → `CSC-PJ`
2. Service → Settings
   - Root Directory = `assist`
   - Branch = `main` (หรือ `claude/csc-pj-connect-3d20y0` ถ้ายังไม่ merge)
   - Config as Code path = `/assist/railway.json` (path นี้นับจาก root ของ repo ไม่ตาม Root Directory)
   - Region = Singapore
3. Volumes → New Volume → Mount path = `/app/data`
4. Variables (ใส่ใน dashboard ไม่ใช้ไฟล์ .env; ห้ามตั้ง `PORT`):
   - `ASSIST_HMAC_SECRET` (สุ่ม ≥32 ตัว), `ASSIST_TENANT_ID=tulip`
   - `FB_VERIFY_TOKEN`, `FB_APP_SECRET`, `FB_PAGE_TOKEN`, `FB_PAGE_ID`
   - `LINE_CHANNEL_SECRET`, `LINE_CHANNEL_ACCESS_TOKEN`, `LINE_TARGET_GROUP_ID`
   - ค่าที่ยังไม่มีเว้นได้ → ระบบเป็น dry-run
5. Settings → Networking → Generate Domain → เปิด `https://<โดเมน>/healthz`
6. Meta Callback URL = `https://<โดเมน>/webhook/meta` · LINE Webhook URL = `https://<โดเมน>/webhook/line`
7. เทสตาม `GO_LIVE_RUNBOOK.md` Stage 5
