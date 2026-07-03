"""Report routes."""

from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.report_service import ReportService

router = APIRouter(prefix="/reports", tags=["reports"])


@router.post("/generate")
async def generate_report(
    format: str = Query(default="json", pattern="^(json|wechat_text|wechat_markdown)$"),
    date_: date = Query(alias="date"),
    batch_id: Optional[int] = None,
    mine_hotel_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
):
    service = ReportService(db)
    summary = await service.generate_daily_summary(date_, batch_id=batch_id, mine_hotel_id=mine_hotel_id)
    if format == "json":
        return summary
    text = service.format_for_push(summary, format)
    return Response(content=text, media_type="text/plain; charset=utf-8")


@router.get("/latest")
async def latest_report(
    date_: Optional[date] = Query(default=None, alias="date"),
    format: str = Query(default="json", pattern="^(json|wechat_text|wechat_markdown)$"),
    mine_hotel_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
):
    service = ReportService(db)
    summary = await service.generate_daily_summary(date_ or date.today(), mine_hotel_id=mine_hotel_id)
    if format == "json":
        return summary
    text = service.format_for_push(summary, format)
    return Response(content=text, media_type="text/plain; charset=utf-8")
