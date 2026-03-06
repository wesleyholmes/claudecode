"""
Advertiser catalog: fetches all Rakuten advertisers, maps them to our
supported site countries, assigns WordPress categories via Claude,
and persists to the DB.

Usage:
    from octocoupon.catalog import build_catalog
    build_catalog()
"""
from __future__ import annotations

import json
import time
import base64
import httpx
import anthropic

from octocoupon.config import settings
from octocoupon.affiliates.rakuten import _get_token
from octocoupon.db.connection import get_db, init_db
import logging
log = logging.getLogger(__name__)

# ── Our supported sites and their ISO country codes ──────────────────────────
SITE_TO_ISO: dict[str, str] = {
    "us": "US",
    "hk": "HK",
    "au": "AU",
    "sg": "SG",
    "uk": "GB",
}
ISO_TO_SITE = {v: k for k, v in SITE_TO_ISO.items()}

# Rakuten network IDs we care about (others are CA, EU, BR, etc.)
RELEVANT_NETWORKS = {"1", "3", "41"}   # US, UK, AU

# ── Category taxonomy ─────────────────────────────────────────────────────────
CATEGORIES: dict[str, str] = {
    "fashion":           "Fashion & Clothing",
    "beauty":            "Beauty & Skincare",
    "shoes-accessories": "Shoes & Accessories",
    "travel":            "Travel & Hotels",
    "electronics":       "Electronics & Tech",
    "home-living":       "Home & Living",
    "food-dining":       "Food & Dining",
    "sports-outdoors":   "Sports & Outdoors",
    "kids-baby":         "Kids & Baby",
    "health-wellness":   "Health & Wellness",
    "jewelry-watches":   "Jewelry & Watches",
    "lifestyle":         "Lifestyle & Subscriptions",
}


# ── WordPress helpers ─────────────────────────────────────────────────────────

def _wp_headers() -> dict:
    token = base64.b64encode(
        f"{settings.wp_username}:{settings.wp_app_password}".encode()
    ).decode()
    return {"Authorization": f"Basic {token}", "Content-Type": "application/json"}


def ensure_wp_categories() -> dict[str, int]:
    """Create any missing WordPress categories and return slug→wp_id mapping."""
    base = f"{settings.wp_base_url}/wp-json/wp/v2"
    h = _wp_headers()

    with httpx.Client(headers=h, timeout=20) as client:
        existing = {c["slug"]: c["id"] for c in client.get(f"{base}/categories", params={"per_page": 100}).json()}

        slug_to_id: dict[str, int] = {}
        for slug, name in CATEGORIES.items():
            if slug in existing:
                slug_to_id[slug] = existing[slug]
                log.debug(f"Category exists: {slug} (id={existing[slug]})")
            else:
                r = client.post(f"{base}/categories", json={"name": name, "slug": slug})
                r.raise_for_status()
                wp_id = r.json()["id"]
                slug_to_id[slug] = wp_id
                log.info(f"Created WP category: {slug} → id={wp_id}")

    # Persist to DB
    with get_db() as db:
        for slug, wp_id in slug_to_id.items():
            db.execute(
                "INSERT OR REPLACE INTO wp_categories (slug, name, wp_id) VALUES (?,?,?)",
                (slug, CATEGORIES[slug], wp_id),
            )
    return slug_to_id


# ── Country mapping ───────────────────────────────────────────────────────────

def _map_countries(advertiser: dict) -> list[str]:
    """
    Return list of our site codes where this advertiser is valid.
    Priority:
      1. ships_to ISO codes intersected with our supported set
      2. Fall back to primary network if ships_to is empty
    """
    ships_raw = (advertiser.get("policies") or {}).get("international_capabilities") or {}
    ships = set(ships_raw.get("ships_to") or [])

    sites = [ISO_TO_SITE[iso] for iso in ships if iso in ISO_TO_SITE]

    if not sites:
        # Fall back to network's primary market
        net_to_site = {"1": "us", "3": "uk", "41": "au"}
        net = str(advertiser.get("network", ""))
        if net in net_to_site:
            sites = [net_to_site[net]]

    return sorted(set(sites))


# ── Claude batch categorization ───────────────────────────────────────────────

