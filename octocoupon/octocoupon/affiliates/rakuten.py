"""
Rakuten Advertising (formerly LinkShare) adapter.
API reference: https://developers.rakutenadvertising.com/
"""
from __future__ import annotations

import json
import time
import httpx

from octocoupon.config import settings
from .base import AffiliateAdapter, Advertiser, Coupon, CountryCode, is_expired

BASE_URL = "https://api.linksynergy.com"
TOKEN_URL = "https://api.linksynergy.com/token"

# Rakuten uses numeric site IDs per region
COUNTRY_SITE: dict[CountryCode, str] = {
    "us": "1",
    "au": "41",
    "uk": "3",
}

# In-memory token cache: (access_token, expiry_timestamp)
_token_cache: tuple[str, float] | None = None


def _fetch_token() -> str:
    """Exchange client credentials for a Bearer token, caching until expiry."""
    global _token_cache
    now = time.time()
    if _token_cache and now < _token_cache[1] - 60:  # 60s buffer before expiry
        return _token_cache[0]

    if not settings.rakuten_client_id or not settings.rakuten_client_secret:
        raise RuntimeError("RAKUTEN_CLIENT_ID and RAKUTEN_CLIENT_SECRET must be set in .env")

    resp = httpx.post(
        TOKEN_URL,
        auth=(settings.rakuten_client_id, settings.rakuten_client_secret),
        data={"grant_type": "client_credentials", "scope": settings.rakuten_scope},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    token = data["access_token"]
    expires_in = data.get("expires_in", 3600)
    _token_cache = (token, now + expires_in)
    return token


class RakutenAdapter(AffiliateAdapter):
    network = "rakuten"

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {_fetch_token()}"}

    def get_advertisers(self, country: CountryCode) -> list[Advertiser]:
        site_id = COUNTRY_SITE.get(country)
        if not site_id:
            return []

        resp = httpx.get(
            f"{BASE_URL}/advertisers",
            headers=self._headers(),
            params={"siteId": site_id, "status": "approved", "limit": 500},
            timeout=30,
        )
        resp.raise_for_status()
        return [
            Advertiser(
                id=str(a["id"]),
                network=self.network,
                name=a["name"],
                url=a.get("url", ""),
                country=country,
                logo_url=a.get("logoUrl"),
                raw_json=json.dumps(a),
            )
            for a in resp.json().get("advertisers", [])
        ]

    def get_coupons(self, advertiser_id: str, country: CountryCode) -> list[Coupon]:
        site_id = COUNTRY_SITE.get(country)
        if not site_id:
            return []

        resp = httpx.get(
            f"{BASE_URL}/coupons",
            headers=self._headers(),
            params={"advertiserId": advertiser_id, "siteId": site_id, "status": "active", "limit": 200},
            timeout=30,
        )
        resp.raise_for_status()

        return [
            Coupon(
                id=f"rakuten_{c['id']}",
                advertiser_id=advertiser_id,
                network=self.network,
                country=country,
                title=c.get("title") or c.get("name", ""),
                description=c.get("description"),
                code=c.get("couponCode"),
                discount=f"{c['discountAmount']} {c['discountType']}" if c.get("discountType") else None,
                start_date=c.get("startDate"),
                end_date=c.get("endDate"),
                affiliate_url=c["clickUrl"],
                raw_json=json.dumps(c),
            )
            for c in resp.json().get("coupons", [])
            if not is_expired(c.get("endDate"))
        ]
