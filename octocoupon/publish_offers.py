"""
One-shot publisher: generates SEO posts for all unique offers from
Adidas HK, Chow Sang Sang, and Trip.com (Agent Provocateur already published).

Run:  .venv/bin/python publish_offers.py
"""
from __future__ import annotations

import base64
import io
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import anthropic
import httpx

sys.path.insert(0, ".")
from octocoupon.affiliates.rakuten import _get_token
from octocoupon.config import settings
from octocoupon.db.connection import get_db, init_db

# ── Config ────────────────────────────────────────────────────────────────────

SCRAPE_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

# Subsite paths per country (empty = root/US)
COUNTRY_WP_PATH = {"us": "", "hk": "/hk", "au": "/au", "sg": "/sg", "uk": "/uk"}

# Advertiser → WP category ID (from catalog build)
CATEGORY_IDS = {
    "adidas":          84,   # sports-outdoors
    "chowsangsang":    87,   # jewelry-watches
    "tripcom":         80,   # travel
}

ADVERTISER_SITES = {
    "44931": "https://www.adidas.com.hk/en",
    "42929": "https://www.chowsangsang.com",
    "52696": "https://www.trip.com",
    "39673": "https://www.agentprovocateur.com",
}

RAKUTEN_LOGOS = {
    "44931": "https://merchant.linksynergy.com/fs/logo/lg_44931.jpg",
    "42929": "https://merchant.linksynergy.com/fs/logo/lg_42929.jpg",
    "52696": "https://merchant.linksynergy.com/fs/logo/lg_52696",
    "39673": "https://merchant.linksynergy.com/fs/logo/lg_39673.png",
}

# ── WordPress helpers ─────────────────────────────────────────────────────────

def _wp_auth() -> str:
    return base64.b64encode(f"{settings.wp_username}:{settings.wp_app_password}".encode()).decode()

def _wp_base(country: str) -> str:
    return f"{settings.wp_base_url}{COUNTRY_WP_PATH.get(country, '')}/wp-json/wp/v2"

def _wp_headers(content_type: str = "application/json") -> dict:
    return {"Authorization": f"Basic {_wp_auth()}", "Content-Type": content_type}


def fetch_advertiser_image(advertiser_id: str) -> str:
    """
    Fetch the best available image for an advertiser:
    1. OG/Twitter image scraped from official website
    2. Fall back to Rakuten logo URL
    """
    site_url = ADVERTISER_SITES.get(advertiser_id)
    if site_url:
        try:
            r = httpx.get(site_url, headers=SCRAPE_HEADERS, timeout=15, follow_redirects=True)
            html = r.text
            for pat in [
                r'property=["\']og:image["\'][^>]+content=["\']([^"\'>\s]+)',
                r'content=["\']([^"\'>\s]+)["\'][^>]+property=["\']og:image',
                r'name=["\']twitter:image["\'][^>]+content=["\']([^"\'>\s]+)',
                r'content=["\']([^"\'>\s]+)["\'][^>]+name=["\']twitter:image',
            ]:
                m = re.search(pat, html)
                if m:
                    img = m.group(1)
                    if img.startswith("//"):
                        img = "https:" + img
                    if img.startswith("/"):
                        from urllib.parse import urlparse
                        p = urlparse(site_url)
                        img = f"{p.scheme}://{p.netloc}{img}"
                    print(f"  [img] Found OG image: {img[:70]}")
                    return img
        except Exception as e:
            print(f"  [img] OG scrape failed ({e}), falling back to logo")

    logo = RAKUTEN_LOGOS.get(advertiser_id, "")
    if logo:
        print(f"  [img] Using Rakuten logo: {logo}")
    return logo


