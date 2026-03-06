"""
Publisher: generates coupon posts for all unique offers from
Adidas HK, Chow Sang Sang, and Trip.com.

Deletes any previously created wrong-type (regular `post`) entries before
re-publishing everything as the `coupon` custom post type.

Run:  .venv/bin/python publish_offers.py
"""
from __future__ import annotations

import base64
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from urllib.parse import urlparse

import anthropic
import httpx

sys.path.insert(0, ".")
from octocoupon.affiliates.rakuten import _get_token
from octocoupon.config import settings
from octocoupon.db.connection import get_db, init_db

# ── Config ────────────────────────────────────────────────────────────────────

SCRAPE_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

COUNTRY_WP_PATH = {"us": "", "hk": "/hk", "au": "/au", "sg": "/sg", "uk": "/uk"}

# WP coupon-store term IDs (from existing taxonomy)
STORE_TERM_IDS = {
    "44931": 58,   # Adidas HK
    "42929": 70,   # Chow Sang Sang
    "52696": 57,   # Trip.com
    "39673": 69,   # Agent Provocateur
}

# WP coupon-category term IDs (from existing taxonomy)
CATEGORY_TERM_IDS = {
    "44931": 41,   # Adidas → Spoorting (41)
    "42929": 35,   # Chow Sang Sang → Jewlery (35)
    "52696": 43,   # Trip.com → Travel (43)
    "39673": 20,   # Agent Provocateur → Clothing (20)
}

# Advertiser official sites (for OG image fallback)
ADVERTISER_SITES = {
    "44931": "https://www.adidas.com.hk/en",
    "42929": "https://www.chowsangsang.com",
    "52696": "https://www.trip.com",
    "39673": "https://www.agentprovocateur.com",
}

# Advertiser display names for deletion matching
ADVERTISER_NAME_PATTERNS = ["adidas", "chow sang sang", "trip.com", "trip com"]


# ── WordPress helpers ─────────────────────────────────────────────────────────

def _wp_auth() -> str:
    return base64.b64encode(f"{settings.wp_username}:{settings.wp_app_password}".encode()).decode()

def _wp_base(country: str) -> str:
    return f"{settings.wp_base_url}{COUNTRY_WP_PATH.get(country, '')}/wp-json/wp/v2"

def _wp_headers(content_type: str = "application/json") -> dict:
    return {"Authorization": f"Basic {_wp_auth()}", "Content-Type": content_type}


def delete_wrong_type_posts(countries: list[str] = ("us", "hk")) -> int:
    """
    Find and permanently delete any regular `post` type entries that match
    our advertiser names. These were created by an earlier run using the wrong
    post type and should be replaced with `coupon` type posts.
    """
    deleted = 0
    for country in countries:
        base = _wp_base(country)
        # Fetch up to 100 regular posts
        r = httpx.get(f"{base}/posts", headers=_wp_headers(),
                      params={"per_page": 100, "status": "publish,draft,trash"}, timeout=20)
        if r.status_code != 200:
            print(f"  [delete] Could not fetch posts for {country}: {r.status_code}")
            continue

        posts = r.json()
        for post in posts:
            title_raw = post.get("title", {}).get("rendered", "").lower()
            slug = post.get("slug", "").lower()
            # Match on title or slug containing any of our advertiser patterns
            if any(p in title_raw or p in slug for p in ADVERTISER_NAME_PATTERNS):
                post_id = post["id"]
                # force=True bypasses trash and permanently deletes
                dr = httpx.delete(f"{base}/posts/{post_id}",
                                  headers=_wp_headers(),
                                  params={"force": "true"}, timeout=15)
                status = dr.status_code
                print(f"  [delete] {country} post #{post_id} '{title_raw[:55]}' → HTTP {status}")
                if status in (200, 201):
                    deleted += 1

    return deleted


# ── Image helpers ──────────────────────────────────────────────────────────────

def _extract_og_image(html: str, base_url: str) -> str | None:
    """Extract the best og:image / twitter:image from HTML."""
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
            elif img.startswith("/"):
                p = urlparse(base_url)
                img = f"{p.scheme}://{p.netloc}{img}"
            return img
    return None


