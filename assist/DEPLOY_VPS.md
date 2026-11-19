# Deploy บน VPS (รันตลอด 24 ชม.)

ใช้ได้กับ VPS เจ้าไหนก็ได้ที่ได้ **root/SSH**, เป็น **KVM**, มี IP สาธารณะ และเปิดพอร์ต 80/443 ได้
(เช่น HostAtom Cloud VPS ถ้าตอบ 3 ข้อนี้ได้) ตัวอย่างใช้ **Debian 12** เพราะมี Python 3.11 มาให้ ไม่ต้องลงเพิ่ม
ระบบรัน **เครื่องเดียว** เท่านั้น (state อยู่ในหน่วยความจำ + SQLite)

## 0. เตรียม
- โดเมนหรือซับโดเมน (เช่น `assist.yourbrand.com`) ชี้ **A record** มาที่ IP ของ VPS (จำเป็นสำหรับ HTTPS)

## 1. ติดตั้ง (ล็อกอิน SSH แล้วรันด้วย root)
```bash
apt update && apt install -y python3 git sqlite3 caddy ufw
# ถ้า apt ไม่พบ caddy ให้ติดตั้งตามเอกสารของ Caddy
useradd --system --create-home --shell /usr/sbin/nologin waku
git clone -b claude/csc-pj-connect-3d20y0 https://github.com/WkWkp-Project/CSC-PJ /opt/wakuflow
mkdir -p /var/lib/wakuflow /var/backups/wakuflow
chown -R waku:waku /var/lib/wakuflow
python3 --version   # ต้องเป็น 3.11 ขึ้นไป
```

## 2. ไฟล์ตัวแปรลับ `/etc/wakuflow.env`
```bash
nano /etc/wakuflow.env     # ใส่ตามด้านล่าง
chmod 600 /etc/wakuflow.env
```
```
PORT=8080
ASSIST_DB_PATH=/var/lib/wakuflow/assist.db
ASSIST_HMAC_SECRET=สตริงสุ่มยาวอย่างน้อย32ตัว
ASSIST_TENANT_ID=tulip
LINE_CHANNEL_SECRET=
LINE_CHANNEL_ACCESS_TOKEN=
LINE_TARGET_GROUP_ID=
FB_APP_SECRET=
FB_PAGE_TOKEN=
FB_PAGE_ID=
FB_VERIFY_TOKEN=
```
(ช่องที่ยังไม่มีเว้นว่างไว้ได้ ระบบจะทำงานแบบ dry-run)

## 3. ให้รันอัตโนมัติ (systemd) `/etc/systemd/system/wakuflow.service`
```
[Unit]
Description=WakuFlow Assist
After=network.target

[Service]
User=waku
WorkingDirectory=/opt/wakuflow/assist
EnvironmentFile=/etc/wakuflow.env
Environment=PYTHONPATH=/opt/wakuflow/assist
ExecStart=/usr/bin/python3 -m phase8.webhook_server
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```
```bash
systemctl daemon-reload && systemctl enable --now wakuflow
systemctl status wakuflow
```

## 4. HTTPS ด้วย Caddy `/etc/caddy/Caddyfile`
```
assist.yourbrand.com {
    reverse_proxy localhost:8080
}
```
```bash
systemctl restart caddy
```

## 5. ไฟร์วอลล์ (ปิดพอร์ต 8080 จากภายนอก)
```bash
ufw allow 22 && ufw allow 80 && ufw allow 443 && ufw enable
```

## 6. ตรวจ
- เปิด `https://assist.yourbrand.com/healthz` ต้องได้ JSON
- Webhook URL: `https://assist.yourbrand.com/webhook/line` และ `/webhook/meta`
- ดู log (groupId ของ LINE จะโผล่ที่นี่): `journalctl -u wakuflow -f`

## 7. สำรองฐานข้อมูลทุกวัน
ใช้เครื่องมือในตัว (ไม่ต้องติดตั้ง sqlite3 เพิ่ม) สำรองแบบปลอดภัยแม้ระบบกำลังทำงาน ตรวจความสมบูรณ์ของไฟล์ และลบไฟล์เก่าเกิน 14 ชุดให้เอง
```bash
echo '30 3 * * * root cd /opt/wakuflow && PYTHONPATH=. python3 -m phase8.tools.backup_db --src /var/lib/wakuflow/assist.db --dest /var/backups/wakuflow --keep 14 >> /var/log/wakuflow-backup.log 2>&1' > /etc/cron.d/wakuflow-backup
```
ทดสอบรันทันทีหนึ่งครั้ง ต้องขึ้น `backup ok: ...`
```bash
cd /opt/wakuflow && PYTHONPATH=. python3 -m phase8.tools.backup_db --src /var/lib/wakuflow/assist.db --dest /var/backups/wakuflow
```
กู้คืน: `systemctl stop wakuflow` แล้วก๊อปไฟล์สำรองทับ `/var/lib/wakuflow/assist.db` แล้ว `systemctl start wakuflow`
ไฟล์สำรองอยู่ในเครื่องเดียวกัน ควรก๊อปออกไปเก็บนอกเครื่องเป็นครั้งคราว (snapshot ของผู้ให้เช่าอาจทับของเดิมทุกสัปดาห์)

## 7.1 แจ้งเตือนเข้า LINE เมื่อระบบล่ม
ตัวเช็กรันทุกนาที แจ้งเข้ากลุ่มเดียวกับใบแจ้งงานเมื่อ `/healthz` ไม่ตอบ 2 ครั้งติด และแจ้งอีกครั้งเมื่อกลับมา (ไม่แจ้งซ้ำรัวๆ)
```bash
echo '* * * * * root cd /opt/wakuflow && set -a && . /etc/wakuflow.env && set +a && PYTHONPATH=. python3 -m phase8.tools.watchdog --url http://127.0.0.1:8080/healthz --state /var/lib/wakuflow/watchdog.json' > /etc/cron.d/wakuflow-watchdog
```
ข้อจำกัด: ตัวเช็กรันบนเครื่องเดียวกัน ถ้าทั้งเครื่องหรือเน็ตล่มจะแจ้งไม่ได้ ให้ตั้งบริการเช็กจากภายนอกฟรี (เช่น UptimeRobot) ชี้ไปที่ `https://assist.yourbrand.com/healthz` เพิ่มอีกชั้น

## 7.2 หน้านโยบายความเป็นส่วนตัว (สำหรับ Meta App Review)
ตั้งสองค่านี้ใน `/etc/wakuflow.env` แล้วรีสตาร์ท หน้าจะเปิดที่ `/privacy` และ `/data-deletion` (ถ้าไม่ตั้ง จะเป็น 404)
```
ASSIST_COMPANY_NAME=ชื่อบริษัทตามจริง
ASSIST_CONTACT_EMAIL=อีเมลที่รับเรื่องข้อมูลส่วนบุคคล
```
ข้อความในหน้าเขียนตามที่โปรแกรมทำจริง แต่เป็นข้อความตั้งต้น ไม่ใช่คำปรึกษากฎหมาย ให้ผู้รับผิดชอบของบริษัทอ่านก่อนยื่น Meta และถ้าพฤติกรรมของโปรแกรมเปลี่ยนต้องแก้ข้อความตาม

## 8. อัปเดตโค้ด
```bash
cd /opt/wakuflow && git pull && systemctl restart wakuflow
```
ทำช่วงที่ลูกค้าทักน้อย: ข้อความที่ยังไม่ถึง 30 วินาทีของการรอรวมข้อความจะหายตอนรีสตาร์ท
