"""
Facebook Pages API — post a text update to a Page.
Requires: pages_manage_posts, pages_read_engagement permissions.
Graph API docs: https://developers.facebook.com/docs/pages-api/posts
"""
from __future__ import annotations

import httpx
from octocoupon.config import settings
from .base import SocialAdapter, PostResult

GRAPH = "https://graph.facebook.com/v20.0"


class FacebookAdapter(SocialAdapter):
    platform = "facebook"

    def post(self, caption: str, link_url: str | None = None) -> PostResult:
        try:
            message = f"{caption}\n\n{link_url}" if link_url else caption
            resp = httpx.post(
                f"{GRAPH}/{settings.facebook_page_id}/feed",
                data={"message": message, "access_token": settings.facebook_access_token},
                timeout=30,
            )
            resp.raise_for_status()
            return PostResult(platform=self.platform, success=True, post_id=resp.json().get("id"))
        except Exception as exc:
            return PostResult(platform=self.platform, success=False, error=str(exc))
