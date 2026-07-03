"""Seed real hotels and platform mappings."""

import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy import select

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from app.database import async_session, init_db  # noqa: E402
from app.models import Hotel, HotelCompetitor, HotelPlatformMapping  # noqa: E402

SEED_FILE = Path(__file__).with_name("seed_data.json")


async def main():
    await init_db()
    data = json.loads(SEED_FILE.read_text(encoding="utf-8"))

    inserted_hotels = 0
    inserted_mappings = 0
    async with async_session() as session:
        hotel_items = [(data["my_hotel"], True)]
        hotel_items.extend((item, False) for item in data.get("competitors", []))

        my_hotel = None
        competitor_hotels = []
        for hotel_data, is_mine in hotel_items:
            hotel, created = await get_or_create_hotel(session, hotel_data, is_mine)
            if created:
                inserted_hotels += 1
            if is_mine:
                my_hotel = hotel
            else:
                competitor_hotels.append(hotel)

            for platform, platform_data in hotel_data["platforms"].items():
                created_mapping = await get_or_create_mapping(session, hotel.id, platform, platform_data)
                if created_mapping:
                    inserted_mappings += 1

        if my_hotel:
            await sync_competitors(session, my_hotel.id, [hotel.id for hotel in competitor_hotels[:5]])
        await session.commit()

    print(f"Seed complete: {inserted_hotels} hotels inserted, {inserted_mappings} mappings inserted.")


async def get_or_create_hotel(session, hotel_data: dict, is_mine: bool) -> tuple[Hotel, bool]:
    stmt = select(Hotel).where(Hotel.name == hotel_data["name"])
    result = await session.execute(stmt)
    hotel = result.scalar_one_or_none()
    if hotel:
        hotel.is_mine = is_mine
        hotel.distance_km = hotel_data.get("distance_km")
        await session.flush()
        return hotel, False

    hotel = Hotel(
        name=hotel_data["name"],
        is_mine=is_mine,
        distance_km=hotel_data.get("distance_km"),
    )
    session.add(hotel)
    await session.flush()
    return hotel, True


async def get_or_create_mapping(session, hotel_id: int, platform: str, platform_data: dict) -> bool:
    stmt = select(HotelPlatformMapping).where(
        HotelPlatformMapping.platform == platform,
        HotelPlatformMapping.platform_hotel_id == platform_data["hotel_id"],
    )
    result = await session.execute(stmt)
    mapping = result.scalar_one_or_none()
    if mapping:
        mapping.hotel_id = hotel_id
        mapping.hotel_url = platform_data.get("url")
        mapping.default_room_name = platform_data.get("room_name")
        await session.flush()
        return False

    session.add(
        HotelPlatformMapping(
            hotel_id=hotel_id,
            platform=platform,
            platform_hotel_id=platform_data["hotel_id"],
            hotel_url=platform_data.get("url"),
            default_room_name=platform_data.get("room_name"),
        )
    )
    await session.flush()
    return True


async def sync_competitors(session, mine_hotel_id: int, competitor_ids: list[int]):
    for competitor_id in competitor_ids:
        stmt = select(HotelCompetitor).where(
            HotelCompetitor.mine_hotel_id == mine_hotel_id,
            HotelCompetitor.competitor_hotel_id == competitor_id,
        )
        exists = (await session.execute(stmt)).scalar_one_or_none()
        if not exists:
            session.add(HotelCompetitor(mine_hotel_id=mine_hotel_id, competitor_hotel_id=competitor_id))
    await session.flush()


if __name__ == "__main__":
    asyncio.run(main())