def upload_image(image_url: str, filename: str, alt_text: str, country: str = "us") -> int | None:
    """Download image from URL and upload to WordPress media library. Returns WP media ID."""
    try:
        r = httpx.get(image_url, headers=SCRAPE_HEADERS, timeout=20, follow_redirects=True)
        if r.status_code != 200:
            print(f"  [img] Failed to download {image_url}: {r.status_code}")
            return None

        content_type = r.headers.get("content-type", "image/jpeg").split(";")[0].strip()
        ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif"}.get(content_type, "jpg")
        fname = f"{filename}.{ext}"

        base = _wp_base(country)
        upload_headers = {
            "Authorization": f"Basic {_wp_auth()}",
            "Content-Disposition": f'attachment; filename="{fname}"',
            "Content-Type": content_type,
        }
        resp = httpx.post(f"{base}/media", headers=upload_headers, content=r.content, timeout=30)
        if resp.status_code in (200, 201):
            media_id = resp.json()["id"]
            # Set alt text
            httpx.post(f"{base}/media/{media_id}",
                headers=_wp_headers(),
                content=json.dumps({"alt_text": alt_text, "caption": alt_text}),
                timeout=15)
            print(f"  [img] Uploaded → media_id={media_id}")
            return media_id
        else:
            print(f"  [img] Upload failed: {resp.status_code} {resp.text[:100]}")
            return None
    except Exception as e:
        print(f"  [img] Error: {e}")
        return None


def post_exists_by_slug(slug: str, country: str = "us") -> bool:
    base = _wp_base(country)
    r = httpx.get(f"{base}/posts", headers=_wp_headers(),
                  params={"slug": slug}, timeout=15)
    return len(r.json()) > 0 if r.status_code == 200 else False


def create_wp_post(
    country: str,
    title: str,
    content: str,
    excerpt: str,
    slug: str,
    category_ids: list[int],
    tags: list[str],
    featured_media_id: int | None,
    seo: dict,
) -> dict | None:
    """Create a WordPress post with Yoast SEO fields."""
    base = _wp_base(country)
    headers = _wp_headers()

    # Resolve/create tags
    tag_ids = []
    with httpx.Client(headers=headers, timeout=20) as client:
        for tag in tags:
            r = client.get(f"{base}/tags", params={"search": tag})
            existing = r.json() if r.status_code == 200 else []
            if existing:
                tag_ids.append(existing[0]["id"])
            else:
                r2 = client.post(f"{base}/tags", content=json.dumps({"name": tag}))
                if r2.status_code in (200, 201):
                    tag_ids.append(r2.json()["id"])

    payload = {
        "title": title,
        "content": content,
        "excerpt": excerpt,
        "slug": slug,
        "status": "publish",
        "categories": category_ids,
        "tags": tag_ids,
    }
    if featured_media_id:
        payload["featured_media"] = featured_media_id

    r = httpx.post(f"{base}/posts", headers=headers, content=json.dumps(payload), timeout=30)
    if r.status_code not in (200, 201):
        print(f"  [wp] Post failed: {r.status_code} {r.text[:200]}")
        return None

    post = r.json()
    post_id = post["id"]

    # Write Yoast SEO fields via separate PATCH
    if seo:
        httpx.post(f"{base}/posts/{post_id}", headers=headers,
                   content=json.dumps({"yoast_head_json": seo}), timeout=15)

    return post


# ── Claude content generation ─────────────────────────────────────────────────

@dataclass
class Offer:
    advertiser_id: str
    advertiser_name: str
    title: str
    description: str
    code: str | None
    discount: str
    end_date: str
    affiliate_url: str
    country: str          # our site code: us/hk/au/sg/uk
    category_id: int
    image_url: str
    tags: list[str]


