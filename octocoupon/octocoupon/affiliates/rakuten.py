"""
Rakuten Advertising (formerly LinkShare) adapter.

Auth: OAuth 2.0 client_credentials. The scope MUST be set to the publisher
      SID (not "Production") for the token to carry publisher identity.
      Token expires in 3600s and is cached in memory.

Advertisers: GET /v2/advertisers  (JSON)
Coupons:     GET /coupon/1.0      (XML)
"""
from __future__ import annotations

import time
import xml.etree.ElementTree as ET

import httpx

from octocoupon.config import settings
from .base import AffiliateAdapter, Advertiser, Coupon, CountryCode, is_expired

BASE_URL = "https://api.linksynergy.com"
TOKEN_URL = "https://api.linksynergy.com/token"

# Rakuten numeric network IDs per region
COUNTRY_NETWORK: dict[CountryCode, str] = {
    "us": "1",
    "au": "41",
    "uk": "3",
}

# In-memory token cache: (access_token, expiry_timestamp)
_token_cache: tuple[str, float] | None = None


def _get_token() -> str:
    """Exchange client credentials for a Bearer token. Scope must be the publisher SID."""
    global _token_cache
    now = time.time()
    if _token_cache and now < _token_cache[1] - 60:
        return _token_cache[0]

    if not settings.rakuten_client_id or not settings.rakuten_client_secret:
        raise RuntimeError("RAKUTEN_CLIENT_ID and RAKUTEN_CLIENT_SECRET must be set in .env")
    if not settings.rakuten_sid:
        raise RuntimeError("RAKUTEN_SID must be set in .env (your publisher Site ID)")

    resp = httpx.post(
        TOKEN_URL,
        auth=(settings.rakuten_client_id, settings.rakuten_client_secret),
        # scope = publisher SID — this is what causes the token to carry publisher identity
        data={"grant_type": "client_credentials", "scope": settings.rakuten_sid},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    token = data["access_token"]
    expires_in = data.get("expires_in", 3600)
    _token_cache = (token, now + expires_in)
    return token


def _headers() -> dict:
    return {"Authorization": f"Bearer {_get_token()}"}


class RakutenAdapter(AffiliateAdapter):
    network = "rakuten"

    def get_advertisers(self, country: CountryCode) -> list[Advertiser]:
        network_id = COUNTRY_NETWORK.get(country)
        if not network_id:
            return []

        advertisers = []
        page = 1
        while True:
            resp = httpx.get(
                f"{BASE_URL}/v2/advertisers",
                headers=_headers(),
                params={"siteId": settings.rakuten_sid, "network": network_id, "page": page, "limit": 100},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            batch = data.get("advertisers", [])
            for a in batch:
                advertisers.append(Advertiser(
                    id=str(a["id"]),
                    network=self.network,
                    name=a["name"],
                    url=a.get("url", ""),
                    country=country,
                    logo_url=a.get("logo_url"),
                    raw_json=str(a),
                ))
            if not data.get("_metadata", {}).get("_links", {}).get("next") or len(batch) < 100:
                break
            page += 1

        return advertisers

    def get_coupons(self, advertiser_id: str, country: CountryCode) -> list[Coupon]:
        """Fetch coupons for a specific advertiser."""
        resp = httpx.get(
            f"{BASE_URL}/coupon/1.0",
            headers=_headers(),
            params={"sid": settings.rakuten_sid, "mid": advertiser_id, "limit": 200},
            timeout=30,
        )
        resp.raise_for_status()
        return _parse_coupon_xml(resp.text, advertiser_id, country)

    def get_all_coupons(self, country: CountryCode) -> list[Coupon]:
        """Fetch all available coupons at once (more efficient than per-advertiser)."""
        network_id = COUNTRY_NETWORK.get(country)
        resp = httpx.get(
            f"{BASE_URL}/coupon/1.0",
            headers=_headers(),
            params={"sid": settings.rakuten_sid, "limit": 500},
            timeout=30,
        )
        resp.raise_for_status()
        all_coupons = _parse_coupon_xml(resp.text, advertiser_id=None, country=country)
        # Filter to the requested country's network if possible
        if network_id:
            return [c for c in all_coupons if c.raw_json and f'"network": "{network_id}"' in c.raw_json] or all_coupons
        return all_coupons


def _parse_coupon_xml(xml_text: str, advertiser_id: str | None, country: CountryCode) -> list[Coupon]:
    """Parse the /coupon/1.0 XML response into Coupon objects."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    # Error response
    if root.tag == "fault":
        return []

    coupons = []
    for link in root.findall("link"):
        end_date = link.findtext("offerenddate")
        if is_expired(end_date):
            continue

        promo_types = [pt.text for pt in link.findall("promotiontypes/promotiontype") if pt.text]
        categories = [c.text for c in link.findall("categories/category") if c.text]
        network_el = link.find("network")
        network_id = network_el.get("id") if network_el is not None else ""

        mid = link.findtext("advertiserid") or advertiser_id or "unknown"
        offer_id = link.findtext("offerid") or ""
        code_el = link.find("couponcode")
        advertiser_name = link.findtext("advertisername") or ""

        coupons.append(Coupon(
            id=f"rakuten_{mid}_{offer_id}",
            advertiser_id=mid,
            network="rakuten",
            country=country,
            title=link.findtext("offerdescription") or "",
            description=", ".join(categories),
            code=code_el.text if code_el is not None else None,
            discount=", ".join(promo_types) if promo_types else None,
            start_date=link.findtext("offerstartdate"),
            end_date=end_date,
            affiliate_url=link.findtext("clickurl") or "",
            raw_json=f'{{"network": "{network_id}", "advertiser": "{advertiser_name}"}}',
        ))

    return coupons
