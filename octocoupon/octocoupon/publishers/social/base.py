"""Abstract base for all social media adapters."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class PostResult:
    platform: str
    success: bool
    post_id: str | None = None
    url: str | None = None
    error: str | None = None


class SocialAdapter(ABC):
    platform: str

    @abstractmethod
    def post(self, caption: str, link_url: str | None = None) -> PostResult:
        """Publish a post. Returns a PostResult regardless of success/failure."""
