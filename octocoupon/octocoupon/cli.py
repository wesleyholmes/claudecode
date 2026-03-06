"""
Octocoupon CLI — entry point for all commands.

Usage:
  octocoupon sync        Pull coupons from all affiliate networks
  octocoupon publish     Generate AI content and publish to WordPress
  octocoupon social      Post queued items to social media
  octocoupon run-all     Run all three phases in sequence (once)
  octocoupon schedule    Start the background cron scheduler
  octocoupon status      Show DB stats
"""
import click

from octocoupon.db import init_db, get_db
from octocoupon.logger import logger


@click.group()
def cli():
    """Octocoupon — affiliate content marketing automation."""
    init_db()


@cli.command()
def sync():
    """Pull coupons from Rakuten, CJ, and Optimise."""
    from octocoupon.pipeline import sync_affiliates
    sync_affiliates()


@cli.command()
def publish():
    """Generate AI content and publish unpublished coupons to WordPress."""
    from octocoupon.pipeline import publish_content
    publish_content()


@cli.command()
def social():
    """Post queued WordPress posts to social media platforms."""
    from octocoupon.pipeline import post_social
    post_social()


@cli.command("run-all")
def run_all():
    """Run sync → publish → social in sequence (one-shot)."""
    from octocoupon.pipeline import sync_affiliates, publish_content, post_social
    sync_affiliates()
    publish_content()
    post_social()


@cli.command()
def schedule():
    """Start the background scheduler (long-running process)."""
    from octocoupon.scheduler import start
    start()


@cli.command()
def status():
    """Print current database statistics."""
    with get_db() as conn:
        advertisers = conn.execute("SELECT COUNT(*) FROM advertisers").fetchone()[0]
        coupons     = conn.execute("SELECT COUNT(*) FROM coupons").fetchone()[0]
        wp_posts    = conn.execute("SELECT COUNT(*) FROM wp_posts").fetchone()[0]
        pending     = conn.execute("SELECT COUNT(*) FROM social_posts WHERE status='pending'").fetchone()[0]
        posted      = conn.execute("SELECT COUNT(*) FROM social_posts WHERE status='posted'").fetchone()[0]
        failed      = conn.execute("SELECT COUNT(*) FROM social_posts WHERE status='failed'").fetchone()[0]

    click.echo(f"""
Octocoupon Status
─────────────────
  Advertisers:     {advertisers}
  Coupons (DB):    {coupons}
  WP posts:        {wp_posts}
  Social — pending:  {pending}
  Social — posted:   {posted}
  Social — failed:   {failed}
""")
