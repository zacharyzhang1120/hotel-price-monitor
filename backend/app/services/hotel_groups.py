"""Helpers for owned-hotel competitor groups."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Hotel


async def load_active_group_hotel_ids(session: AsyncSession) -> list[int]:
    """Return hotels that belong to configured owned-hotel groups."""
    stmt = (
        select(Hotel)
        .options(selectinload(Hotel.competitor_links))
        .where(Hotel.is_mine.is_(True))
        .order_by(Hotel.id)
    )
    result = await session.execute(stmt)
    ids: list[int] = []
    seen: set[int] = set()
    for mine_hotel in result.scalars().all():
        for hotel_id in [mine_hotel.id, *mine_hotel.competitor_ids]:
            if hotel_id in seen:
                continue
            seen.add(hotel_id)
            ids.append(hotel_id)
    return ids