def _categorize_batch(batch: list[dict]) -> dict[str, str]:
    """Send a batch of advertisers to Claude and get back id→category_slug mapping."""
    slugs = list(CATEGORIES.keys())
    lines = "\n".join(f"- id={a['id']}: {a['name']} ({a.get('url', '')})" for a in batch)

    prompt = f"""Categorize each advertiser into exactly one of these slugs:
{", ".join(slugs)}

Rules:
- "fashion" = clothing, apparel, swimwear, lingerie, streetwear
- "beauty" = skincare, makeup, cosmetics, fragrance, haircare, spa
- "shoes-accessories" = shoes, bags, belts, sunglasses, hats
- "travel" = airlines, hotels, booking, accommodation, tours
- "electronics" = tech, gadgets, phones, computers, e-readers
- "home-living" = furniture, bedding, kitchen, garden, flowers, gifts
- "food-dining" = restaurants, groceries, supplements, food delivery
- "sports-outdoors" = gym, running, cycling, outdoor gear, activewear
- "kids-baby" = children's clothing, toys, baby products
- "health-wellness" = pharmacy, vitamins, medical devices, fitness apps
- "jewelry-watches" = fine jewelry, watches, precious metals
- "lifestyle" = subscription boxes, loyalty programs, financial services, general retail

Advertisers:
{lines}

Return ONLY a JSON object: {{"id": "slug", ...}}"""

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    text = msg.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(text.strip())


# ── Main build function ───────────────────────────────────────────────────────

def build_catalog(batch_size: int = 80) -> int:
    """
    Fetch all Rakuten advertisers, categorize them, and store in DB.
    Returns number of advertisers saved.
    """
    init_db()

    log.info("Ensuring WordPress categories exist…")
    slug_to_wp_id = ensure_wp_categories()

    log.info("Fetching all Rakuten advertisers…")
    token = _get_token()
    h = {"Authorization": f"Bearer {token}"}
    all_advertisers: list[dict] = []
    page = 1
    while True:
        r = httpx.get(
            "https://api.linksynergy.com/v2/advertisers",
            headers=h,
            params={"siteId": settings.rakuten_sid, "page": page, "limit": 100},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        batch = data.get("advertisers", [])
        all_advertisers.extend(batch)
        if not data.get("_metadata", {}).get("_links", {}).get("next") or len(batch) < 100:
            break
        page += 1
    log.info(f"Fetched {len(all_advertisers)} advertisers from Rakuten")

    # Filter to those relevant to our markets
    relevant = []
    for a in all_advertisers:
        countries = _map_countries(a)
        if countries:
            relevant.append({**a, "_countries": countries})
    log.info(f"{len(relevant)} advertisers relevant to our markets (us/hk/au/sg/uk)")

    # Check which ones are already categorized
    with get_db() as db:
        already = {row[0] for row in db.execute("SELECT id FROM advertiser_catalog").fetchall()}

    to_categorize = [a for a in relevant if str(a["id"]) not in already]
    log.info(f"{len(to_categorize)} new advertisers to categorize, {len(already)} already in DB")

    # Batch categorize with Claude (Haiku for speed/cost)
    category_map: dict[str, str] = {}
    for i in range(0, len(to_categorize), batch_size):
        chunk = to_categorize[i: i + batch_size]
        log.info(f"Categorizing batch {i // batch_size + 1} ({len(chunk)} advertisers)…")
        try:
            result = _categorize_batch([{"id": str(a["id"]), "name": a["name"], "url": a.get("url", "")} for a in chunk])
            category_map.update(result)
        except Exception as e:
            log.warning(f"Batch categorization failed: {e} — defaulting to 'lifestyle'")
            for a in chunk:
                category_map[str(a["id"])] = "lifestyle"
        time.sleep(0.5)  # avoid rate limits

    # Persist to DB
    saved = 0
    with get_db() as db:
        for a in relevant:
            aid = str(a["id"])
            category = category_map.get(aid, "lifestyle")
            wp_cat_id = slug_to_wp_id.get(category)
            countries = a["_countries"]
            db.execute(
                """INSERT OR REPLACE INTO advertiser_catalog
                   (id, name, url, logo_url, network_id, countries, category, wp_category_id, updated_at)
                   VALUES (?,?,?,?,?,?,?,?, datetime('now'))""",
                (
                    aid,
                    a["name"],
                    a.get("url", ""),
                    a.get("logo_url", ""),
                    str(a.get("network", "")),
                    json.dumps(countries),
                    category,
                    wp_cat_id,
                ),
            )
            saved += 1

    log.info(f"Catalog built: {saved} advertisers saved")
    return saved
