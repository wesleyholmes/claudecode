"""
Twitter/X API v2 — post a tweet via OAuth 1.0a user context.
Uses tweepy which handles the OAuth signing automatically.
Docs: https://docs.tweepy.org/en/stable/
"""
from __future__ import annotations

import tweepy
from octocoupon.config import settings
from .base import SocialAdapter, PostResult


def _client() -> tweepy.Client:
    return tweepy.Client(
        consumer_key=settings.twitter_api_key,
        consumer_secret=settings.twitter_api_secret,
        access_token=settings.twitter_access_token,
        access_token_secret=settings.twitter_access_secret,
    )


class TwitterAdapter(SocialAdapter):
    platform = "twitter"

    def post(self, caption: str, link_url: str | None = None) -> PostResult:
        try:
            text = f"{caption}\n\n{link_url}" if link_url else caption
            # Twitter counts URLs as 23 chars; stay under 280 total
            if len(text) > 280:
                # Truncate caption, keep the URL intact
                max_caption = 280 - (len(link_url) + 4 if link_url else 3)
                text = f"{caption[:max_caption]}…\n\n{link_url}" if link_url else f"{caption[:277]}…"

            response = _client().create_tweet(text=text)
            tweet_id = str(response.data["id"])
            return PostResult(
                platform=self.platform,
                success=True,
                post_id=tweet_id,
                url=f"https://x.com/i/web/status/{tweet_id}",
            )
        except Exception as exc:
            return PostResult(platform=self.platform, success=False, error=str(exc))