def fetch_promo_image(click_url: str, advertiser_id: str) -> str:
    """
    Try to find a relevant promotional image:
    1. Follow the affiliate click URL to the landing page, grab og:image
    2. Fall back to og:image on the advertiser's main site
    Returns an image URL string (may be empty if nothing found).
    """
    # 1. Try landing page from click URL
    if click_url:
        try:
            r = httpx.get(click_url, headers=SCRAPE_HEADERS, timeout=20, follow_redirects=True)
            img = _extract_og_image(r.text, str(r.url))
            if img:
                print(f"  [img] Landing page OG image: {img[:80]}")
                return img
        except Exception as e:
            print(f"  [img] Landing page scrape failed: {e}")

    # 2. Fall back to advertiser main site
    site_url = ADVERTISER_SITES.get(advertiser_id)
    if site_url:
        try:
            r = httpx.get(site_url, headers=SCRAPE_HEADERS, timeout=15, follow_redirects=True)
            img = _extract_og_image(r.text, site_url)
            if img:
                print(f"  [img] Advertiser site OG image: {img[:80]}")
                return img
        except Exception as e:
            print(f"  [img] Advertiser site scrape failed: {e}")

    print("  [img] No image found")
    return ""


def upload_image(image_url: str, filename: str, alt_text: str, country: str = "us") -> int | None:
    """Download an image and upload to WP media library. Returns WP media ID."""
    try:
        r = httpx.get(image_url, headers=SCRAPE_HEADERS, timeout=20, follow_redirects=True)
        if r.status_code != 200:
            print(f"  [img] Download failed {r.status_code}: {image_url[:80]}")
            return None

        ct = r.headers.get("content-type", "image/jpeg").split(";")[0].strip()
        ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif"}.get(ct, "jpg")
        fname = f"{filename}.{ext}"

        base = _wp_base(country)
        upload_headers = {
            "Authorization": f"Basic {_wp_auth()}",
            "Content-Disposition": f'attachment; filename="{fname}"',
            "Content-Type": ct,
        }
        resp = httpx.post(f"{base}/media", headers=upload_headers, content=r.content, timeout=30)
        if resp.status_code in (200, 201):
            media = resp.json()
            media_id = media["id"]
            # Update alt text
            httpx.post(f"{base}/media/{media_id}", headers=_wp_headers(),
                       content=json.dumps({"alt_text": alt_text}), timeout=15)
            print(f"  [img] Uploaded → media_id={media_id}")
            return media_id
        else:
            print(f"  [img] Upload failed: {resp.status_code} {resp.text[:120]}")
            return None
    except Exception as e:
        print(f"  [img] Error uploading: {e}")
        return None


# ── WordPress coupon creation ──────────────────────────────────────────────────

def coupon_exists_by_slug(slug: str, country: str = "us") -> bool:
    base = _wp_base(country)
    r = httpx.get(f"{base}/coupon", headers=_wp_headers(),
                  params={"slug": slug}, timeout=15)
    return len(r.json()) > 0 if r.status_code == 200 else False


def create_coupon_post(
    country: str,
    title: str,
    content: str,
    excerpt: str,
    slug: str,
    coupon_code: str | None,
    coupon_url: str,
    expire: str | None,
    store_term_id: int,
    category_term_id: int,
    featured_media_id: int | None,
    focus_keyword: str = "",
    seo_title: str = "",
) -> dict | None:
    """Create a WordPress coupon post with all custom fields."""
    base = _wp_base(country)

    payload: dict = {
        "title": title,
        "content": content,
        "excerpt": excerpt,
        "slug": slug,
        "status": "publish",
        "coupon-store": [store_term_id],
        "coupon-category": [category_term_id],
        "coupon_code": coupon_code or "",
        "coupon_url": coupon_url,
        "ctype": "coupon" if coupon_code else "deal",
    }

    if expire:
        # expire field takes a year string like "2025" or "2026"
        year = expire[:4] if len(expire) >= 4 else expire
        payload["expire"] = year

    if featured_media_id:
        payload["featured_media"] = featured_media_id

    r = httpx.post(f"{base}/coupon", headers=_wp_headers(),
                   content=json.dumps(payload), timeout=30)

    if r.status_code not in (200, 201):
        print(f"  [wp] Coupon create failed: {r.status_code} {r.text[:200]}")
        return None

    post = r.json()
    post_id = post["id"]

    # Write Yoast SEO fields
    if focus_keyword or seo_title:
        seo_payload = {}
        if seo_title:
            seo_payload["yoast_title"] = seo_title
        if focus_keyword:
            seo_payload["yoast_focuskw"] = focus_keyword
        if excerpt:
            seo_payload["yoast_metadesc"] = excerpt
        httpx.post(f"{base}/coupon/{post_id}", headers=_wp_headers(),
                   content=json.dumps(seo_payload), timeout=15)

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
    country: str


