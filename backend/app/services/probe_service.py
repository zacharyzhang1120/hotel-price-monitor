"""Single URL scraper probing."""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any, Literal, Optional

from app.config import SCRAPE_PROBE_TIMEOUT
from app.services.scraper.mock import MockScraper
from app.services.scraper.registry import ScraperContext, create_real_scraper


async def probe_scraper(
    platform: str,
    hotel_url: str,
    check_in_date: date,
    room_name: Optional[str] = None,
    mode: Literal["real", "mock"] = "real",
) -> dict[str, Any]:
    context = ScraperContext(
        platform=platform,
        hotel_name="探测酒店",
        default_room_name=room_name,
        batch_seed=1,
    )
    scraper = (
        MockScraper(platform, context.hotel_name, room_name, context.batch_seed)
        if mode == "mock"
        else create_real_scraper(context)
    )
    try:
        points = await asyncio.wait_for(
            scraper.fetch_calendar(hotel_url, [check_in_date]),
            timeout=max(1, SCRAPE_PROBE_TIMEOUT),
        )
    except asyncio.TimeoutError:
        return {
            "success": False,
            "platform": platform,
            "mode": mode,
            "points": [],
            "error": f"探测超过 {SCRAPE_PROBE_TIMEOUT} 秒，已自动中止",
        }
    except Exception as exc:
        return {
            "success": False,
            "platform": platform,
            "mode": mode,
            "points": [],
            "error": str(exc),
        }

    return {
        "success": True,
        "platform": platform,
        "mode": mode,
        "points": [
            {
                "check_in_date": point.check_in_date,
                "cheapest_room": point.cheapest_room,
                "cheapest_price": point.cheapest_price,
            }
            for point in points
        ],
        "error": None,
    }
