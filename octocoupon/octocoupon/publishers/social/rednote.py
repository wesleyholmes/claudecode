"""
Rednote / 小红书 adapter.

IMPORTANT: Rednote has no official public API for third-party posting.
This adapter uses the internal web API via a browser session cookie.

How to get your cookie:
  1. Log in at xiaohongshu.com in Chrome/Firefox
  2. Open DevTools → Application → Cookies → copy the full Cookie header
  3. Paste it as REDNOTE_COOKIE in your .env file

This approach is fragile and may break if Rednote changes their web API.
For high-volume production use, explore official brand partnership programs
or a managed social media tool that supports Rednote.
"""
from __future__ import annotations

import httpx
from octocoupon.config import settings
from .base import SocialAdapter, PostResult

NOTE_API = "https://edith.xiaohongshu.com/api/sns/web/v1/note/create"


class RednoteAdapter(SocialAdapter):
    platform = "rednote"

    def post(self, caption: str, link_url: str | None = None) -> PostResult:
        if not settings.rednote_cookie:
            return PostResult(
                platform=self.platform,
                success=False,
                error="REDNOTE_COOKIE not set. See .env.example for instructions.",
            )

        try:
            # Rednote notes have a title (first line, max ~20 chars) and body
            lines = caption.strip().split("\n", 1)
            title = lines[0][:20]
            desc = caption

            resp = httpx.post(
                NOTE_API,
                json={
                    "type": "normal",
                    "title": title,
                    "desc": desc,
                    "privacy_info": {"op_type": 0, "type": 0},
                },
                headers={
                    "Cookie": settings.rednote_cookie,
                    "Content-Type": "application/json",
                    "User-Agent": (
                        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                        "AppleWebKit/605.1.15"
                    ),
                    "Referer": "https://www.xiaohongshu.com/",
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("success"):
                return PostResult(
                    platform=self.platform,
                    success=True,
                    post_id=data.get("data", {}).get("id"),
                )
            return PostResult(
                platform=self.platform,
                success=False,
                error=data.get("msg", "Unknown Rednote API error"),
            )
        except Exception as exc:
            return PostResult(platform=self.platform, success=False, error=str(exc))
