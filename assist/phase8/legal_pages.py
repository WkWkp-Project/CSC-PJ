"""Public privacy-policy and data-deletion pages (needed for Meta App Review).

Served at /privacy and /data-deletion. They stay OFF (404) until
ASSIST_COMPANY_NAME and ASSIST_CONTACT_EMAIL are set, so a policy with blank
contact details is never published.

The wording describes what this program actually does (see engine.py,
collector.py, anonymize.py). It is a starting text, not legal advice: the
company's own legal owner should read it before it is submitted to Meta. If the
program's behaviour changes, change this text with it.
"""

from __future__ import annotations

import html
from typing import Any

PAGES = ("/privacy", "/data-deletion")

CSS = ("body{font-family:system-ui,'Noto Sans Thai',sans-serif;max-width:720px;margin:32px auto;"
       "padding:0 16px;line-height:1.7;color:#1c1c1c}h1{font-size:1.5rem}h2{font-size:1.15rem;margin-top:1.6em}"
       "table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:6px 10px;text-align:left}")


def _page(title: str, body_html: str) -> bytes:
    doc = ('<!doctype html><html lang="th"><head><meta charset="utf-8">'
           '<meta name="viewport" content="width=device-width,initial-scale=1">'
           '<title>%s</title><style>%s</style></head><body>%s</body></html>') % (
        html.escape(title), CSS, body_html)
    return doc.encode("utf-8")


def privacy_html(company: str, email: str, retention_days: int, collecting_text: bool) -> bytes:
    c, e = html.escape(company), html.escape(email)
    if collecting_text:
        stored = ("<li>ข้อความคำถามของลูกค้าที่ผ่านการลบข้อมูลติดต่อแล้ว (เบอร์โทร อีเมล ลิงก์ ไอดี LINE และตัวเลขยาว "
                  "ถูกแทนที่ด้วยเครื่องหมาย) เก็บคู่กับหมวดหมู่และเวลา <b>โดยไม่ผูกกับชื่อหรือรหัสผู้ส่ง</b> "
                  "เพื่อทำสถิติว่าลูกค้าถามเรื่องอะไรบ่อย เก็บไว้ %d วันแล้วลบอัตโนมัติ</li>") % retention_days
    else:
        stored = "<li>ขณะนี้ไม่มีการเก็บข้อความของลูกค้า</li>"
    body = """
<h1>นโยบายความเป็นส่วนตัว</h1>
<p>จัดทำโดย %(c)s ("เรา") สำหรับระบบช่วยคัดแยกข้อความลูกค้าที่รับข้อความจากเพจ Facebook ของเรา
ติดต่อเรื่องข้อมูลส่วนบุคคลได้ที่ <a href="mailto:%(e)s">%(e)s</a></p>

<h2>1. ระบบนี้ทำอะไร</h2>
<p>เมื่อคุณส่งข้อความถึงเพจของเรา ระบบจะอ่านข้อความนั้นเพื่อจัดหมวดหมู่เรื่องที่ถาม (เช่น ราคา พัสดุ ร้องเรียน)
แล้วแจ้งทีมงานของเราภายในกลุ่มแชตของทีมว่ามีเรื่องหมวดใดเข้ามาและเมื่อไร
<b>การแจ้งทีมไม่มีข้อความของคุณและไม่มีชื่อหรือตัวตนของคุณ</b>
ระบบไม่ตอบกลับคุณโดยอัตโนมัติ ทีมงานที่เป็นคนจริงตอบคุณในช่องทางเดิม</p>

<h2>2. ข้อมูลที่ระบบใช้และเก็บ</h2>
<ul>
<li>ข้อความที่คุณส่งถึงเพจ และรหัสผู้ส่งที่ Meta กำหนดให้ ใช้ชั่วคราวเพื่อรวมข้อความที่ส่งต่อเนื่องกันภายในประมาณ 30 วินาทีให้เป็นเรื่องเดียว</li>
<li>บันทึกของแต่ละเรื่อง: หมวดหมู่ที่จัดได้ เวลา และจำนวนตัวอักษร โดยรหัสผู้ส่งถูกแปลงเป็นรหัสย่อที่ย้อนกลับไม่ได้ และตัวข้อความไม่ถูกเก็บในบันทึกนี้</li>
%(stored)s
</ul>

<h2>3. ข้อมูลที่เราไม่ทำ</h2>
<ul>
<li>ไม่ขายหรือเปิดเผยข้อมูลให้บุคคลภายนอกเพื่อการโฆษณา</li>
<li>ไม่ส่งข้อความหรือตัวตนของคุณเข้ากลุ่ม LINE ของทีม (ส่งเฉพาะหมวดหมู่และเวลา)</li>
<li>ไม่ใช้ข้อมูลเพื่อติดตามคุณข้ามเว็บไซต์</li>
</ul>

<h2>4. ผู้ที่เกี่ยวข้อง</h2>
<p>ข้อความของคุณผ่านแพลตฟอร์ม Meta (Facebook Messenger) ตามนโยบายของ Meta เอง
ระบบของเรารันบนเซิร์ฟเวอร์ที่เราเช่าไว้ และใช้ LINE ส่งการแจ้งเตือนภายในทีม (ไม่มีข้อความลูกค้า)</p>

<h2>5. สิทธิของคุณ</h2>
<p>คุณขอทราบ ขอแก้ไข หรือขอลบข้อมูลของคุณได้ ดูวิธีที่ <a href="/data-deletion">/data-deletion</a>
หรือติดต่อ <a href="mailto:%(e)s">%(e)s</a></p>
""" % {"c": c, "e": e, "stored": stored}
    return _page("นโยบายความเป็นส่วนตัว - %s" % company, body)


