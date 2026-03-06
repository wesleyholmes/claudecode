"""
Reddit API — submit a link post to a deals subreddit.
Uses PRAW (Python Reddit API Wrapper) with script-app OAuth.
Docs: https://praw.readthedocs.io/
"""
from __future__ import annotations

import praw
from octocoupon.config import settings
from .base import SocialAdapter, PostResult

# Maps country to the subreddit to post in
COUNTRY_SUBREDDIT: dict[str, str] = {
    "us": settings.reddit_subreddit_us,
    "au": "AussieDealHunter",
    "uk": "UKPersonalFinance",  # or r/HotUKDeals
    "sg": "singapore",
}


def _reddit() -> praw.Reddit:
    return praw.Reddit(
        client_id=settings.reddit_client_id,
        client_secret=settings.reddit_client_secret,
        username=settings.reddit_username,
        password=settings.reddit_password,
        user_agent="Octocoupon/1.0",
    )


class RedditAdapter(SocialAdapter):
    platform = "reddit"

    def __init__(self, country: str = "us"):
        self.country = country

    def post(self, caption: str, link_url: str | None = None) -> PostResult:
        try:
            subreddit_name = COUNTRY_SUBREDDIT.get(self.country, settings.reddit_subreddit_us)
            reddit = _reddit()
            subreddit = reddit.subreddit(subreddit_name)

            if link_url:
                submission = subreddit.submit(title=caption[:300], url=link_url, resubmit=True)
            else:
                submission = subreddit.submit(title=caption[:300], selftext=caption)

            return PostResult(
                platform=self.platform,
                success=True,
                post_id=submission.id,
                url=f"https://reddit.com{submission.permalink}",
            )
        except Exception as exc:
            return PostResult(platform=self.platform, success=False, error=str(exc))
