"""Price query service."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Hotel, HotelPlatformMapping, PriceRecord, ScrapeRun, ScrapeTaskResult
from app.schemas.price import CalendarPriceItem, TrendItem
from app.config import PRICE_FALLBACK_MAX_AGE_HOURS

SUCCESS_STATUSES = ("success", "partial_success")


class PriceService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_latest_batch_id(self, hotel_ids: Optional[list[int]] = None) -> Optional[int]:
        stmt = (
            select(ScrapeRun.id)
            .join(PriceRecord, PriceRecord.batch_id == ScrapeRun.id)
            .where(ScrapeRun.status.in_(SUCCESS_STATUSES))
            .where(PriceRecord.cheapest_price.is_not(None))
        )
        if hotel_ids:
            stmt = stmt.where(PriceRecord.hotel_id.in_(hotel_ids))
        stmt = (
            stmt.group_by(ScrapeRun.id)
            .having(func.count(PriceRecord.id) > 0)
            .order_by(desc(func.coalesce(ScrapeRun.finished_at, ScrapeRun.started_at)), desc(ScrapeRun.id))
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_calendar(
        self,
        start_date: date,
        days: int = 8,
        hotel_ids: Optional[list[int]] = None,
        batch_id: Optional[int] = None,
    ) -> list[CalendarPriceItem]:
        check_in_dates = [start_date + timedelta(days=offset) for offset in range(days)]
        current_batch_id = batch_id or await self.get_latest_batch_id(hotel_ids)

        hotels_stmt = (
            select(Hotel)
            .options(selectinload(Hotel.platform_mappings))
            .order_by(Hotel.is_mine.desc(), Hotel.id)
        )
        if hotel_ids:
            hotels_stmt = hotels_stmt.where(Hotel.id.in_(hotel_ids))
        hotels = list((await self.session.execute(hotels_stmt)).scalars().all())

        records_by_key: dict[tuple[int, str, date], PriceRecord] = {}
        if batch_id:
            records_stmt = select(PriceRecord).where(
                PriceRecord.batch_id == batch_id,
                PriceRecord.check_in_date.in_(check_in_dates),
            )
            if hotel_ids:
                records_stmt = records_stmt.where(PriceRecord.hotel_id.in_(hotel_ids))
            records = (await self.session.execute(records_stmt)).scalars().all()
            records_by_key = {
                (record.hotel_id, record.platform, record.check_in_date): record
                for record in records
            }
        else:
            records_by_key = await self._get_latest_records_by_key(check_in_dates, hotel_ids)

        task_results_by_key = await self._get_task_results_by_key(current_batch_id, hotel_ids)

        items: list[CalendarPriceItem] = []
        for hotel in hotels:
            for mapping in sorted(hotel.platform_mappings, key=lambda item: item.platform):
                for check_in_date in check_in_dates:
                    record = records_by_key.get((hotel.id, mapping.platform, check_in_date))
                    task_result = task_results_by_key.get((hotel.id, mapping.platform))
                    record_batch_id = record.batch_id if record else None
                    items.append(
                        CalendarPriceItem(
                            hotel_id=hotel.id,
                            hotel_name=hotel.name,
                            is_mine=hotel.is_mine,
                            platform=mapping.platform,
                            check_in_date=check_in_date,
                            cheapest_room=record.cheapest_room if record else None,
                            cheapest_price=record.cheapest_price if record else None,
                            scraped_at=record.scraped_at if record else None,
                            batch_id=record_batch_id,
                            is_current_batch=bool(record and current_batch_id and record_batch_id == current_batch_id),
                            is_fallback=bool(not batch_id and record and current_batch_id and record_batch_id != current_batch_id),
                            task_status=task_result.status if task_result else None,
                            task_error_message=task_result.error_message if task_result else None,
                        )
                    )
        return items

    async def _get_task_results_by_key(
        self,
        batch_id: Optional[int],
        hotel_ids: Optional[list[int]] = None,
    ) -> dict[tuple[int, str], ScrapeTaskResult]:
        if not batch_id:
            return {}
        stmt = (
            select(ScrapeTaskResult)
            .where(ScrapeTaskResult.batch_id == batch_id)
            .order_by(desc(ScrapeTaskResult.finished_at), desc(ScrapeTaskResult.id))
        )
        if hotel_ids:
            stmt = stmt.where(ScrapeTaskResult.hotel_id.in_(hotel_ids))
        task_results = (await self.session.execute(stmt)).scalars().all()
        results_by_key: dict[tuple[int, str], ScrapeTaskResult] = {}
        for task_result in task_results:
            key = (task_result.hotel_id, task_result.platform)
            if key not in results_by_key:
                results_by_key[key] = task_result
        return results_by_key

    async def _get_latest_records_by_key(
        self,
        check_in_dates: list[date],
        hotel_ids: Optional[list[int]] = None,
    ) -> dict[tuple[int, str, date], PriceRecord]:
        min_scraped_at = datetime.utcnow() - timedelta(hours=PRICE_FALLBACK_MAX_AGE_HOURS)
        stmt = (
            select(PriceRecord)
            .join(ScrapeRun, ScrapeRun.id == PriceRecord.batch_id)
            .where(ScrapeRun.status.in_(SUCCESS_STATUSES))
            .where(PriceRecord.check_in_date.in_(check_in_dates))
            .where(PriceRecord.cheapest_price.is_not(None))
            .where(PriceRecord.scraped_at >= min_scraped_at)
            .order_by(desc(PriceRecord.scraped_at), desc(PriceRecord.id))
        )
        if hotel_ids:
            stmt = stmt.where(PriceRecord.hotel_id.in_(hotel_ids))

        records = (await self.session.execute(stmt)).scalars().all()
        records_by_key: dict[tuple[int, str, date], PriceRecord] = {}
        for record in records:
            key = (record.hotel_id, record.platform, record.check_in_date)
            if key not in records_by_key:
                records_by_key[key] = record
        return records_by_key

    async def get_trend(
        self,
        hotel_id: int,
        check_in_date: date,
        platform: Optional[str] = None,
    ) -> list[TrendItem]:
        stmt = select(PriceRecord).where(
            PriceRecord.hotel_id == hotel_id,
            PriceRecord.check_in_date == check_in_date,
        )
        if platform:
            stmt = stmt.where(PriceRecord.platform == platform)
        stmt = stmt.order_by(PriceRecord.platform, PriceRecord.scraped_at)
        records = (await self.session.execute(stmt)).scalars().all()
        return [
            TrendItem(
                scraped_at=record.scraped_at,
                platform=record.platform,
                cheapest_price=record.cheapest_price,
            )
            for record in records
        ]
