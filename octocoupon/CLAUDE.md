# CLAUDE.md — octocoupon

Project-specific instructions for Claude Code when working in this directory.

## What this project does

**octocoupon** is an affiliate coupon automation pipeline:
- Fetches deals from affiliate networks (Rakuten/LinkShare, Commission Junction, Optimise)
- Generates SEO blog posts via Claude (Anthropic API)
- Publishes to WordPress
- Cross-posts to social platforms (Twitter/X, Facebook, Instagram, Threads, Reddit, RedNote)

## Running the project

```bash
cd ~/claudecode/octocoupon

# Run any command
.venv/bin/python -m octocoupon --help
.venv/bin/python -m octocoupon sync       # fetch deals from affiliates
.venv/bin/python -m octocoupon publish    # generate + post to WordPress
.venv/bin/python -m octocoupon social     # cross-post to social
.venv/bin/python -m octocoupon status     # show DB stats
.venv/bin/python -m octocoupon schedule   # start scheduler daemon
```

## Stack

- **Python 3.12** — virtual env at `.venv/`
- **Pydantic Settings** — config from `.env` (see `.env.example`)
- **Anthropic SDK** — content generation via Claude
- **httpx** — async HTTP for API calls
- **APScheduler** — cron-style scheduling
- **SQLite** — local deal/post tracking DB at `~/.octocoupon/octocoupon.db`

## Project structure

```
octocoupon/
├── CLAUDE.md                   # this file
├── pyproject.toml
├── requirements.txt
├── .env                        # credentials (gitignored)
├── .env.example                # template
└── octocoupon/
    ├── affiliates/             # network adapters (Rakuten, CJ, Optimise)
    ├── content/                # Claude-powered post generator
    ├── publishers/             # WordPress + social publishers
    ├── db/                     # SQLite connection + queries
    ├── pipeline.py             # orchestrates sync/publish/social
    ├── scheduler.py            # APScheduler wrapper
    └── cli.py                  # Click CLI entrypoint
```

## Key files

| File | Purpose |
|------|---------|
| `octocoupon/affiliates/base.py` | Base class all affiliate adapters inherit |
| `octocoupon/affiliates/optimise.py` | Optimise/Impact adapter |
| `octocoupon/affiliates/cj.py` | Commission Junction adapter |
| `octocoupon/content/generator.py` | Claude API content generation |
| `octocoupon/publishers/wordpress.py` | WordPress REST API publisher |
| `octocoupon/publishers/social/` | Per-platform social publishers |
| `octocoupon/pipeline.py` | Main pipeline orchestration |
| `octocoupon/cli.py` | CLI commands |

## Environment / credentials

All secrets live in `.env` (gitignored). Copy `.env.example` to get started.
Required for basic Rakuten → WordPress flow:
- `ANTHROPIC_API_KEY`
- `RAKUTEN_TOKEN` + `RAKUTEN_WEBSITE_ID`
- `WORDPRESS_URL` + `WORDPRESS_USERNAME` + `WORDPRESS_APP_PASSWORD`

## Development notes

- Use `.venv/bin/python` prefix (Ubuntu 24.04 blocks global pip installs)
- Activate venv with `source .venv/bin/activate` if doing multiple commands
- Logs go to console + `~/.octocoupon/octocoupon.log`
- First-run creates `~/.octocoupon/octocoupon.db` automatically
