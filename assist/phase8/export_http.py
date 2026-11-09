"""Password-protected CSV download, so results can be seen from a browser.

GET /export                 readable page: counts by category and day, latest questions
GET /export/summary         text counts by category and day (from the case table)
GET /export/cases.csv       one row per case: time, category, route, status (no text)
GET /export/collected.csv   scrubbed question text + category (only if ASSIST_STORE_TEXT=1)

Disabled (404) unless ASSIST_EXPORT_PASSWORD is set. Uses HTTP Basic auth: the
browser asks for a login, type any user name and the password. Serve it over
HTTPS only. The files never contain customer identity; the collected text can
still hold names or addresses typed by customers, so read it before sharing.
"""

from __future__ import annotations

import base64
import hmac
from collections import Counter
from html import escape

from phase8.config import Config
from phase8.ops_delivery import INTENT_LABEL
from phase8.tools.export_collected import (
    ExportError, cases_csv_text, cases_summary, collected_csv_text, fetch, fetch_cases,
)

HTML = "text/html; charset=utf-8"
CSV = "text/csv; charset=utf-8"
TEXT = "text/plain; charset=utf-8"


def _authorized(auth_header: str, password: str) -> bool:
    if not auth_header.lower().startswith("basic "):
        return False
    try:
        decoded = base64.b64decode(auth_header[6:].strip()).decode("utf-8")
    except Exception:
        return False
    supplied = decoded.partition(":")[2]
    return hmac.compare_digest(supplied.encode("utf-8"), password.encode("utf-8"))


_PAGE_CSS = (
    "body{font:15px/1.5 system-ui,'Segoe UI',Tahoma,sans-serif;margin:0;padding:24px;background:#fafaf7;color:#0e1116}"
    "h1{font-size:22px;margin:0 0 4px}h2{font-size:16px;margin:28px 0 8px}p.sub{color:#6b6f76;margin:0 0 16px}"
    "table{border-collapse:collapse;width:100%;max-width:1000px;background:#fff}"
    "th,td{border:1px solid #d9d6cb;padding:6px 10px;text-align:left;vertical-align:top}th{background:#f2f1eb}"
    ".bar{display:inline-block;height:10px;background:#1e4fa8;vertical-align:middle;margin-right:8px}"
    ".num{text-align:right;white-space:nowrap}.wrap{overflow-x:auto}a{color:#1e4fa8}"
)


def _label(code: str | None) -> str:
    code = code or ""
    name = INTENT_LABEL.get(code, "")
    return "%s (%s)" % (name, code) if name else (code or "-")


def render_view(cases: list[tuple], collected: list[tuple] | None) -> str:
    """cases: (opened_at,intent,route,status); collected: (at,channel,text,intent,route) or None."""
    e = escape
    total = len(cases)
    by_intent = Counter(r[1] or "-" for r in cases)
    by_day = Counter(r[0][:10] for r in cases)
    out = ["<!doctype html><html lang=th><meta charset=utf-8>",
           "<meta name=viewport content='width=device-width,initial-scale=1'>",
           "<title>WakuFlow Assist: ผลที่เก็บได้</title><style>%s</style>" % _PAGE_CSS,
           "<h1>ผลที่เก็บได้</h1><p class=sub>จำนวนเคส %d &middot; ไม่มีข้อมูลตัวตนลูกค้า</p>" % total,
           "<h2>แยกตามหมวด</h2><div class=wrap><table><tr><th>หมวด<th class=num>จำนวน<th>สัดส่วน"]
    for code, n in by_intent.most_common():
        pct = (n / total * 100) if total else 0
        out.append("<tr><td>%s<td class=num>%d<td><span class=bar style='width:%dpx'></span>%.0f%%"
                   % (e(_label(code)), n, int(pct * 2), pct))
    out.append("</table></div><h2>แยกตามวัน</h2><div class=wrap><table><tr><th>วัน<th class=num>จำนวน")
    for day, n in sorted(by_day.items(), reverse=True):
        out.append("<tr><td>%s<td class=num>%d" % (e(day), n))
    out.append("</table></div>")
    if collected is not None:
        out.append("<h2>คำถามล่าสุด (สูงสุด 100 ข้อ)</h2><div class=wrap><table>"
                   "<tr><th>เวลา (UTC)<th>ช่องทาง<th>คำถาม<th>ระบบจัดเป็น")
        for at, channel, text, intent, _route in reversed(collected[-100:]):
            out.append("<tr><td>%s<td>%s<td>%s<td>%s" % (e(at), e(channel), e(text), e(_label(intent))))
        out.append("</table></div><p class=sub>ชื่อและที่อยู่ที่ลูกค้าพิมพ์เองอาจหลุดอยู่ในคำถาม ตรวจก่อนส่งต่อ</p>")
    else:
        out.append("<p class=sub>ไม่ได้เปิดเก็บข้อความคำถาม (ASSIST_STORE_TEXT)</p>")
    out.append("<h2>ดาวน์โหลด</h2><p><a href='/export/cases.csv'>cases.csv</a>")
    if collected is not None:
        out.append(" &middot; <a href='/export/collected.csv'>collected.csv</a>")
    out.append(" &middot; <a href='/export/summary'>summary</a></p>")
    return "".join(out)


def export_response(path: str, auth_header: str, cfg: Config) -> tuple[int, dict[str, str], bytes]:
    """Return (status, headers, body) for a GET under /export/."""
    if not cfg.export_password:
        return 404, {"Content-Type": TEXT}, b"not found"
    if not _authorized(auth_header or "", cfg.export_password):
        return 401, {"Content-Type": TEXT, "WWW-Authenticate": 'Basic realm="WakuFlow export"'}, b"login required"
    try:
        if path in ("/export", "/export/", "/export/view"):
            page = render_view(fetch_cases(cfg.db_path), fetch(cfg.db_path) if cfg.store_text else None)
            return 200, {"Content-Type": HTML, "X-Content-Type-Options": "nosniff",
                         "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'"}, page.encode("utf-8")
        if path == "/export/summary":
            return 200, {"Content-Type": TEXT}, cases_summary(fetch_cases(cfg.db_path)).encode("utf-8")
        if path == "/export/cases.csv":
            body = cases_csv_text(fetch_cases(cfg.db_path)).encode("utf-8-sig")
            name = "cases.csv"
        elif path == "/export/collected.csv" and cfg.store_text:
            body = collected_csv_text(fetch(cfg.db_path)).encode("utf-8-sig")
            name = "collected.csv"
        else:
            return 404, {"Content-Type": TEXT}, b"not found"
    except ExportError as exc:
        return 404, {"Content-Type": TEXT}, str(exc).encode("utf-8")
    return 200, {"Content-Type": CSV, "Content-Disposition": 'attachment; filename="%s"' % name}, body
