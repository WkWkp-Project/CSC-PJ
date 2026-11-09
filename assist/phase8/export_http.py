"""Password-protected CSV download, so results can be seen from a browser.

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

from phase8.config import Config
from phase8.tools.export_collected import (
    ExportError, cases_csv_text, cases_summary, collected_csv_text, fetch, fetch_cases,
)

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


def export_response(path: str, auth_header: str, cfg: Config) -> tuple[int, dict[str, str], bytes]:
    """Return (status, headers, body) for a GET under /export/."""
    if not cfg.export_password:
        return 404, {"Content-Type": TEXT}, b"not found"
    if not _authorized(auth_header or "", cfg.export_password):
        return 401, {"Content-Type": TEXT, "WWW-Authenticate": 'Basic realm="WakuFlow export"'}, b"login required"
    try:
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
