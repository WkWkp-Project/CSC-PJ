"""Phase 8 config - the single place tokens are filled in (from env vars).

Nothing in the codebase hardcodes a secret. All six platform values plus the
engine secret are read from environment variables here, so going live is only a
matter of filling `.env` (see `.env.example`). While a value is blank, the
matching capability simply reports "not ready" instead of crashing - so the
whole pipeline can be built, imported and tested before any real token exists.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _get(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass
class Config:
    # ---- Facebook / Meta (fill these) ----
    fb_app_secret: str          # FB_APP_SECRET      - verify X-Hub-Signature-256
    fb_page_token: str          # FB_PAGE_TOKEN      - read page messages (make permanent!)
    fb_page_id: str             # FB_PAGE_ID
    fb_verify_token: str        # FB_VERIFY_TOKEN    - you choose this string
    # ---- LINE (fill these) ----
    line_channel_secret: str    # LINE_CHANNEL_SECRET        - verify x-line-signature
    line_channel_access_token: str  # LINE_CHANNEL_ACCESS_TOKEN - read/send
    line_target_group_id: str   # LINE_TARGET_GROUP_ID       - where tickets are posted
    # ---- engine / runtime ----
    assist_hmac_secret: str     # ASSIST_HMAC_SECRET - >=32 bytes, internal digests
    tenant_id: str              # ASSIST_TENANT_ID   - e.g. "tulip"
    db_path: str                # ASSIST_DB_PATH
    kb_approved_path: str       # KB_APPROVED_PATH
    kb_draft_path: str          # KB_DRAFT_PATH

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            fb_app_secret=_get("FB_APP_SECRET"),
            fb_page_token=_get("FB_PAGE_TOKEN"),
            fb_page_id=_get("FB_PAGE_ID"),
            fb_verify_token=_get("FB_VERIFY_TOKEN"),
            line_channel_secret=_get("LINE_CHANNEL_SECRET"),
            line_channel_access_token=_get("LINE_CHANNEL_ACCESS_TOKEN"),
            line_target_group_id=_get("LINE_TARGET_GROUP_ID"),
            assist_hmac_secret=_get("ASSIST_HMAC_SECRET"),
            tenant_id=_get("ASSIST_TENANT_ID", "tulip"),
            db_path=_get("ASSIST_DB_PATH", "data/assist.db"),
            kb_approved_path=_get("KB_APPROVED_PATH", "phase6/config/approved_kb.json"),
            kb_draft_path=_get("KB_DRAFT_PATH", "phase6/config/kb_draft_from_research.json"),
        )

    # ---- readiness flags (blank token => not ready, no crash) ----
    @property
    def meta_ready(self) -> bool:
        return all([self.fb_app_secret, self.fb_page_token, self.fb_page_id, self.fb_verify_token])

    @property
    def line_ready(self) -> bool:
        return all([self.line_channel_secret, self.line_channel_access_token])

    @property
    def delivery_ready(self) -> bool:
        # Can actually push tickets into the LINE group.
        return bool(self.line_channel_access_token and self.line_target_group_id)

    @property
    def engine_ready(self) -> bool:
        return len(self.assist_hmac_secret.encode("utf-8")) >= 32

    def missing(self) -> dict[str, list[str]]:
        """What is still blank, grouped, so a status page can show the checklist."""
        def blanks(pairs):
            return [name for name, val in pairs if not val]
        return {
            "facebook": blanks([
                ("FB_APP_SECRET", self.fb_app_secret), ("FB_PAGE_TOKEN", self.fb_page_token),
                ("FB_PAGE_ID", self.fb_page_id), ("FB_VERIFY_TOKEN", self.fb_verify_token),
            ]),
            "line": blanks([
                ("LINE_CHANNEL_SECRET", self.line_channel_secret),
                ("LINE_CHANNEL_ACCESS_TOKEN", self.line_channel_access_token),
                ("LINE_TARGET_GROUP_ID", self.line_target_group_id),
            ]),
            "engine": [] if self.engine_ready else ["ASSIST_HMAC_SECRET(>=32 chars)"],
        }

    def status(self) -> dict[str, object]:
        return {
            "meta_ready": self.meta_ready,
            "line_ready": self.line_ready,
            "delivery_ready": self.delivery_ready,
            "engine_ready": self.engine_ready,
            "can_go_live_phase1": self.engine_ready and (self.meta_ready or self.line_ready) and self.delivery_ready,
            "missing": self.missing(),
        }
