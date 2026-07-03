"""Price query routes."""

from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.price import CalendarResponse, TrendResponse
from app.services.price_service import PriceService

router = APIRouter(prefix="/prices", tags=["prices"])


@router.get("/calendar", response_model=CalendarResponse)
async def get_calendar(
    date_: date = Query(alias="date"),
    days: int = Query(default=8, ge=1, le=31),
    hotel_ids: Optional[str] = None,
    batch_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
):
    parsed_hotel_ids = _parse_hotel_ids(hotel_ids)
    service = PriceService(db)
    data = await service.get_calendar(
        start_date=date_,
        days=days,
        hotel_ids=parsed_hotel_ids,
        batch_id=batch_id,
    )
    return CalendarResponse(data=data)


@router.get("/trend", response_model=TrendResponse)
async def get_trend(
    hotel_id: int,
    check_in_date: date,
    platform: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    service = PriceService(db)
    data = await service.get_trend(
        hotel_id=hotel_id,
        check_in_date=check_in_date,
        platform=platform,
    )
    return TrendResponse(data=data)


def _parse_hotel_ids(raw: Optional[str]) -> Optional[list[int]]:
    if not raw:
        return None
    return [int(item.strip()) for item in raw.split(",") if item.strip()]
