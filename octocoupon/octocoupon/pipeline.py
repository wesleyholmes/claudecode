"""
Core pipeline functions — called by both the CLI and the scheduler.

  sync_affiliates()   — pull coupons from all networks into SQLite
  publish_content()   — generate AI content + post to WordPress
  post_social()       — push queued WP posts to social platforms
"""
from __future__ import annotations

import re
from datetime import datetime

from octocoupon.affiliates import ALL_ADAPTERS
from octocoupon.affiliates.base import Coupon, Advertiser, CountryCode
from octocoupon.content.generator import generate
from octocoupon.publishers.wordpress import create_post, post_exists
from octocoupon.publishers.social import PLATFORM_ADAPTERS
from octocoupon.db import get_db
from octocoupon.config import settings
from octocoupon.logger import logger

# Active country list — add more as you launch new subsites
ACTIVE_COUNTRIES: list[CountryCode] = ["us", "hk", "au"]

COUNTRY_PLATFORMS: dict[str, list[str]] = {
    "us": ["facebook", "instagram", "threads", "twitter", "reddit"],
    "hk": ["instagram", "threads", "rednote"],
    "au": ["facebook", "instagram", "threads", "twitter", "reddit"],
    "sg": ["facebook", "instagram", "threads", "twitter"],
    "uk": ["facebook", "instagram", "threads", "twitter", "reddit"],
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _upsert_advertiser(conn, a: Advertiser) -> None:
    conn.execute("""
        INSERT INTO advertisers (id, network, name, url, country, logo_url, raw_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            name=excluded.name, url=excluded.url,
            logo_url=excluded.logo_url, raw_json=excluded.raw_json,
            synced_at=datetime('now')
    """, (a.id, a.network, a.name, a.url, a.country, a.logo_url, a.raw_json))


def _upsert_coupon(conn, c: Coupon) -> None:
    conn.execute("""
        INSERT INTO coupons (id, advertiser_id, network, country, title, description,
                             code, discount, start_date, end_date, affiliate_url, raw_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            title=excluded.title, description=excluded.description,
            code=excluded.code, discount=excluded.discount,
            start_date=excluded.start_date, end_date=excluded.end_date,
            affiliate_url=excluded.affiliate_url, raw_json=excluded.raw_json,
            synced_at=datetime('now')
    """, (c.id, c.advertiser_id, c.network, c.country, c.title, c.description,
          c.code, c.discount, c.start_date, c.end_date, c.affiliate_url, c.raw_json))


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]


# ── Phase 1: Affiliate Sync ────────────────────────────────────────────────────

def sync_affiliates() -> None:
    logger.info("=== Affiliate sync started ===")
    for adapter in ALL_ADAPTERS:
        for country in ACTIVE_COUNTRIES:
            logger.info(f"  Syncing {adapter.network}/{country}...")
            result = adapter.sync(country)
            with get_db() as conn:
                for a in result.advertisers:
                    _upsert_advertiser(conn, a)
                for c in result.coupons:
                    _upsert_coupon(conn, c)
            logger.info(
                f"  {adapter.network}/{country}: "
                f"{len(result.advertisers)} advertisers, {len(result.coupons)} coupons"
                + (f", {len(result.errors)} errors" if result.errors else "")
            )
            for err in result.errors:
                logger.warning(f"    {err}")
    logger.info("=== Affiliate sync complete ===")


# ── Phase 2: Content + WordPress Publish ───────────────────────────────────────

def publish_content() -> None:
    logger.info("=== Content publish started ===")
    for country in ACTIVE_COUNTRIES:
        platforms = COUNTRY_PLATFORMS.get(country, [])
        with get_db() as conn:
            rows = conn.execute("""
                SELECT c.* FROM coupons c
                LEFT JOIN wp_posts w ON w.coupon_id = c.id AND w.country = ?
                WHERE c.country = ?
                  AND w.id IS NULL
                  AND (c.end_date IS NULL OR c.end_date > date('now'))
                ORDER BY c.synced_at DESC
                LIMIT ?
            """, (country, country, settings.max_publish_per_run)).fetchall()

        logger.info(f"  {country}: {len(rows)} coupons to publish")

        for row in rows:
            coupon = Coupon(
                id=row["id"], advertiser_id=row["advertiser_id"],
                network=row["network"], country=row["country"],
                title=row["title"], description=row["description"],
                code=row["code"], discount=row["discount"],
                start_date=row["start_date"], end_date=row["end_date"],
                affiliate_url=row["affiliate_url"],
            )
            try:
                content = generate(coupon, platforms)
                slug = _slugify(content.wp_title) + f"-{coupon.id[-6:]}"

                if post_exists(country, slug):
                    logger.info(f"  Skipping (already published): {slug}")
                    continue

                wp = create_post(
                    country=country,
                    title=content.wp_title,
                    content=content.wp_body,
                    excerpt=content.wp_excerpt,
                    slug=slug,
                    tags=[coupon.network, country, "deals", "coupons"],
                )
                logger.info(f"  Published: {content.wp_title} → {wp.url}")

                with get_db() as conn:
                    conn.execute("""
                        INSERT OR IGNORE INTO wp_posts (coupon_id, country, wp_post_id, wp_url)
                        VALUES (?, ?, ?, ?)
                    """, (coupon.id, country, wp.id, wp.url))

                    wp_db_id = conn.execute("""
                        SELECT id FROM wp_posts WHERE coupon_id = ? AND country = ?
                    """, (coupon.id, country)).fetchone()["id"]

                    for platform in platforms:
                        caption = content.social_captions.get(platform, content.wp_excerpt)
                        conn.execute("""
                            INSERT OR IGNORE INTO social_posts
                                (wp_post_id, platform, status)
                            VALUES (?, ?, 'pending')
                        """, (wp_db_id, platform))
                        # Store caption in error field temporarily (repurposed as staging)
                        conn.execute("""
                            UPDATE social_posts SET error = ?
                            WHERE wp_post_id = ? AND platform = ? AND status = 'pending'
                        """, (caption, wp_db_id, platform))

            except Exception as exc:
                logger.error(f"  Failed to publish {coupon.id}: {exc}")

    logger.info("=== Content publish complete ===")


# ── Phase 3: Social Media Posting ─────────────────────────────────────────────

def post_social() -> None:
    logger.info("=== Social posting started ===")

    with get_db() as conn:
        pending = conn.execute("""
            SELECT sp.id, sp.wp_post_id, sp.platform, sp.error AS caption,
                   wp.wp_url, wp.country, c.title
            FROM social_posts sp
            JOIN wp_posts wp ON wp.id = sp.wp_post_id
            JOIN coupons c ON c.id = wp.coupon_id
            WHERE sp.status = 'pending'
            ORDER BY sp.id
            LIMIT 30
        """).fetchall()

    for row in pending:
        platform = row["platform"]
        adapter = PLATFORM_ADAPTERS.get(platform)
        if not adapter:
            logger.warning(f"  No adapter for platform: {platform}")
            continue

        caption = row["caption"] or row["title"]
        result = adapter.post(caption=caption, link_url=row["wp_url"])

        with get_db() as conn:
            conn.execute("""
                UPDATE social_posts
                SET platform_post_id = ?,
                    status = ?,
                    posted_at = datetime('now'),
                    error = ?
                WHERE id = ?
            """, (
                result.post_id,
                "posted" if result.success else "failed",
                result.error,
                row["id"],
            ))

        if result.success:
            logger.info(f"  {platform}: posted (id={result.post_id})")
        else:
            logger.warning(f"  {platform}: failed — {result.error}")

    logger.info("=== Social posting complete ===")
