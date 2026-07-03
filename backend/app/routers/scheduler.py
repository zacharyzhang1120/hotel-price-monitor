"""Scheduler status routes."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import SCHEDULER_ENABLED, SCHEDULER_HEALTH_GRACE_MINUTES, SCRAPE_SCHEDULE_HOURS
from app.database import get_db
from app.models import ScrapeRun, ScrapeTaskResult
from app.services.hotel_groups import load_active_group_hotel_ids
from app.services.scheduler import get_scheduler_status

router = APIRouter(prefix="/scheduler", tags=["scheduler"])


@router.get("/status")
async def scheduler_status(db: AsyncSession = Depends(get_db)):
    status = get_scheduler_status()
    target_count = len(await load_active_group_hotel_ids(db))
    status["scheduled_target_hotel_count"] = target_count
    if not status.get("last_scheduler_event"):
        status["last_scheduler_event"] = await _latest_scheduled_scrape_event(db, target_count)
    status["scheduler_health"] = await _scheduler_health(db, status, target_count)
    return status


async def _scheduler_health(db: AsyncSession, status: dict, target_count: int) -> dict:
    if not SCHEDULER_ENABLED:
        return {"status": "disabled", "message": "后台定时未开启"}
    if not status.get("running"):
        return {"status": "down", "message": "后台定时进程未运行"}
    if target_count <= 0:
        return {"status": "warning", "message": "未配置有效门店组"}

    latest_run = await _latest_scheduled_run(db)
    last_success = await _latest_successful_scheduled_run(db)
    if latest_run and _is_run_in_progress(latest_run):
        return {
            "status": "running",
            "message": "后台定时正在抓取",
            **_scheduled_run_health_fields(latest_run, "latest_scheduled"),
        }
    if not last_success:
        return {"status": "warning", "message": "尚无成功的后台定时抓取"}

    if latest_run and latest_run.status != "success" and latest_run.started_at >= last_success.started_at:
        return {
            "status": "warning",
            "message": f"最近一次后台定时未完全成功：{latest_run.status}",
            **_scheduled_run_health_fields(latest_run, "latest_scheduled"),
            **_scheduled_run_health_fields(last_success, "last_success"),
            "last_success_target_hotel_count": await _scheduled_run_target_count(db, last_success.id) or None,
        }

    finished_at = last_success.finished_at or last_success.started_at
    finished_local = _as_local_time(finished_at)
    previous_slot = _previous_schedule_slot()
    healthy_after = previous_slot + timedelta(minutes=SCHEDULER_HEALTH_GRACE_MINUTES)
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    is_stale = now >= healthy_after and finished_local < previous_slot

    run_target_count = await _scheduled_run_target_count(db, last_success.id)
    target_mismatch = bool(run_target_count and run_target_count != target_count)
    if is_stale:
        health_status = "stale"
        message = f"最近成功后台抓取早于上一场计划，建议等待下一次或手动刷新"
    elif target_mismatch:
        health_status = "warning"
        message = f"最近成功后台抓取目标为 {run_target_count} 家，当前目标为 {target_count} 家"
    else:
        health_status = "ok"
        message = "后台定时正常"

    return {
        "status": health_status,
        "message": message,
        "last_success_batch_id": last_success.id,
        "last_success_finished_at": _local_isoformat(finished_at),
        "last_success_target_hotel_count": run_target_count or None,
        "last_success_wall_time_s": round((finished_at - last_success.started_at).total_seconds(), 1),
        "expected_previous_run_at": previous_slot.isoformat(),
        "grace_minutes": SCHEDULER_HEALTH_GRACE_MINUTES,
    }


async def _latest_scheduled_scrape_event(db: AsyncSession, current_target_count: int) -> dict | None:
    stmt = (
        select(ScrapeRun)
        .where(ScrapeRun.trigger_type == "scheduled")
        .order_by(desc(ScrapeRun.started_at), desc(ScrapeRun.id))
        .limit(1)
    )
    result = await db.execute(stmt)
    run = result.scalar_one_or_none()
    if run is None:
        return None

    completed_target_count = await _scheduled_run_target_count(db, run.id)
    target_count = run.total_tasks or completed_target_count
    display_time = run.finished_at or datetime.utcnow()
    wall_time_s = round((display_time - run.started_at).total_seconds(), 1) if display_time else None
    target_note = f"，目标 {target_count} 家" if target_count else ""
    stale_note = (
        "（旧目标）"
        if run.finished_at and target_count and current_target_count and target_count != current_target_count
        else ""
    )
    return {
        "type": "scrape",
        "status": run.status,
        "batch_id": run.id,
        "success": run.success_tasks,
        "failed": run.failed_tasks,
        "scope": "today",
        "target_hotel_count": target_count or None,
        "wall_time_s": wall_time_s,
        "message": f"最近定时抓取 {run.success_tasks}/{run.total_tasks}{target_note}{stale_note}",
        "finished_at": _local_isoformat(display_time),
    }


async def _latest_scheduled_run(db: AsyncSession) -> ScrapeRun | None:
    stmt = (
        select(ScrapeRun)
        .where(ScrapeRun.trigger_type == "scheduled")
        .order_by(desc(ScrapeRun.started_at), desc(ScrapeRun.id))
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _latest_successful_scheduled_run(db: AsyncSession) -> ScrapeRun | None:
    stmt = (
        select(ScrapeRun)
        .where(ScrapeRun.trigger_type == "scheduled")
        .where(ScrapeRun.status == "success")
        .order_by(desc(ScrapeRun.finished_at), desc(ScrapeRun.started_at), desc(ScrapeRun.id))
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _scheduled_run_target_count(db: AsyncSession, batch_id: int) -> int:
    stmt = select(func.count(func.distinct(ScrapeTaskResult.hotel_id))).where(ScrapeTaskResult.batch_id == batch_id)
    result = await db.execute(stmt)
    return int(result.scalar_one() or 0)


def _scheduled_run_health_fields(run: ScrapeRun, prefix: str) -> dict:
    finished_at = run.finished_at or datetime.utcnow()
    return {
        f"{prefix}_batch_id": run.id,
        f"{prefix}_status": run.status,
        f"{prefix}_finished_at": _local_isoformat(finished_at),
        f"{prefix}_wall_time_s": round((finished_at - run.started_at).total_seconds(), 1),
    }


def _is_run_in_progress(run: ScrapeRun) -> bool:
    return run.finished_at is None or run.status == "running"


def _previous_schedule_slot() -> datetime:
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    today_slots = [
        now.replace(hour=hour, minute=0, second=0, microsecond=0)
        for hour in sorted(SCRAPE_SCHEDULE_HOURS)
    ]
    previous_slots = [slot for slot in today_slots if slot <= now]
    if previous_slots:
        return previous_slots[-1]
    yesterday = now - timedelta(days=1)
    return yesterday.replace(hour=max(SCRAPE_SCHEDULE_HOURS), minute=0, second=0, microsecond=0)


def _as_local_time(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=ZoneInfo("UTC"))
    return value.astimezone(ZoneInfo("Asia/Shanghai"))


def _local_isoformat(value: datetime) -> str:
    return _as_local_time(value).isoformat()
