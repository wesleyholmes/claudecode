"""
Rakuten Advertising (formerly LinkShare) adapter.

Auth: uses a static Bearer token (RAKUTEN_TOKEN in .env).
      The OAuth client_credentials flow does NOT work for publisher coupon access.

Coupon feed:  GET /coupon/1.0  (XML)
Advertisers:  GET /v2/advertisers  (JSON)
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

import httpx

from octocoupon.config import settings
from .base import AffiliateAdapter, Advertiser, Coupon, CountryCode, is_expired

BASE_URL = "https://api.linksynergy.com"

# Rakuten uses numeric network IDs per region
COUNTRY_NETWORK: dict[CountryCode, str] = {
    "us": "1",
    "au": "41",
    "uk": "3",
}


def _headers() -> dict:
    if not settings.rakuten_token:
        raise RuntimeError("RAKUTEN_TOKEN must be set in .env")
    return {"Authorization": f"Bearer {settings.rakuten_token}"}


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
            meta = data.get("_metadata", {})
            if not meta.get("_links", {}).get("next") or len(batch) < 100:
                break
            page += 1

        return advertisers

    def get_coupons(self, advertiser_id: str, country: CountryCode) -> list[Coupon]:
        """Fetch coupons for a specific advertiser."""
        network_id = COUNTRY_NETWORK.get(country)
        if not network_id:
            return []

        resp = httpx.get(
            f"{BASE_URL}/coupon/1.0",
            headers=_headers(),
            params={"sid": settings.rakuten_sid, "mid": advertiser_id, "network": network_id, "limit": 200},
            timeout=30,
        )
        resp.raise_for_status()
        return _parse_coupon_xml(resp.text, advertiser_id, country)

    def get_all_coupons(self, country: CountryCode) -> list[Coupon]:
        """Fetch all available coupons at once (more efficient than per-advertiser)."""
        network_id = COUNTRY_NETWORK.get(country)
        if not network_id:
            return []

        resp = httpx.get(
            f"{BASE_URL}/coupon/1.0",
            headers=_headers(),
            params={"sid": settings.rakuten_sid, "limit": 500},
            timeout=30,
        )
        resp.raise_for_status()
        # Parse without a specific advertiser_id — each coupon carries its own mid
        return _parse_coupon_xml(resp.text, advertiser_id=None, country=country)


def _parse_coupon_xml(xml_text: str, advertiser_id: str | None, country: CountryCode) -> list[Coupon]:
    """Parse the /coupon/1.0 XML response into Coupon objects."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    coupons = []
    for link in root.findall("link"):
        end_date = link.findtext("offerenddate")
        if is_expired(end_date):
            continue

        promo_types = [pt.text for pt in link.findall("promotiontypes/promotiontype") if pt.text]
        categories = [c.text for c in link.findall("categories/category") if c.text]

        code_el = link.find("couponcode")
        code = code_el.text if code_el is not None else None

        mid = link.findtext("advertiserid") or advertiser_id or "unknown"
        offer_id = link.findtext("offerid") or ""
        coupons.append(Coupon(
            id=f"rakuten_{mid}_{offer_id}",
            advertiser_id=mid,
            network="rakuten",
            country=country,
            title=link.findtext("offerdescription") or "",
            description=", ".join(categories),
            code=code,
            discount=", ".join(promo_types) if promo_types else None,
            start_date=link.findtext("offerstartdate"),
            end_date=end_date,
            affiliate_url=link.findtext("clickurl") or "",
            raw_json=xml_text[:200],
        ))

    return coupons
