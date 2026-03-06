"""Abstract base class for affiliate network adapters."""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

AffiliateNetwork = Literal["rakuten", "cj", "optimise"]
CountryCode = Literal["us", "hk", "au", "sg", "uk"]


@dataclass
class Advertiser:
    id: str
    network: AffiliateNetwork
    name: str
    url: str
    country: CountryCode
    logo_url: str | None = None
    raw_json: str | None = None


@dataclass
class Coupon:
    id: str
    advertiser_id: str
    network: AffiliateNetwork
    country: CountryCode
    title: str
    affiliate_url: str
    description: str | None = None
    code: str | None = None
    discount: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    raw_json: str | None = None


@dataclass
class SyncResult:
    network: AffiliateNetwork
    country: CountryCode
    advertisers: list[Advertiser] = field(default_factory=list)
    coupons: list[Coupon] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def is_expired(end_date: str | None) -> bool:
    if not end_date:
        return False
    try:
        return date.fromisoformat(end_date[:10]) < date.today()
    except ValueError:
        return False


class AffiliateAdapter(ABC):
    network: AffiliateNetwork

    @abstractmethod
    def get_advertisers(self, country: CountryCode) -> list[Advertiser]:
        """Return all advertisers the publisher is approved for."""

    @abstractmethod
    def get_coupons(self, advertiser_id: str, country: CountryCode) -> list[Coupon]:
        """Return active coupons for a single advertiser."""

    def sync(self, country: CountryCode) -> SyncResult:
        result = SyncResult(network=self.network, country=country)
        try:
            result.advertisers = self.get_advertisers(country)
        except Exception as exc:
            result.errors.append(f"get_advertisers: {exc}")
            return result

        for advertiser in result.advertisers:
            try:
                coupons = self.get_coupons(advertiser.id, country)
                result.coupons.extend(coupons)
            except Exception as exc:
                result.errors.append(f"get_coupons({advertiser.id}): {exc}")

        return result
