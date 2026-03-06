"""
Commission Junction (CJ Affiliate) adapter.
Uses the GraphQL API for advertisers and the REST Coupon API for promotions.
API reference: https://developers.cj.com/docs/
"""
from __future__ import annotations

import json
import httpx

from octocoupon.config import settings
from .base import AffiliateAdapter, Advertiser, Coupon, CountryCode, is_expired

GRAPHQL_URL = "https://ads.api.cj.com/query"
COUPON_URL = "https://link.cj.com/v2/coupons"


class CJAdapter(AffiliateAdapter):
    network = "cj"

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {settings.cj_api_key}"}

    def get_advertisers(self, country: CountryCode) -> list[Advertiser]:
        query = f"""
        query {{
          publisherAccount(cid: "{settings.cj_cid}") {{
            joinedAdvertisers(limit: 500) {{
              records {{
                id
                name
                primaryUrl
                logoUrl
              }}
            }}
          }}
        }}
        """
        resp = httpx.post(
            GRAPHQL_URL,
            headers={**self._headers(), "Content-Type": "application/json"},
            json={"query": query},
            timeout=30,
        )
        resp.raise_for_status()
        records = (
            resp.json()
            .get("data", {})
            .get("publisherAccount", {})
            .get("joinedAdvertisers", {})
            .get("records", [])
        )
        return [
            Advertiser(
                id=str(a["id"]),
                network=self.network,
                name=a["name"],
                url=a.get("primaryUrl", ""),
                country=country,
                logo_url=a.get("logoUrl"),
                raw_json=json.dumps(a),
            )
            for a in records
        ]

    def get_coupons(self, advertiser_id: str, country: CountryCode) -> list[Coupon]:
        resp = httpx.get(
            COUPON_URL,
            headers=self._headers(),
            params={
                "publisher-id": settings.cj_cid,
                "advertiser-id": advertiser_id,
                "promotion_type": "coupon",
                "limit": 200,
            },
            timeout=30,
        )
        resp.raise_for_status()

        raw_coupons = resp.json().get("coupons", {}).get("coupon", [])
        # API returns a single dict instead of a list when there's only one result
        if isinstance(raw_coupons, dict):
            raw_coupons = [raw_coupons]

        return [
            Coupon(
                id=f"cj_{c['id']}",
                advertiser_id=advertiser_id,
                network=self.network,
                country=country,
                title=c.get("title", ""),
                description=c.get("description"),
                code=c.get("coupon-code"),
                discount=(
                    f"{c['savings-percent']}% off" if c.get("savings-percent")
                    else f"${c['savings-dollar']} off" if c.get("savings-dollar")
                    else None
                ),
                start_date=c.get("start-date"),
                end_date=c.get("end-date"),
                affiliate_url=c.get("link", ""),
                raw_json=json.dumps(c),
            )
            for c in raw_coupons
            if not is_expired(c.get("end-date"))
        ]
