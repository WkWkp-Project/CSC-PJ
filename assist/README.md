# WakuFlow Assist — เฟส 1 (รับ → จัดหมวด → ส่งใบแจ้งงานเข้า LINE)

ระบบผู้ช่วย CS สำหรับ Tulip บน Messenger + LINE ที่ **รับข้อความ → จัดหมวด (แยกงาน) → ส่ง "ใบแจ้งงาน" เข้า LINE กลุ่มทีม**
โดย **ยังไม่ตอบลูกค้าเอง** (ปลอดภัยสุด ไม่ต้องรอแบรนด์เติมคำตอบ) ใช้ keyword + KB ล้วน ยังไม่ต้องใช้ AI API

## โครงสร้าง
```
phase3/   กติกา keyword ตั้งต้น (INTENT_RULES) + state reference
phase5/   classifier_v2.py  — สมองจัดหมวด (rule-based, I01–I18)
phase6/   engine.py — รับ→รวบ(debounce)→จัด→route→สร้างใบแจ้งงาน (เก็บ SQLite)
          config/approved_kb.json          — KB ที่อนุมัติแล้ว (ระบบตอบจากอันนี้)
          config/kb_draft_from_research.json — FAQ 57 ร่าง (draft ยังไม่ live)
phase8/   ชั้น operation + go-live (งานใหม่)
          config.py          — ช่องกรอก token ทั้งหมด (จาก env)
          signatures.py      — ตรวจลายเซ็น Meta + LINE
          ops_delivery.py    — outbox ส่งใบแจ้งงาน (exactly-once + retry + SLA watchdog + safety net)
          suggestion.py      — โหมด "แนะนำคำตอบ" + ตัวดักคำเสี่ยง
          classifier_ext.py  — keyword เสริม (เพิ่ม recall แบบปลอดภัย)
          line_deliverer.py  — ส่งใบแจ้งงานเข้า LINE กลุ่ม (ว่าง=dry-run)
          pipeline.py        — ต่อท่อครบ + debounce + verify challenge
          webhook_server.py  — เซิร์ฟเวอร์ (stdlib ล้วน)
          build_kb_draft.py  — generator สร้าง FAQ (ยืนยัน routing กับ classifier)
          experiments/adversarial.py — ทดลองคำหลอก 70 เคส (0 อันตราย)
          tests/             — 49 เทสต์
```

## 3 โหมดการทำงาน (เลือกได้ต่อ FAQ)
- **A. Route** — ส่งใบแจ้งงานเฉยๆ คนตอบเอง
- **B. Suggest** — ใบแจ้งงาน + ร่างคำตอบ คนกดส่ง (ไม่ต้องใช้ AI)
- **C. Auto** — ระบบตอบเอง เฉพาะ FAQ ปลอดภัย + อนุมัติแล้ว

## ความปลอดภัยการจัดหมวด (5 ชั้น)
1. ลำดับความสำคัญ (safety/complaint/wholesale ชนะเสมอ)
2. ตัวดักคำเสี่ยงซ่อน (แพ้/เด็กกิน/คืนเงิน → บังคับส่งคน, ห้าม auto)
3. หมวดอันตราย (I03/I07/I14) ห้าม auto ตลอด
4. รูปภาพ → ส่งคนเสมอ
5. Safety net: จัดไม่ได้ (I99) → โต๊ะคัดแยก ไม่หายเงียบ

ผลทดลองคำหลอก 70 เคส: **ตอบผิดถึงลูกค้า = 0 (ปลอดภัย 100%)** ดู `reports/adversarial_report.csv`

## รันทดสอบ
```bash
cd assist && PYTHONPATH=. python3 -m pytest phase8/tests/ -q      # 49 tests
PYTHONPATH=. python3 phase8/experiments/adversarial.py            # adversarial report
```

## ขึ้นใช้งาน
1. `cp .env.example .env` แล้วเติม token (ดู `.env.example`)
2. `docker compose up -d --build`
3. เปิด `https://<โดเมน>/healthz` ดูสถานะความพร้อม
4. ทำตาม `GO_LIVE_RUNBOOK.md` ทีละขั้น

> ⚠️ ห้าม commit ไฟล์ `.env`, ฐานข้อมูล `*.db`, หรือข้อมูลแชทดิบ (มี PII) — มี .gitignore คุมไว้แล้ว
