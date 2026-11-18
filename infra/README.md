# Platform: PostgreSQL + Caddy บน VPS (สำหรับโปรแกรมไม่เกิน ~5 ตัว)

PostgreSQL ตัวเดียวใช้ร่วมกัน โดยแต่ละโปรแกรมได้ **database และผู้ใช้ของตัวเอง** เห็นข้อมูลของโปรแกรมอื่นไม่ได้
โปรแกรมจะเป็น Node, Docker image หรืออย่างอื่น รันเป็น container เหมือนกันหมด

```
อินเทอร์เน็ต ──443──> Caddy (HTTPS อัตโนมัติ) ──> โปรแกรม 1..5 (container) ──> PostgreSQL
                                                                      (ไม่เปิดสู่อินเทอร์เน็ต)
```

## ที่ทดสอบแล้ว / ยังไม่ได้ทดสอบ
- ทดสอบกับ PostgreSQL 16 ตัวจริง: สร้าง database ต่อโปรแกรม (โปรแกรมหนึ่งเปิด database ของอีกตัวไม่ได้ และไม่ใช่ superuser), สำรองข้อมูล, กู้คืน
- **ยังไม่ได้รัน** `docker-compose.yml` จริง (เครื่องที่ผมใช้ไม่มี Docker daemon) ตรวจแค่ไวยากรณ์ ครั้งแรกบน VPS อาจต้องแก้เล็กน้อย

## ขนาดเครื่อง (ประมาณการ ยังไม่ได้วัดกับโปรแกรมจริง)
2 vCPU / 4 GB RAM / SSD 40 GB เหมาะกับโปรแกรมเล็ก 5 ตัว ถ้าเครื่อง 2 GB ก็พอได้ถ้าโปรแกรมเบามาก
ค่า `shared_buffers=256MB` ใน compose ตั้งไว้สำหรับ 2-4 GB ถ้าเปลี่ยนขนาดเครื่อง ปรับตามนั้น

## 0. ก่อนซื้อ VPS
ถามผู้ให้บริการ: เป็น **KVM** ไหม, ได้ **root/SSH** ไหม, ลง **Docker** ได้ไหม, เปิดพอร์ต **80/443** ได้ไหม
เตรียม **โดเมน** แล้วสร้าง A record ชี้ซับโดเมนของแต่ละโปรแกรมมาที่ IP ของ VPS (เช่น `s.yourbrand.com`, `influencer.yourbrand.com`)

## 1. เตรียมเครื่อง (แนะนำ Ubuntu 24.04 LTS; ใช้ Ubuntu 22.04 หรือ Debian 12 ก็ได้)
ล็อกอินเป็น root แล้วรันสคริปต์เตรียมเครื่อง (อัปเดตระบบ, ไฟร์วอลล์ 22/80/443, Docker, สร้างผู้ใช้ deploy):
```bash
ssh root@IP_ของ_VPS
curl -fsSL -o setup-vps.sh https://raw.githubusercontent.com/WkWkp-Project/CSC-PJ/claude/csc-pj-connect-3d20y0/infra/scripts/setup-vps.sh
less setup-vps.sh      # อ่านก่อนรัน (repo เป็น private: ถ้าโหลดไม่ได้ ให้ scp ไฟล์ขึ้นไปแทน)
bash setup-vps.sh deploy
```
สคริปต์ **ไม่ปิด** การล็อกอินด้วยรหัสผ่าน ให้เปิดเทอร์มินัลใหม่ทดสอบ `ssh deploy@IP` ให้ได้ก่อน
แล้วค่อยปิดเองใน `/etc/ssh/sshd_config` (`PasswordAuthentication no`) ไม่งั้นอาจล็อกตัวเองออกจากเครื่อง
หมายเหตุ: พอร์ตที่ Docker เปิด (`ports:`) ข้ามกฎของ `ufw` ดังนั้น **ห้ามใส่ `ports:` ให้ postgres** (ในไฟล์ไม่มี) มีแค่ Caddy ที่เปิด 80/443

## 2. วางชุดนี้บน VPS
```bash
sudo mkdir -p /opt/platform && sudo chown deploy /opt/platform
git clone -b claude/csc-pj-connect-3d20y0 https://github.com/WkWkp-Project/CSC-PJ /opt/platform/repo   # repo เป็น private ต้องล็อกอิน/ใช้ token ของ GitHub
cd /opt/platform/repo/infra
```
(หรืออัปโหลดโฟลเดอร์ `infra` ขึ้นไปด้วย `scp` ก็ได้)

## 3. ตั้งรหัสผ่านฐานข้อมูล
```bash
cp .env.example .env
nano .env        # POSTGRES_PASSWORD=ผลจาก: openssl rand -hex 24
chmod 600 .env
```

