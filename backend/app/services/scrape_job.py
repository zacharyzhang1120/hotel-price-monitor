"""Shared scrape job used by manual trigger and scheduler."""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any, Callable, Optional

from app.database import async_session
from app.services.push_service import ReportPushService
from app.services.report_service import ReportService
from app.services.scrape_manager import ScraperManager

SCRAPE_LOCK = asyncio.Lock()


class ScrapeAlreadyRunningError(RuntimeError):
    """Raised when another scrape batch is already running."""


async def scrape_and_report(
    trigger_type: str = "manual",
    progress_callback: Optional[Callable[[dict[str, Any]], None]] = None,
    hotel_ids: Optional[list[int]] = None,
    scope: str = "all",
) -> dict[str, Any]:
    if SCRAPE_LOCK.locked():
        raise ScrapeAlreadyRunningError("已有抓取任务正在运行")

    async with SCRAPE_LOCK:
        async with async_session() as session:
            stats = await ScraperManager(session, progress_callback=progress_callback).scrape_all(
                trigger_type=trigger_type,
                hotel_ids=hotel_ids or [],
                scope=scope,
            )
            report_service = ReportService(session)
            summary = await report_service.generate_daily_summary(date.today(), batch_id=stats["batch_id"])
            push_text = report_service.format_for_push(summary, "wechat_text")
            push_result = await ReportPushService().push_text(push_text)
            return {
                **stats,
                "report": summary,
                "push": push_result.__dict__,
            }
