"""
Optimise Media adapter.
API reference: https://www.optimisemedia.com/api/
Strongest in APAC (HK, AU, SG) and UK.
"""
from __future__ import annotations

import json
import httpx

from octocoupon.config import settings
from .base import AffiliateAdapter, Advertiser, Coupon, CountryCode, is_expired

BASE_URL = "https://api.optimisemedia.com/v1"

COUNTRY_NETWORK: dict[CountryCode, str] = {
    "hk": "HK",
    "au": "AU",
    "sg": "SG",
    "uk": "UK",
}


class OptimiseAdapter(AffiliateAdapter):
    network = "optimise"

    def _headers(self) -> dict:
        return {"X-Api-Key": settings.optimise_api_key}

    def get_advertisers(self, country: CountryCode) -> list[Advertiser]:
        network = COUNTRY_NETWORK.get(country)
        if not network:
            return []

        resp = httpx.get(
            f"{BASE_URL}/publisher/programmes",
            headers=self._headers(),
            params={
                "publisherId": settings.optimise_publisher_id,
                "network": network,
                "status": "APPROVED",
                "pageSize": 500,
            },
            timeout=30,
        )
        resp.raise_for_status()
        return [
            Advertiser(
                id=str(a["id"]),
                network=self.network,
                name=a["name"],
                url=a.get("website", ""),
                country=country,
                logo_url=a.get("logo"),
                raw_json=json.dumps(a),
            )
            for a in resp.json().get("programmes", [])
        ]

    def get_coupons(self, advertiser_id: str, country: CountryCode) -> list[Coupon]:
        network = COUNTRY_NETWORK.get(country)
        if not network:
            return []

        resp = httpx.get(
            f"{BASE_URL}/publisher/vouchers",
            headers=self._headers(),
            params={
                "publisherId": settings.optimise_publisher_id,
                "programmeId": advertiser_id,
                "network": network,
                "status": "ACTIVE",
                "pageSize": 200,
            },
            timeout=30,
        )
        resp.raise_for_status()
        return [
            Coupon(
                id=f"optimise_{v['id']}",
                advertiser_id=advertiser_id,
                network=self.network,
                country=country,
                title=v.get("title", ""),
                description=v.get("description"),
                code=v.get("code"),
                discount=(
                    f"{v['discountValue']}% off" if v.get("discountType") == "PERCENT"
                    else f"{v.get('discountValue', '')} off" if v.get("discountValue")
                    else None
                ),
                start_date=v.get("startDate"),
                end_date=v.get("expiryDate"),
                affiliate_url=v.get("trackingLink", ""),
                raw_json=json.dumps(v),
            )
            for v in resp.json().get("vouchers", [])
            if not is_expired(v.get("expiryDate"))
        ]
