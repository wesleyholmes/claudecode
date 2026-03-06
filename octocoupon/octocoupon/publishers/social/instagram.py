"""
Instagram Graph API — create a media container then publish it.
Requires: instagram_basic, instagram_content_publish permissions.
A public image URL is required; falls back to the site OG image.
Docs: https://developers.facebook.com/docs/instagram-api/guides/content-publishing
"""
from __future__ import annotations

import httpx
from octocoupon.config import settings
from .base import SocialAdapter, PostResult

GRAPH = "https://graph.facebook.com/v20.0"
DEFAULT_IMAGE = "https://octocoupon.com/og-default.jpg"


class InstagramAdapter(SocialAdapter):
    platform = "instagram"

    def post(self, caption: str, link_url: str | None = None, image_url: str | None = None) -> PostResult:
        try:
            account_id = settings.instagram_account_id
            token = settings.instagram_access_token
            full_caption = caption  # link_url goes in bio, not caption

            # Step 1: create media container
            r1 = httpx.post(
                f"{GRAPH}/{account_id}/media",
                data={
                    "image_url": image_url or DEFAULT_IMAGE,
                    "caption": full_caption,
                    "access_token": token,
                },
                timeout=30,
            )
            r1.raise_for_status()
            creation_id = r1.json()["id"]

            # Step 2: publish
            r2 = httpx.post(
                f"{GRAPH}/{account_id}/media_publish",
                data={"creation_id": creation_id, "access_token": token},
                timeout=30,
            )
            r2.raise_for_status()
            return PostResult(platform=self.platform, success=True, post_id=r2.json().get("id"))
        except Exception as exc:
            return PostResult(platform=self.platform, success=False, error=str(exc))