def generate_post(offer: Offer) -> dict:
    """Call Claude to generate SEO post. Returns dict with all fields."""
    lang_map = {"us": "English (US)", "hk": "English", "au": "English (AU)", "sg": "English (SG)", "uk": "English (UK)"}
    currency_map = {"us": "USD", "hk": "HKD", "au": "AUD", "sg": "SGD", "uk": "GBP"}
    lang = lang_map.get(offer.country, "English")
    currency = currency_map.get(offer.country, "USD")

    prompt = f"""You are an SEO copywriter for Octocoupon, a deals and coupon website.

Write a blog post for this offer. Output ONLY valid JSON, no markdown fences.

Offer details:
- Advertiser: {offer.advertiser_name}
- Title: {offer.title}
- Discount type: {offer.discount}
- Coupon code: {offer.code or "No code needed — discount applied automatically"}
- Expires: {offer.end_date or "No expiry listed"}
- Affiliate URL: {offer.affiliate_url}
- Language: {lang}
- Currency: {currency}

SEO requirements:
- Target a specific long-tail keyword based on the offer (e.g. "agent provocateur sale discount", "chow sang sang jewellery promo code")
- Title: 50-60 characters, include brand name + main benefit
- Meta description: 140-160 characters, include keyword + CTA
- Post body: 300-400 words HTML with:
  * ONE <h1> matching the post title (for schema)
  * 2-3 <h2> subheadings with keyword variations
  * <ul> bullet list of 4-5 key deal highlights
  * Schema.org Offer markup as a <script type="application/ld+json"> block
  * Clear <a href="{offer.affiliate_url}" target="_blank" rel="sponsored noopener">Shop Now →</a> CTA button styled with: style="display:inline-block;background:#000;color:#fff;padding:12px 28px;text-decoration:none;font-weight:bold;border-radius:4px;"
  * If coupon code exists, a styled code box: <div style="background:#f5f5f5;border:2px dashed #333;padding:16px;text-align:center;font-size:1.3em;font-weight:bold;letter-spacing:2px;">{offer.code}</div>
  * Do NOT invent discount amounts not stated in the offer

Return this exact JSON:
{{
  "wp_title": "SEO title, 50-60 chars",
  "wp_body": "Full HTML post body (no <html>/<body> tags, just content)",
  "wp_excerpt": "Meta description, 140-160 chars",
  "focus_keyword": "primary SEO keyword phrase",
  "seo_title": "SEO title tag (can differ slightly from wp_title), 50-60 chars",
  "tags": ["tag1", "tag2", "tag3", "tag4", "tag5"]
}}"""

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=3000,
        messages=[{"role": "user", "content": prompt}],
    )
    text = msg.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(text.strip())


# ── Offer definitions ─────────────────────────────────────────────────────────

