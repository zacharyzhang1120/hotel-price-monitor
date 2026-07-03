"""Update a hotel's platform mapping for real OTA trials."""

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import select

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from app.database import async_session, init_db  # noqa: E402
from app.models import Hotel, HotelPlatformMapping  # noqa: E402
from app.services.mapping_utils import infer_platform_hotel_id  # noqa: E402


async def main():
    parser = argparse.ArgumentParser(description="Update hotel platform mapping.")
    parser.add_argument("--hotel", required=True, help="Hotel name, supports partial match")
    parser.add_argument("--platform", required=True, choices=["ctrip", "qunar", "tongcheng"])
    parser.add_argument("--url", required=True)
    parser.add_argument("--room", default=None)
    parser.add_argument("--platform-hotel-id", default=None)
    args = parser.parse_args()

    await init_db()
    platform_hotel_id = args.platform_hotel_id or infer_platform_hotel_id(args.platform, args.url)
    if not platform_hotel_id:
        raise SystemExit("Cannot infer platform hotel id. Please pass --platform-hotel-id.")

    async with async_session() as session:
        hotel = await find_hotel(session, args.hotel)
        if not hotel:
            raise SystemExit(f"Hotel not found: {args.hotel}")

        stmt = select(HotelPlatformMapping).where(
            HotelPlatformMapping.hotel_id == hotel.id,
            HotelPlatformMapping.platform == args.platform,
        )
        mapping = (await session.execute(stmt)).scalar_one_or_none()
        if not mapping:
            mapping = HotelPlatformMapping(hotel_id=hotel.id, platform=args.platform)
            session.add(mapping)

        mapping.platform_hotel_id = platform_hotel_id
        mapping.hotel_url = args.url
        if args.room:
            mapping.default_room_name = args.room

        await session.commit()
        print(
            f"Updated: hotel={hotel.name}, platform={args.platform}, "
            f"platform_hotel_id={mapping.platform_hotel_id}, url={mapping.hotel_url}"
        )


async def find_hotel(session, name: str):
    exact = (await session.execute(select(Hotel).where(Hotel.name == name))).scalar_one_or_none()
    if exact:
        return exact
    result = await session.execute(select(Hotel).where(Hotel.name.contains(name)).order_by(Hotel.id))
    return result.scalars().first()


if __name__ == "__main__":
    asyncio.run(main())
