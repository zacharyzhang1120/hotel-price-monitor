"""Startup maintenance tasks."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_, select

from app.database import async_session
from app.models import ScrapeRun


async def mark_stale_running_scrape_runs() -> int:
    """Close scrape runs left unfinished by a process restart."""
    async with async_session() as session:
        result = await session.execute(
            select(ScrapeRun).where(or_(ScrapeRun.status == "running", ScrapeRun.finished_at.is_(None)))
        )
        runs = list(result.scalars().all())
        for run in runs:
            if run.status == "running":
                run.status = "failed"
            run.finished_at = datetime.utcnow()
            run.error_summary = (run.error_summary or "服务重启，未完成的抓取批次已自动结束")
        await session.commit()
        return len(runs)
