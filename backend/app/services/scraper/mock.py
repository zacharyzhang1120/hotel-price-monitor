"""Mock scraper for P0 MVP development."""

from __future__ import annotations

import random
from datetime import date
from typing import Optional

from app.services.scraper.base import BaseScraper, PricePoint


class MockScraper(BaseScraper):
    """Generate stable-but-changing prices without touching OTA websites."""

    def __init__(
        self,
        platform: str,
        hotel_name: str,
        default_room_name: Optional[str],
        batch_seed: int,
    ):
        self.platform = platform
        self.hotel_name = hotel_name
        self.default_room_name = default_room_name or "标准大床房"
        self.batch_seed = batch_seed

    async def fetch_calendar(self, hotel_url: str, check_in_dates: list[date]) -> list[PricePoint]:
        points: list[PricePoint] = []
        for check_in_date in check_in_dates:
            points.append(
                PricePoint(
                    check_in_date=check_in_date,
                    cheapest_room=self.default_room_name,
                    cheapest_price=float(self._price_for(check_in_date)),
                )
            )
        return points

    def _price_for(self, check_in_date: date) -> int:
        hotel_offset = _stable_int(self.hotel_name) % 160 - 80
        platform_offset = {
            "ctrip": 20,
        }.get(self.platform, 15)
        weekday_offset = 40 if check_in_date.weekday() in (4, 5) else 0
        date_offset = (check_in_date.toordinal() % 5) * 8
        rng = random.Random(f"{self.batch_seed}:{self.hotel_name}:{self.platform}:{check_in_date.isoformat()}")
        batch_noise = rng.randint(-15, 15)
        return max(300, 680 + hotel_offset + platform_offset + weekday_offset + date_offset + batch_noise)


def _stable_int(value: str) -> int:
    total = 0
    for char in value:
        total = (total * 131 + ord(char)) % 10_000
    return total
