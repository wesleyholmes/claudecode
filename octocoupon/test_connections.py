"""Quick connection test for Rakuten and WordPress."""
import sys
import httpx
import base64
from pathlib import Path

# Load .env manually so we don't need pydantic-settings installed
env = {}
env_file = Path(__file__).parent / ".env"
for line in env_file.read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip()

print("=" * 60)
print("CONNECTION TESTS")
print("=" * 60)

# ── Rakuten ─────────────────────────────────────────────────────
print("\n[1] Rakuten — OAuth token exchange")
try:
    r = httpx.post(
        "https://api.rakutenadvertising.com/token",
        auth=(env["RAKUTEN_CLIENT_ID"], env["RAKUTEN_CLIENT_SECRET"]),
        data={"grant_type": "client_credentials", "scope": env.get("RAKUTEN_SCOPE", "Production")},
        timeout=15,
    )
    if r.status_code == 200:
        token = r.json().get("access_token", "")
        expires = r.json().get("expires_in", "?")
        print(f"  ✓ Token obtained — expires_in={expires}s, token={token[:20]}...")
        RAKUTEN_TOKEN = token
    else:
        print(f"  ✗ HTTP {r.status_code}: {r.text[:300]}")
        RAKUTEN_TOKEN = None
except Exception as e:
    print(f"  ✗ Error: {e}")
    RAKUTEN_TOKEN = None

# ── Rakuten: list advertisers ────────────────────────────────────
if RAKUTEN_TOKEN:
    print("\n[2] Rakuten — fetch approved advertisers (US, site_id=1)")
    try:
        r = httpx.get(
            "https://api.rakutenadvertising.com/advertisers",
            headers={"Authorization": f"Bearer {RAKUTEN_TOKEN}"},
            params={"siteId": "1", "status": "approved", "limit": 5},
            timeout=30,
        )
        if r.status_code == 200:
            data = r.json()
            advertisers = data.get("advertisers", data if isinstance(data, list) else [])
            print(f"  ✓ {len(advertisers)} advertisers returned (showing up to 5)")
            for a in advertisers[:3]:
                print(f"    • {a.get('name','?')} (id={a.get('id','?')})")
        else:
            print(f"  ✗ HTTP {r.status_code}: {r.text[:300]}")
    except Exception as e:
        print(f"  ✗ Error: {e}")

# ── WordPress ────────────────────────────────────────────────────
print("\n[3] WordPress — REST API ping")
wp_url = env.get("WP_BASE_URL", "").rstrip("/")
wp_user = env.get("WP_USERNAME", "")
wp_pass = env.get("WP_APP_PASSWORD", "")
token = base64.b64encode(f"{wp_user}:{wp_pass}".encode()).decode()
headers = {"Authorization": f"Basic {token}"}

try:
    r = httpx.get(f"{wp_url}/wp-json/wp/v2", headers=headers, timeout=15)
    if r.status_code == 200:
        info = r.json()
        print(f"  ✓ Connected — site: {info.get('name','?')} ({info.get('url','?')})")
    else:
        print(f"  ✗ HTTP {r.status_code}: {r.text[:300]}")
except Exception as e:
    print(f"  ✗ Error: {e}")

print("\n[4] WordPress — check /posts endpoint (US root site)")
try:
    r = httpx.get(f"{wp_url}/wp-json/wp/v2/posts", headers=headers, params={"per_page": 3}, timeout=15)
    if r.status_code == 200:
        posts = r.json()
        print(f"  ✓ Posts endpoint OK — {len(posts)} recent posts")
        for p in posts[:2]:
            print(f"    • [{p.get('status','?')}] {p.get('title',{}).get('rendered','?')[:60]}")
    elif r.status_code == 401:
        print(f"  ✗ 401 Unauthorized — check WP_USERNAME and WP_APP_PASSWORD")
    else:
        print(f"  ✗ HTTP {r.status_code}: {r.text[:200]}")
except Exception as e:
    print(f"  ✗ Error: {e}")

print("\n" + "=" * 60)
