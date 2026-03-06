"""
Content generator — calls Claude to produce:
  - A WordPress post (title, HTML body, excerpt)
  - Social media captions (one per platform, localised per country)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

import anthropic

from octocoupon.config import settings
from octocoupon.affiliates.base import Coupon

# Per-country localisation hints passed to Claude
COUNTRY_CONTEXT = {
    "us": {"language": "English (US)", "currency": "USD", "tone": "casual American"},
    "hk": {"language": "Traditional Chinese (香港)", "currency": "HKD", "tone": "friendly Hong Kong style, mix English brand names naturally"},
    "au": {"language": "English (AU)", "currency": "AUD", "tone": "casual Australian"},
    "sg": {"language": "English (SG)", "currency": "SGD", "tone": "friendly Singaporean"},
    "uk": {"language": "English (UK)", "currency": "GBP", "tone": "friendly British"},
}

PLATFORM_HINTS = {
    "facebook":  "conversational, 100-200 words, include the link, end with a question to drive engagement",
    "instagram": "punchy, 3-5 lines, 5-10 relevant hashtags at end, note 'link in bio' instead of the URL",
    "threads":   "casual and conversational, 1-3 short paragraphs, no hashtags needed",
    "twitter":   "punchy, under 240 characters (excluding link), include 1-2 hashtags",
    "reddit":    "straightforward deal-post title style, no marketing fluff, include code and savings amount upfront",
    "rednote":   "written in Traditional Chinese, warm and personal tone (小红书 style), 3-5 paragraphs, 5-8 hashtags with # symbol",
}


@dataclass
class GeneratedContent:
    wp_title: str
    wp_body: str       # HTML
    wp_excerpt: str    # plain text, max 160 chars
    social_captions: dict[str, str] = field(default_factory=dict)


def generate(coupon: Coupon, platforms: list[str]) -> GeneratedContent:
    ctx = COUNTRY_CONTEXT.get(coupon.country, COUNTRY_CONTEXT["us"])
    platform_instructions = "\n".join(
        f'  "{p}": "{PLATFORM_HINTS[p]}"'
        for p in platforms
        if p in PLATFORM_HINTS
    )

    system = (
        f"You are a copywriter for Octocoupon, a coupon and deals website. "
        f"Write all content in {ctx['language']} ({ctx['tone']} tone). "
        f"Currency: {ctx['currency']}. "
        "Never invent discount amounts — use only what is provided in the coupon data. "
        "Output ONLY valid JSON, no markdown fences, no extra text."
    )

    user = f"""Generate content for this coupon deal:

Title: {coupon.title}
Description: {coupon.description or "N/A"}
Coupon Code: {coupon.code or "No code — discount auto-applied"}
Discount: {coupon.discount or "Special offer"}
Affiliate URL: {coupon.affiliate_url}
Expires: {coupon.end_date or "No expiry listed"}

Return this exact JSON shape:
{{
  "wp_title": "SEO-optimised post title, max 70 characters",
  "wp_body": "HTML for the WordPress post body. 150-300 words. Use <h2> subheadings, <ul> bullet points for key benefits, and a <a href=\\"{coupon.affiliate_url}\\">Shop Now</a> CTA button.",
  "wp_excerpt": "Plain-text meta description, max 160 characters",
  "social_captions": {{
{platform_instructions}
  }}
}}"""

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        system=system,
        messages=[{"role": "user", "content": user}],
    )

    text = "".join(block.text for block in message.content if hasattr(block, "text"))
    data = json.loads(text)

    return GeneratedContent(
        wp_title=data["wp_title"],
        wp_body=data["wp_body"],
        wp_excerpt=data["wp_excerpt"],
        social_captions=data.get("social_captions", {}),
    )
