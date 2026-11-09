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
`/usr/local/bin/wakuflow-backup.sh`:
```bash
#!/bin/sh
sqlite3 /var/lib/wakuflow/assist.db ".backup '/var/backups/wakuflow/assist-$(date +%F).db'"
find /var/backups/wakuflow -name 'assist-*.db' -mtime +14 -delete
```
```bash
chmod +x /usr/local/bin/wakuflow-backup.sh
echo '30 3 * * * root /usr/local/bin/wakuflow-backup.sh' > /etc/cron.d/wakuflow-backup
```
ควรก๊อปไฟล์สำรองออกไปเก็บนอกเครื่องเป็นครั้งคราว

## 8. อัปเดตโค้ด
```bash
cd /opt/wakuflow && git pull && systemctl restart wakuflow
```
ทำช่วงที่ลูกค้าทักน้อย: ข้อความที่ยังไม่ถึง 30 วินาทีของการรอรวมข้อความจะหายตอนรีสตาร์ท
