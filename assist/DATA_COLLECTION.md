# เก็บข้อมูลเพื่อวัดและปรับระบบ (ไม่ต้องเทรนโมเดล)

ระบบเป็น keyword + FAQ ไม่มีการเทรน ข้อมูลใช้ 3 อย่าง: วัดความแม่น, หา keyword ที่ขาด, เขียนคำตอบ FAQ

## ขั้นตอน
1. คัดลอกข้อความลูกค้าจริง (Messenger/LINE) ใส่ไฟล์ CSV ตามแบบ `templates/labeled_template.csv`
   คอลัมน์: `text, true_intent, staff_reply, needs_human`
2. ลบข้อมูลส่วนตัว:
   `PYTHONPATH=. python3 -m phase8.tools.anonymize data/raw.csv data/clean.csv --column text --column staff_reply`
   แล้ว **เปิดอ่านไฟล์ clean.csv เอง** ชื่อคนและที่อยู่ไม่ถูกตรวจจับ
3. ให้คนติดป้าย `true_intent` (I01-I18 หรือ I99 = ทักทาย/ไม่ชัด) ให้คนที่รู้งานจริงเป็นคนติด
4. วัดผล:
   `PYTHONPATH=. python3 -m phase8.tools.evaluate data/clean.csv --misses data/misses.csv`
5. ดู `misses.csv` → เพิ่ม keyword ใน `phase8/classifier_ext.py` → วัดใหม่ → ทำซ้ำ

## กติกา
- เก็บไฟล์ไว้ใน `assist/data/` (ถูก .gitignore กันไว้แล้ว) ห้าม commit ข้อมูลลูกค้า
- ลบข้อมูลส่วนตัวก่อนส่งให้ใครดู รวมถึงแชทกลุ่มทีม
- หมวดเสี่ยง (I03/I07/I14: สุขภาพ ร้องเรียน คืนเงิน) เก็บให้ครบทุกเคสที่มี
- ตัวเลขความแม่นจะเชื่อถือได้เมื่อมีข้อความต่อหมวดมากพอ (เริ่มที่ ~30 ต่อหมวดที่พบบ่อย)
