# Deploy บน Synology NAS (Container Manager)

ยังไม่ได้ทดสอบบน Synology จริง ชื่อเมนูอาจต่างตามรุ่น DSM ให้ยึดชื่อที่เห็นบนหน้าจอเป็นหลัก

## 0. ตรวจก่อน
- NAS ต้องรองรับ Docker: Package Center → ค้นหา **Container Manager** (DSM 7.2 ขึ้นไป) หรือ **Docker** (รุ่นเก่า) ถ้าไม่มี แปลว่ารุ่นนี้ใช้ไม่ได้
- ต้องให้ LINE เข้าถึงจากอินเทอร์เน็ตได้ด้วย HTTPS เลือกทางใดทางหนึ่ง:
  - **ก. เปิดพอร์ตที่เราเตอร์ + DDNS ของ Synology** ใช้ได้ถ้ามี IP สาธารณะ (เทียบ IP ที่หน้าเราเตอร์กับผลค้นหา "what is my ip" ถ้าไม่ตรง แปลว่าอยู่หลัง CGNAT ทางนี้ใช้ไม่ได้)
  - **ข. Cloudflare Tunnel** ต้องมีโดเมน ไม่ต้องเปิดพอร์ต (ดูท้ายไฟล์)

## 1. เอาโค้ดขึ้น NAS
1. ใน File Station สร้างโฟลเดอร์ `docker/wakuflow` แล้วอัปโหลดเนื้อหาโฟลเดอร์ `assist` ทั้งหมดเข้าไป (ต้องเห็น `Dockerfile` อยู่ในโฟลเดอร์นี้)
2. สร้างไฟล์ `.env` ในโฟลเดอร์เดียวกัน โดยคัดลอกจาก `local.env.example` แล้วแก้ค่า (ไม่มีช่องว่างรอบ `=` บันทึกแบบ UTF-8 / LF)
   - ตั้ง `ASSIST_EXPORT_PASSWORD` เป็นรหัสยาวและสุ่ม เพราะหน้า `/export` จะเปิดสู่อินเทอร์เน็ต
3. เปลี่ยนชื่อ `docker-compose.synology.yml` เป็น `docker-compose.yml` (หรือเลือกไฟล์นี้ตอนสร้างโปรเจกต์)

## 2. รันด้วย Container Manager
Container Manager → **Project** → Create → ตั้งชื่อ `wakuflow` → เลือกโฟลเดอร์ `docker/wakuflow` → ใช้ไฟล์ compose ที่มี → Build/Start
- ตรวจ: ใน Container แท็บ Log ต้องเห็น `WakuFlow Assist webhook server on 0.0.0.0:8080`
- รันเครื่องเดียว (1 container) ห้ามขยายเป็นหลายตัว

## 3. HTTPS (ทาง ก.)
1. **DDNS:** Control Panel → External Access → DDNS → Add → Synology → ตั้งชื่อ เช่น `yourname.synology.me`
2. **ใบรับรอง:** Control Panel → Security → Certificate → Add → Let's Encrypt → ใส่ชื่อโดเมนข้างบน (ต้องให้พอร์ต 80 เข้าถึง NAS ได้ชั่วคราวระหว่างขอ)
3. **Reverse Proxy:** Control Panel → Login Portal → Advanced → Reverse Proxy → Create
   - Source: HTTPS, hostname `yourname.synology.me`, port 443
   - Destination: HTTP, `localhost`, port `8080`
   - กำหนดใบรับรองให้รายการนี้ (Settings → Certificate → Configure)
4. **เราเตอร์:** ส่งต่อพอร์ต 443 (และ 80 ตอนขอใบรับรอง) ไปที่ IP ของ NAS
5. ทดสอบจากนอกเครือข่าย (เช่น 4G มือถือ): `https://yourname.synology.me/healthz` ต้องได้ JSON

Webhook URL ของ LINE = `https://yourname.synology.me/webhook/line`

## 4. ความปลอดภัย
- เปิดสู่อินเทอร์เน็ตเฉพาะพอร์ต 443 ผ่าน reverse proxy อย่าเปิดหน้าจัดการ DSM (5000/5001)
- compose นี้ผูกพอร์ต 8080 ไว้ที่ NAS เองเท่านั้น (`127.0.0.1`) คนภายนอกเข้าได้ทางเดียวคือ reverse proxy
- เปิด 2-step verification ของบัญชี DSM และตั้ง Auto Block
- สำรอง `data/assist.db` (Hyper Backup หรือคัดลอกเป็นระยะ)
- ไฟดับ/เน็ตหลุด = หยุดรับข้อความ ข้อความช่วงนั้นหาย ถ้ามี UPS จะช่วยเรื่องไฟ

## 5. อัปเดตโค้ด
อัปโหลดไฟล์ใหม่ทับ (อย่าทับ `.env` และโฟลเดอร์ `data`) → Project → Build ใหม่ ทำช่วงที่ลูกค้าทักน้อย (ข้อความที่รอรวม 30 วินาทีอยู่ในหน่วยความจำ หายถ้ารีสตาร์ท)

## ทาง ข. Cloudflare Tunnel (ถ้ามีโดเมน / อยู่หลัง CGNAT)
สร้าง Tunnel ในหน้า Cloudflare Zero Trust ชี้ hostname ของคุณไปที่ `http://assist:8080` แล้วเพิ่ม container `cloudflared` ในโปรเจกต์เดียวกันด้วย token ของ tunnel
ไม่ต้องเปิดพอร์ตที่เราเตอร์ ผมยังไม่ได้เขียนไฟล์ compose ส่วนนี้ ถ้าต้องการบอกได้
