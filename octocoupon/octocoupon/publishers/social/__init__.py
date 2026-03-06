"""Social media platform adapters."""
from .facebook import FacebookAdapter
from .instagram import InstagramAdapter
from .threads import ThreadsAdapter
from .twitter import TwitterAdapter
from .reddit import RedditAdapter
from .rednote import RednoteAdapter
from .base import SocialAdapter, PostResult

PLATFORM_ADAPTERS: dict[str, SocialAdapter] = {
    "facebook":  FacebookAdapter(),
    "instagram": InstagramAdapter(),
    "threads":   ThreadsAdapter(),
    "twitter":   TwitterAdapter(),
    "reddit":    RedditAdapter(),
    "rednote":   RednoteAdapter(),
}

__all__ = [
    "FacebookAdapter", "InstagramAdapter", "ThreadsAdapter",
    "TwitterAdapter", "RedditAdapter", "RednoteAdapter",
    "PLATFORM_ADAPTERS", "SocialAdapter", "PostResult",
]
