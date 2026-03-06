"""
WordPress REST API client.
Handles all country subsites via a single client — just pass the CountryCode
and it routes to the correct subsite URL.

WP Application Passwords: Users → Profile → Application Passwords
Docs: https://developer.wordpress.org/rest-api/
"""
from __future__ import annotations

import base64
from dataclasses import dataclass

import httpx

from octocoupon.config import settings

# country → subsite path (empty = root site)
COUNTRY_WP_PATH: dict[str, str] = {
    "us": "",
    "hk": "/hk",
    "au": "/au",
    "sg": "/sg",
    "uk": "/uk",
}


@dataclass
class WPPost:
    id: int
    url: str
    slug: str
    status: str


def _api_url(country: str) -> str:
    path = COUNTRY_WP_PATH.get(country, "")
    return f"{settings.wp_base_url}{path}/wp-json/wp/v2"


def _auth_header() -> dict:
    token = base64.b64encode(
        f"{settings.wp_username}:{settings.wp_app_password}".encode()
    ).decode()
    return {"Authorization": f"Basic {token}"}


def _resolve_tag_ids(client: httpx.Client, base: str, tags: list[str]) -> list[int]:
    ids = []
    for tag in tags:
        r = client.get(f"{base}/tags", params={"search": tag})
        r.raise_for_status()
        existing = r.json()
        if existing:
            ids.append(existing[0]["id"])
        else:
            r2 = client.post(f"{base}/tags", json={"name": tag})
            r2.raise_for_status()
            ids.append(r2.json()["id"])
    return ids


def create_post(
    country: str,
    title: str,
    content: str,
    excerpt: str,
    slug: str,
    tags: list[str] | None = None,
    status: str = "publish",
) -> WPPost:
    base = _api_url(country)
    headers = {**_auth_header(), "Content-Type": "application/json"}

    with httpx.Client(headers=headers, timeout=30) as client:
        tag_ids = _resolve_tag_ids(client, base, tags or [])

        resp = client.post(
            f"{base}/posts",
            json={
                "title": title,
                "content": content,
                "excerpt": excerpt,
                "slug": slug,
                "status": status,
                "tags": tag_ids,
            },
        )
        resp.raise_for_status()
        data = resp.json()

    return WPPost(
        id=data["id"],
        url=data["link"],
        slug=data["slug"],
        status=data["status"],
    )


def post_exists(country: str, slug: str) -> bool:
    base = _api_url(country)
    r = httpx.get(
        f"{base}/posts",
        headers=_auth_header(),
        params={"slug": slug},
        timeout=15,
    )
    r.raise_for_status()
    return len(r.json()) > 0
