"""
APScheduler-based background scheduler.
Runs the three pipeline phases on configurable cron expressions.
"""
from __future__ import annotations

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from octocoupon.config import settings
from octocoupon.logger import logger
from octocoupon.pipeline import sync_affiliates, publish_content, post_social


def _safe(fn):
    """Wrap a pipeline function so scheduler keeps running even if it raises."""
    def wrapper():
        try:
            fn()
        except Exception as exc:
            logger.exception(f"Scheduled job {fn.__name__} failed: {exc}")
    wrapper.__name__ = fn.__name__
    return wrapper


def start() -> None:
    scheduler = BlockingScheduler(timezone="UTC")

    scheduler.add_job(
        _safe(sync_affiliates),
        CronTrigger.from_crontab(settings.cron_affiliate_sync),
        id="affiliate_sync",
        name="Affiliate Sync",
    )
    scheduler.add_job(
        _safe(publish_content),
        CronTrigger.from_crontab(settings.cron_content_publish),
        id="content_publish",
        name="Content Publish",
    )
    scheduler.add_job(
        _safe(post_social),
        CronTrigger.from_crontab(settings.cron_social_post),
        id="social_post",
        name="Social Post",
    )

    logger.info("Scheduler started (UTC):")
    logger.info(f"  Affiliate sync:  {settings.cron_affiliate_sync}")
    logger.info(f"  Content publish: {settings.cron_content_publish}")
    logger.info(f"  Social post:     {settings.cron_social_post}")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")
