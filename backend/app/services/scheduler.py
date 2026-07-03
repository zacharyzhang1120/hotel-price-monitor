"""APScheduler lifecycle."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import SCHEDULED_SCRAPE_SCOPE, SCHEDULER_ENABLED, SCRAPE_SCHEDULE_HOURS
from app.database import async_session
from app.services.backup_service import backup_database
from app.services.hotel_groups import load_active_group_hotel_ids
from app.services.scrape_job import ScrapeAlreadyRunningError, scrape_and_report

logger = logging.getLogger(__name__)

_scheduler: Optional[AsyncIOScheduler] = None
_last_scheduler_event: Optional[dict] = None


async def scheduled_scrape_job() -> None:
    global _last_scheduler_event
    try:
        hotel_ids = await _load_scheduled_hotel_ids()
        if not hotel_ids:
            _last_scheduler_event = {
                "type": "scrape",
                "status": "skipped",
                "batch_id": None,
                "success": 0,
                "failed": 0,
                "message": "未配置有效门店组，定时抓取已跳过",
                "finished_at": _local_now_isoformat(),
            }
            logger.warning("Scheduled scrape skipped because no active hotel group is configured")
            return

        stats = await scrape_and_report(
            trigger_type="scheduled",
            scope=SCHEDULED_SCRAPE_SCOPE,
            hotel_ids=hotel_ids,
        )
        _last_scheduler_event = {
            "type": "scrape",
            "status": stats["status"],
            "batch_id": stats["batch_id"],
            "success": stats["success"],
            "failed": stats["failed"],
            "scope": SCHEDULED_SCRAPE_SCOPE,
            "target_hotel_count": len(hotel_ids),
            "wall_time_s": stats.get("wall_time_s"),
            "message": f"定时抓取完成 {stats['success']}/{stats['total']}，目标 {len(hotel_ids)} 家",
            "finished_at": _local_now_isoformat(),
        }
        logger.info(
            "Scheduled scrape finished: scope=%s hotels=%s batch=%s success=%s failed=%s",
            SCHEDULED_SCRAPE_SCOPE,
            len(hotel_ids),
            stats["batch_id"],
            stats["success"],
            stats["failed"],
        )
    except ScrapeAlreadyRunningError:
        _last_scheduler_event = {
            "type": "scrape",
            "status": "skipped",
            "batch_id": None,
            "success": 0,
            "failed": 0,
            "message": "已有抓取任务正在运行，定时抓取已跳过",
            "finished_at": _local_now_isoformat(),
        }
        logger.warning("Scheduled scrape skipped because another scrape is running")
    except Exception as exc:
        _last_scheduler_event = {
            "type": "scrape",
            "status": "failed",
            "batch_id": None,
            "success": 0,
            "failed": 1,
            "message": f"定时抓取失败：{str(exc)[:160]}",
            "finished_at": _local_now_isoformat(),
        }
        logger.exception("Scheduled scrape failed")


async def _load_scheduled_hotel_ids() -> list[int]:
    async with async_session() as session:
        return await load_active_group_hotel_ids(session)


def scheduled_backup_job() -> None:
    global _last_scheduler_event
    try:
        target = backup_database()
        if target:
            _last_scheduler_event = {
                "type": "backup",
                "status": "success",
                "batch_id": None,
                "success": 1,
                "failed": 0,
                "message": f"数据库备份完成：{target.name}",
                "finished_at": _local_now_isoformat(),
            }
            logger.info("Database backup created: %s", target)
    except Exception as exc:
        _last_scheduler_event = {
            "type": "backup",
            "status": "failed",
            "batch_id": None,
            "success": 0,
            "failed": 1,
            "message": f"数据库备份失败：{str(exc)[:160]}",
            "finished_at": _local_now_isoformat(),
        }
        logger.exception("Database backup failed")


def _local_now_isoformat() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()


def start_scheduler() -> None:
    global _scheduler
    if not SCHEDULER_ENABLED:
        logger.info("Scheduler disabled")
        return
    if _scheduler and _scheduler.running:
        return

    scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
    for hour in SCRAPE_SCHEDULE_HOURS:
        scheduler.add_job(
            scheduled_scrape_job,
            "cron",
            hour=hour,
            minute=0,
            id=f"scrape_{hour}",
            replace_existing=True,
            max_instances=1,
        )
    scheduler.add_job(
        scheduled_backup_job,
        "cron",
        hour=3,
        minute=0,
        id="daily_sqlite_backup",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.start()
    _scheduler = scheduler
    logger.info("Scheduler started")


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
    _scheduler = None


def get_scheduler_status() -> dict:
    jobs = []
    if _scheduler:
        for job in _scheduler.get_jobs():
            next_run_time = getattr(job, "next_run_time", None)
            jobs.append(
                {
                    "id": job.id,
                    "name": job.name,
                    "next_run_time": next_run_time.isoformat() if next_run_time else None,
                }
            )
    return {
        "enabled": SCHEDULER_ENABLED,
        "running": bool(_scheduler and _scheduler.running),
        "schedule_hours": SCRAPE_SCHEDULE_HOURS,
        "scheduled_scrape_scope": SCHEDULED_SCRAPE_SCOPE,
        "last_scheduler_event": _last_scheduler_event,
        "jobs": jobs,
    }
