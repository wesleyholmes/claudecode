"""
Typed configuration loaded from environment variables / .env file.
All values are optional strings so the app starts without crashing —
individual modules raise clear errors when their credentials are missing.
"""
from __future__ import annotations

from typing import Literal
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Affiliate ──────────────────────────────────────────────────────────────
    rakuten_client_id: str = ""
    rakuten_client_secret: str = ""
    rakuten_scope: str = "Production"

    cj_api_key: str = ""
    cj_cid: str = ""

    optimise_api_key: str = ""
    optimise_publisher_id: str = ""

    # ── WordPress ──────────────────────────────────────────────────────────────
    wp_base_url: str = "https://octocoupon.com"
    wp_username: str = ""
    wp_app_password: str = ""

    # ── AI ─────────────────────────────────────────────────────────────────────
    anthropic_api_key: str = ""

    # ── Social: Meta ──────────────────────────────────────────────────────────
    facebook_page_id: str = ""
    facebook_access_token: str = ""

    instagram_account_id: str = ""
    instagram_access_token: str = ""

    threads_user_id: str = ""
    threads_access_token: str = ""

    # ── Social: Twitter/X ─────────────────────────────────────────────────────
    twitter_api_key: str = ""
    twitter_api_secret: str = ""
    twitter_access_token: str = ""
    twitter_access_secret: str = ""

    # ── Social: Reddit ────────────────────────────────────────────────────────
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_username: str = ""
    reddit_password: str = ""
    reddit_subreddit_us: str = "deals"

    # ── Social: Rednote ───────────────────────────────────────────────────────
    rednote_cookie: str = ""

    # ── Runtime ───────────────────────────────────────────────────────────────
    log_level: str = "INFO"
    db_path: str = "~/.octocoupon/octocoupon.db"
    max_publish_per_run: int = 5

    cron_affiliate_sync: str = "0 */6 * * *"
    cron_content_publish: str = "0 9,17 * * *"
    cron_social_post: str = "30 9,17 * * *"

    @field_validator("wp_base_url")
    @classmethod
    def strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")


settings = Settings()