## 4. แก้ Caddyfile แล้วเปิดระบบ
แก้อีเมลในบรรทัด `email` ของ `Caddyfile` แล้วรัน
```bash
docker compose up -d
docker compose ps          # postgres ต้องเป็น healthy
```

## 5. สร้างฐานข้อมูลให้แต่ละโปรแกรม
```bash
./scripts/new-app-db.sh shortener
```
จะได้บรรทัด `DATABASE_URL=postgresql://shortener:รหัสสุ่ม@postgres:5432/shortener` คัดลอกไปใส่ `.env` ของโปรแกรมนั้นทันที (ไม่ได้เก็บรหัสไว้ที่อื่น) รันซ้ำกับชื่อเดิมจะไม่ทำอะไร

## 6. วางโปรแกรม
```bash
cp -r apps/_template apps/shortener
# ใส่โค้ดของโปรแกรมใน apps/shortener/ แก้ container_name, ใส่ DATABASE_URL ใน .env
cd apps/shortener && docker compose up -d --build && cd ../..
```
- **Node:** ใช้ `Dockerfile` ตัวอย่างใน `_template` (ปรับให้ตรงโปรแกรม)
- **โปรแกรมที่มี Docker image อยู่แล้ว:** ในไฟล์ compose เปลี่ยน `build: .` เป็น `image: ชื่อ-image`
- เพิ่มบล็อกใน `Caddyfile`:
  ```
  s.yourbrand.com {
      reverse_proxy shortener:3000
  }
  ```
  แล้วโหลดใหม่: `docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile`

## 7. สำรองข้อมูล (ต้องทำ)
```bash
sudo tee /etc/cron.d/platform-backup <<'CRON'
30 3 * * * root /opt/platform/repo/infra/scripts/backup.sh >> /var/log/platform-backup.log 2>&1
CRON
```
- ได้ไฟล์ใน `infra/backups/วันที่/` เก็บ 14 วัน (ปรับด้วย `KEEP_DAYS`)
- **ต้องคัดลอกออกนอกเครื่องเป็นประจำ** (เช่น `scp`, `rclone` ไป NAS หรือที่เก็บไฟล์อื่น) สำรองบนดิสก์เดียวกันไม่พอ
- ไฟล์ `globals.sql` มีค่าแฮชรหัสผ่านของผู้ใช้ฐานข้อมูล เก็บให้เป็นความลับ
- กู้คืน: `./scripts/restore.sh shortener backups/2026-11-18/shortener.dump` (แทนที่ข้อมูลทั้งหมดของ database นั้น)
- **ลองกู้คืนจริงสักครั้งก่อนไว้ใจ** สำรองที่ไม่เคยลองกู้ ยังไม่รู้ว่าใช้ได้

## 8. การดูแล
- อัปเดตระบบ: `sudo apt update && sudo apt -y upgrade` เป็นระยะ
- อัปเดต Caddy/Postgres รุ่นย่อย: `docker compose pull && docker compose up -d` (Postgres ปักรุ่น 16 ไว้ การขึ้นรุ่นใหญ่ต้อง dump แล้ว restore)
- เช็กพื้นที่ดิสก์ (`df -h`) และตั้ง uptime monitor ยิงหน้าเว็บของแต่ละโปรแกรม

## 9. ความปลอดภัย
- เข้า SSH ด้วยกุญแจ ปิดรหัสผ่าน
- ไฟร์วอลล์เปิดแค่ 22/80/443 และไม่เปิดพอร์ต Postgres
- แต่ละโปรแกรมใช้ผู้ใช้ฐานข้อมูลของตัวเอง ห้ามให้โปรแกรมใช้ `postgres` (superuser)
- ไฟล์ `.env` ห้าม commit ห้ามส่งในแชท

## ข้อจำกัดที่ต้องรู้
- **เครื่องเดียว = จุดล้มเหลวจุดเดียว** VPS ล่มหรือดิสก์พัง ทุกโปรแกรมหยุด ต้องพึ่งไฟล์สำรอง
- ตัวย่อ URL เป็นโปรแกรมที่ลิงก์ถูกส่งออกไปแล้ว ถ้าล่มลิงก์เปิดไม่ได้ ควรตั้ง monitor และสำรองข้อมูลถี่กว่าตัวอื่น
- **WakuFlow Assist** ตอนนี้เก็บข้อมูลใน SQLite ไม่ได้ใช้ Postgres วางเคียงกันบนเครื่องนี้ได้ (มี `assist/Dockerfile` เพิ่มบล็อกใน Caddyfile) การย้ายไป Postgres เป็นงานแก้โค้ดแยกต่างหาก