def generate_post(offer: Offer) -> dict:
    """Call Claude to generate clean SEO content. Returns dict with post fields."""
    lang_map = {"us": "English (US)", "hk": "English", "au": "English (AU)", "sg": "English (SG)", "uk": "English (UK)"}
    currency_map = {"us": "USD", "hk": "HKD", "au": "AUD", "sg": "SGD", "uk": "GBP"}
    lang = lang_map.get(offer.country, "English")
    currency = currency_map.get(offer.country, "USD")

    code_block = ""
    if offer.code:
        code_block = (
            f'\\n<div style="background:#f5f5f5;border:2px dashed #333;'
            f'padding:16px;text-align:center;font-size:1.3em;'
            f'font-weight:bold;letter-spacing:2px;margin:24px 0;">'
            f'Use code: {offer.code}</div>'
        )

    prompt = f"""You are an SEO copywriter for Octocoupon, a deals and coupon website.

Write a post for this offer. Output ONLY valid JSON with no markdown fences.

Offer:
- Advertiser: {offer.advertiser_name}
- Title: {offer.title}
- Discount: {offer.discount}
- Coupon code: {offer.code or "No code needed — discount applied automatically"}
- Expires: {offer.end_date or "No expiry listed"}
- Affiliate URL: {offer.affiliate_url}
- Language: {lang}
- Currency: {currency}

Content rules:
- Do NOT include any images, logos, icons, or <img> tags in the HTML body
- Do NOT include inline CSS for images
- Do NOT invent discount amounts not stated in the offer
- Write clean, engaging, SEO-optimised copy only
- Post body HTML structure:
  * ONE <h2> subheading summarising the deal
  * ONE more <h2> with keyword variation (e.g. "How to redeem", "Why shop at X")
  * <ul> with 4-5 bullet points highlighting deal benefits
  * If a code exists, include this exact HTML block:{code_block}
  * End with a CTA: <p style="text-align:center;margin:24px 0;"><a href="{offer.affiliate_url}" target="_blank" rel="sponsored noopener" style="display:inline-block;background:#000;color:#fff;padding:14px 32px;text-decoration:none;font-weight:bold;border-radius:4px;font-size:1.05em;">Shop Now →</a></p>
- Total body length: 200-350 words

Return this exact JSON:
{{
  "wp_title": "SEO title 50-60 chars, brand + main benefit",
  "wp_body": "Full HTML post body",
  "wp_excerpt": "Meta description 140-160 chars with keyword and CTA",
  "focus_keyword": "primary SEO keyword phrase (3-5 words)",
  "seo_title": "SEO title tag, 50-60 chars (can match wp_title)"
}}"""

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2500,
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
    r.raise_for_status()
    root = ET.fromstring(r.text)

    all_links = []
    for link in root.findall("link"):
        all_links.append({
            "mid": link.findtext("advertiserid"),
            "name": link.findtext("advertisername"),
            "title": (link.findtext("offerdescription") or "").strip(),
            "code": link.findtext("couponcode"),
            "discount": ", ".join(pt.text for pt in link.findall("promotiontypes/promotiontype") if pt.text),
            "end_date": (link.findtext("offerenddate") or "")[:10],
            "click_url": link.findtext("clickurl") or "",
        })

    def to_offer(l: dict, country: str) -> Offer:
        return Offer(
            advertiser_id=l["mid"],
            advertiser_name=l["name"],
            title=l["title"],
            description=l["discount"],
            code=l["code"],
            discount=l["discount"],
            end_date=l["end_date"],
            affiliate_url=l["click_url"],
            country=country,
        )

    # ── Adidas HK ────────────────────────────────────────────────────────────
    offers: list[Offer] = []
    for l in (l for l in all_links if l["mid"] == "44931"):
        offers.append(to_offer(l, "hk"))

    # ── Chow Sang Sang: English offers only, deduplicated ────────────────────
    seen_css: set[str] = set()
    for l in (l for l in all_links if l["mid"] == "42929"):
        title = l["title"]
        if len(re.findall(r'[a-zA-Z]', title)) < 6:
            continue   # skip Chinese-dominant titles
        norm = re.sub(r'[^a-z0-9\s]', '', title.lower())[:70].strip()
        if norm not in seen_css:
            seen_css.add(norm)
            offers.append(to_offer(l, "us"))

    # ── Trip.com: curated selection for our markets ───────────────────────────
    RELEVANT_TRIP_KEYS = [
        "Find the Best Travel Deals",
        "eSIM Card 8% Off",
        "Trip.com Attraction And Ticket",
        "Autumn Scenery Deals - US!",
        "Autumn Scenery Deals - HK-ZH!",
        "Autumn Scenery Deals - EN-SG!",
    ]
    seen_trip: set[str] = set()
    for l in (l for l in all_links if l["mid"] == "52696"):
        for key in RELEVANT_TRIP_KEYS:
            if key.lower() in l["title"].lower():
                if key not in seen_trip:
                    seen_trip.add(key)
                    country = "hk" if "HK-ZH" in l["title"] else "sg" if "EN-SG" in l["title"] else "us"
                    offers.append(to_offer(l, country))
                break

    return offers


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    init_db()

    # Step 1: Delete wrong-type posts
    print("=" * 60)
    print("Step 1: Deleting wrong-type regular posts…")
    n_deleted = delete_wrong_type_posts(countries=["us", "hk"])
    print(f"  Deleted {n_deleted} wrong-type posts\n")

    # Step 2: Gather offers
    print("Step 2: Fetching offers from Rakuten…")
    offers = get_offers()
    print(f"  {len(offers)} offers to publish:")
    for o in offers:
        print(f"    [{o.advertiser_id}] {o.advertiser_name} / {o.country} — {o.title[:60]}")

    print()
    published = []
    skipped = []

    # Step 3: Publish each offer as a coupon post
    print("Step 3: Publishing coupon posts…")
    for i, offer in enumerate(offers, 1):
        slug = re.sub(r'[^a-z0-9]+', '-',
                      f"{offer.advertiser_name}-{offer.title}".lower())[:65].strip('-')

        print(f"\n[{i}/{len(offers)}] {offer.advertiser_name} → {offer.country}")
        print(f"  Title: {offer.title[:65]}")

        if coupon_exists_by_slug(slug, offer.country):
            print(f"  [skip] Coupon already exists: {slug}")
            skipped.append(slug)
            continue

        # Skip SG — subsite does not exist yet
        if offer.country == "sg":
            print("  [skip] SG subsite not provisioned")
            skipped.append(slug)
            continue

        # 1. Fetch promo image from landing page
        print("  [img] Finding promo image…")
        img_url = fetch_promo_image(offer.affiliate_url, offer.advertiser_id)
        media_id = None
        if img_url:
            img_filename = re.sub(r'[^a-z0-9]+', '-',
                                  f"{offer.advertiser_name}-{offer.title[:40]}".lower())
            media_id = upload_image(
                img_url, img_filename,
                f"{offer.advertiser_name} — {offer.title[:60]}",
                offer.country,
            )

        # 2. Generate SEO content
        print("  [claude] Generating content…")
        try:
            data = generate_post(offer)
        except Exception as e:
            print(f"  [claude] ERROR: {e}")
            continue

        wp_title    = data["wp_title"]
        wp_body     = data["wp_body"]
        wp_excerpt  = data["wp_excerpt"]
        focus_kw    = data.get("focus_keyword", "")
        seo_title   = data.get("seo_title", wp_title)

        # 3. Publish as coupon post
        store_id    = STORE_TERM_IDS.get(offer.advertiser_id)
        category_id = CATEGORY_TERM_IDS.get(offer.advertiser_id)

        if not store_id or not category_id:
            print(f"  [skip] No store/category term IDs for advertiser {offer.advertiser_id}")
            skipped.append(slug)
            continue

        print(f"  [wp] Publishing '{wp_title[:50]}' to /{offer.country}…")
        post = create_coupon_post(
            country=offer.country,
            title=wp_title,
            content=wp_body,
            excerpt=wp_excerpt,
            slug=slug,
            coupon_code=offer.code,
            coupon_url=offer.affiliate_url,
            expire=offer.end_date,
            store_term_id=store_id,
            category_term_id=category_id,
            featured_media_id=media_id,
            focus_keyword=focus_kw,
            seo_title=seo_title,
        )

        if post:
            url = post.get("link", "")
            print(f"  [ok] Published → {url}")
            published.append({"title": wp_title, "url": url, "country": offer.country})
        else:
            print("  [fail] Post creation returned no result")

        time.sleep(1)

    # Summary
    print(f"\n{'='*60}")
    print(f"Done.  Published: {len(published)}   Skipped: {len(skipped)}")
    for p in published:
        print(f"  [{p['country']}] {p['title'][:55]}")
        print(f"         {p['url']}")


if __name__ == "__main__":
    main()
