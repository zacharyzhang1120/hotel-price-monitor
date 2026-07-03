"""Base scraper types."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from typing import Any, Optional


@dataclass(frozen=True)
class PricePoint:
    check_in_date: date
    cheapest_room: Optional[str]
    cheapest_price: Optional[float]
    evidence: Optional[dict[str, Any]] = None


class BaseScraper(ABC):
    platform: str

    @abstractmethod
    async def fetch_calendar(self, hotel_url: str, check_in_dates: list[date]) -> list[PricePoint]:
        """Fetch cheapest room and price for each check-in date."""
