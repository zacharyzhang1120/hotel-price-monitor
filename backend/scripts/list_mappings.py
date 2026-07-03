"""List hotel platform mappings."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import selectinload

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from app.database import async_session, init_db  # noqa: E402
from app.models import Hotel  # noqa: E402


async def main() -> None:
    await init_db()
    stmt = select(Hotel).options(selectinload(Hotel.platform_mappings)).order_by(Hotel.is_mine.desc(), Hotel.id)
    async with async_session() as session:
        hotels = (await session.execute(stmt)).scalars().all()

    for hotel in hotels:
        role = "我方" if hotel.is_mine else "竞对"
        distance = "" if hotel.distance_km is None else f" {hotel.distance_km:g}km"
        print(f"[{role}] #{hotel.id} {hotel.name}{distance}")
        for mapping in sorted(hotel.platform_mappings, key=lambda item: item.platform):
            room = mapping.default_room_name or "-"
            url = mapping.hotel_url or "-"
            print(f"  - {mapping.platform}: room={room} url={url}")


if __name__ == "__main__":
    asyncio.run(main())
