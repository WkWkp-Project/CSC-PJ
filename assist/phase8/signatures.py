"""Webhook signature verification for Meta and LINE.

Every inbound webhook must be proven to come from the real platform before it is
processed, using the App Secret (Meta) / Channel Secret (LINE). A blank secret
means "not configured" -> verification fails closed (returns False), never
silently passes.
"""

from __future__ import annotations

import base64
import hashlib
import hmac


def verify_meta(raw_body: bytes, signature_header: str, app_secret: str) -> bool:
    """Meta sends 'X-Hub-Signature-256: sha256=<hexdigest>'."""
    if not app_secret or not signature_header:
        return False
    if not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    provided = signature_header.split("=", 1)[1]
    return hmac.compare_digest(expected, provided)


def verify_line(raw_body: bytes, signature_header: str, channel_secret: str) -> bool:
    """LINE sends 'x-line-signature: <base64(hmac-sha256)>'."""
    if not channel_secret or not signature_header:
        return False
    digest = hmac.new(channel_secret.encode("utf-8"), raw_body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode("utf-8")
    return hmac.compare_digest(expected, signature_header)