def deletion_html(company: str, email: str, retention_days: int, collecting_text: bool) -> bytes:
    c, e = html.escape(company), html.escape(email)
    if collecting_text:
        anon = ("<p>ข้อความคำถามที่เก็บไว้เพื่อทำสถิติ <b>ไม่ได้ผูกกับชื่อหรือรหัสของผู้ส่ง</b> "
                "เราจึงค้นหาว่าข้อความใดเป็นของคุณไม่ได้เอง ถ้าคุณอยากให้ลบข้อความที่คุณเคยส่ง "
                "ให้แจ้งเราพร้อมระบุข้อความนั้นโดยประมาณ (หรือวันและเวลาที่ส่ง) เราจะลบรายการที่ตรงกัน "
                "ส่วนที่เหลือจะถูกลบอัตโนมัติเมื่อครบ %d วัน</p>") % retention_days
    else:
        anon = "<p>ขณะนี้เราไม่ได้เก็บข้อความของลูกค้า มีเพียงบันทึกหมวดหมู่และเวลาที่ไม่ระบุตัวตน</p>"
    body = """
<h1>การขอลบข้อมูล</h1>
<p>%(c)s</p>
<h2>วิธีขอลบ</h2>
<ol>
<li>ส่งอีเมลถึง <a href="mailto:%(e)s">%(e)s</a> หัวข้อ "ขอลบข้อมูล"</li>
<li>ระบุชื่อบัญชี Facebook ที่คุณใช้ทักเพจ (ถ้ามี) และสิ่งที่ต้องการให้ลบ</li>
<li>เราจะตอบรับและดำเนินการ แล้วแจ้งผลกลับทางอีเมล</li>
</ol>
%(anon)s
<p>ข้อความต้นฉบับที่อยู่ในแชตระหว่างคุณกับเพจ เป็นข้อมูลบนแพลตฟอร์ม Meta คุณจัดการได้ที่ Messenger หรือการตั้งค่าบัญชี Facebook ของคุณเอง</p>
<p><a href="/privacy">นโยบายความเป็นส่วนตัว</a></p>
""" % {"c": c, "e": e, "anon": anon}
    return _page("การขอลบข้อมูล - %s" % company, body)


def legal_response(path: str, cfg: Any) -> tuple[int, dict[str, str], bytes] | None:
    """None = not a legal page (caller carries on). 404 while the details are blank."""
    if path not in PAGES:
        return None
    if not (cfg.company_name and cfg.contact_email):
        return 404, {"Content-Type": "text/plain; charset=utf-8"}, b"not found"
    build = privacy_html if path == "/privacy" else deletion_html
    body = build(cfg.company_name, cfg.contact_email, cfg.text_retention_days, cfg.store_text)
    return 200, {"Content-Type": "text/html; charset=utf-8",
                 "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'"}, body
