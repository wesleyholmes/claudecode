"""
Threads API (Meta) — publish a text post.
Same two-step create-then-publish flow as Instagram.
Docs: https://developers.facebook.com/docs/threads
Permissions: threads_basic, threads_content_publish
"""
from __future__ import annotations

import httpx
from octocoupon.config import settings
from .base import SocialAdapter, PostResult

BASE = "https://graph.threads.net/v1.0"


class ThreadsAdapter(SocialAdapter):
    platform = "threads"

    def post(self, caption: str, link_url: str | None = None) -> PostResult:
        try:
            user_id = settings.threads_user_id
            token = settings.threads_access_token
            text = f"{caption}\n\n{link_url}" if link_url else caption

            # Step 1: create container
            r1 = httpx.post(
                f"{BASE}/{user_id}/threads",
                data={"media_type": "TEXT", "text": text, "access_token": token},
                timeout=30,
            )
            r1.raise_for_status()
            creation_id = r1.json()["id"]

            # Step 2: publish
            r2 = httpx.post(
                f"{BASE}/{user_id}/threads_publish",
                data={"creation_id": creation_id, "access_token": token},
                timeout=30,
            )
            r2.raise_for_status()
            return PostResult(platform=self.platform, success=True, post_id=r2.json().get("id"))
        except Exception as exc:
            return PostResult(platform=self.platform, success=False, error=str(exc))