def get_offers() -> list[Offer]:
    token = _get_token()
    h = {"Authorization": f"Bearer {token}"}
    r = httpx.get("https://api.linksynergy.com/coupon/1.0",
                  headers=h, params={"sid": settings.rakuten_sid, "limit": 500}, timeout=30)
    root = ET.fromstring(r.text)

    all_links = []
    for link in root.findall("link"):
        all_links.append({
            "mid": link.findtext("advertiserid"),
            "name": link.findtext("advertisername"),
            "title": link.findtext("offerdescription") or "",
            "code": link.findtext("couponcode"),
            "discount": ", ".join(pt.text for pt in link.findall("promotiontypes/promotiontype") if pt.text),
            "end_date": (link.findtext("offerenddate") or "")[:10],
            "click_url": link.findtext("clickurl") or "",
            "categories": [c.text for c in link.findall("categories/category") if c.text],
            "network": link.find("network").get("id") if link.find("network") is not None else "1",
        })

    # ── Adidas HK ───────────────────────────────────────────────────────────
    adidas = [l for l in all_links if l["mid"] == "44931"]
    # ── Chow Sang Sang: deduplicate — keep English versions only ─────────────
    css_all = [l for l in all_links if l["mid"] == "42929"]
    seen_titles: set[str] = set()
    css = []
    for l in css_all:
        title = l["title"]
        # Skip Chinese-dominant entries (fewer than 6 ASCII letters = mostly Chinese)
        ascii_letters = len(re.findall(r'[a-zA-Z]', title))
        if ascii_letters < 6:
            continue
        # Deduplicate by normalised title (first 70 chars)
        norm = re.sub(r'[^a-z0-9\s]', '', title.lower())[:70].strip()
        if norm not in seen_titles:
            seen_titles.add(norm)
            css.append(l)

    # ── Trip.com: keep only unique/relevant offers for our markets ─────────
    trip_all = [l for l in all_links if l["mid"] == "52696"]
    RELEVANT_TRIP = {
        "Find the Best Travel Deals",
        "eSIM Card 8% Off",
        "Trip.com Attraction And Ticket",
        "Autumn Scenery Deals - US!",
        "Autumn Scenery Deals - HK-ZH!",
        "Autumn Scenery Deals - EN-SG!",
    }
    seen_trip: set[str] = set()
    trip = []
    for l in trip_all:
        for key in RELEVANT_TRIP:
            if key.lower() in l["title"].lower():
                norm = key
                if norm not in seen_trip:
                    seen_trip.add(norm)
                    trip.append(l)
                break

    def to_offer(l: dict, country: str, cat_id: int, tags: list[str]) -> Offer:
        return Offer(
            advertiser_id=l["mid"],
            advertiser_name=l["name"],
            title=l["title"],
            description=", ".join(l["categories"]),
            code=l["code"],
            discount=l["discount"],
            end_date=l["end_date"],
            affiliate_url=l["click_url"],
            country=country,
            category_id=cat_id,
            image_url="",   # fetched dynamically per advertiser
            tags=tags,
        )

    offers: list[Offer] = []

    for l in adidas:
        offers.append(to_offer(l, "hk", CATEGORY_IDS["adidas"],
                               ["adidas", "sportswear", "sale", "hong kong", "fashion"]))

    for l in css:
        offers.append(to_offer(l, "us", CATEGORY_IDS["chowsangsang"],
                               ["chow sang sang", "jewelry", "jewellery", "gold", "hong kong", "coupon"]))

    for l in trip:
        # Route country-specific deals to correct subsite
        title = l["title"]
        country = "hk" if "HK-ZH" in title else "sg" if "EN-SG" in title else "us"
        offers.append(to_offer(l, country, CATEGORY_IDS["tripcom"],
                               ["trip.com", "travel", "hotel", "flights", "deals"]))

    return offers


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    init_db()
    offers = get_offers()
    print(f"\nOffers to publish: {len(offers)}")
    for o in offers:
        print(f"  [{o.advertiser_id}] {o.advertiser_name} / {o.country} — {o.title[:65]}")

    print()
    published = []
    skipped = []

    for i, offer in enumerate(offers, 1):
        slug_base = re.sub(r'[^a-z0-9]+', '-',
                           f"{offer.advertiser_name}-{offer.title}".lower())[:60].strip('-')
        slug = slug_base

        print(f"\n[{i}/{len(offers)}] {offer.advertiser_name} → {offer.country} — {offer.title[:55]}")

        if post_exists_by_slug(slug, offer.country):
            print(f"  [skip] Post already exists: {slug}")
            skipped.append(slug)
            continue

        # 1. Fetch + upload featured image (scrape official site, fall back to Rakuten logo)
        image_url = fetch_advertiser_image(offer.advertiser_id)
        media_id = None
        if image_url:
            img_filename = re.sub(r'[^a-z0-9]+', '-', offer.advertiser_name.lower())
            media_id = upload_image(image_url, img_filename,
                                    f"{offer.advertiser_name} — {offer.title[:60]}", offer.country)

        # 2. Generate SEO content
        print("  [claude] Generating content…")
        try:
            data = generate_post(offer)
        except Exception as e:
            print(f"  [claude] ERROR: {e}")
            continue

        wp_title = data["wp_title"]
        wp_body = data["wp_body"]
        wp_excerpt = data["wp_excerpt"]
        focus_kw = data.get("focus_keyword", "")
        seo_title = data.get("seo_title", wp_title)
        tags = data.get("tags", offer.tags)

        seo = {
            "title": seo_title,
            "description": wp_excerpt,
            "focusKeyphrase": focus_kw,
        }

        # 3. Publish post
        print(f"  [wp] Publishing '{wp_title[:50]}' to /{offer.country}…")
        post = create_wp_post(
            country=offer.country,
            title=wp_title,
            content=wp_body,
            excerpt=wp_excerpt,
            slug=slug,
            category_ids=[offer.category_id],
            tags=tags,
            featured_media_id=media_id,
            seo=seo,
        )

        if post:
            print(f"  [ok] Published → {post['link']}")
            published.append({"title": wp_title, "url": post["link"], "country": offer.country})

        time.sleep(1)  # be gentle with the API

    print(f"\n{'='*60}")
    print(f"Done. Published: {len(published)}  Skipped: {len(skipped)}")
    for p in published:
        print(f"  [{p['country']}] {p['title'][:55]}")
        print(f"         {p['url']}")


if __name__ == "__main__":
    main()
