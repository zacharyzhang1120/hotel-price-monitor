"""Tongcheng scraper for P1.4."""

from __future__ import annotations

from datetime import date
from typing import Optional

from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

from app.config import HEADLESS, SCRAPE_TIMEOUT
from app.services.scraper.base import BaseScraper, PricePoint
from app.services.scraper.playwright_utils import (
    extract_lowest_price,
    extract_room_name,
    human_delay,
    with_check_in_params,
)
from app.services.scraper.registry import ScraperContext, register_real_scraper


class TongchengScraper(BaseScraper):
    platform = "tongcheng"

    def __init__(self, default_room_name: Optional[str] = None):
        self.default_room_name = default_room_name

    async def fetch_calendar(self, hotel_url: str, check_in_dates: list[date]) -> list[PricePoint]:
        if not hotel_url:
            raise ValueError("Tongcheng hotel_url is required")

        points: list[PricePoint] = []
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                headless=HEADLESS,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            page = await browser.new_page(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36"
                ),
                viewport={"width": 390, "height": 844},
                is_mobile=True,
                locale="zh-CN",
            )
            try:
                for check_in_date in check_in_dates:
                    points.append(await self._fetch_single_date(page, hotel_url, check_in_date))
            finally:
                await browser.close()
        return points

    async def _fetch_single_date(self, page, hotel_url: str, check_in_date: date) -> PricePoint:
        target_url = with_check_in_params(hotel_url, check_in_date)
        try:
            await page.goto(target_url, wait_until="domcontentloaded", timeout=SCRAPE_TIMEOUT)
            await human_delay(page)
            text = await page.locator("body").inner_text(timeout=SCRAPE_TIMEOUT)
        except PlaywrightTimeoutError as exc:
            raise TimeoutError(f"Tongcheng page timeout for {check_in_date}: {exc}") from exc

        price = extract_lowest_price(text)
        if price is None:
            raise ValueError(f"Tongcheng price not found for {check_in_date}")

        return PricePoint(
            check_in_date=check_in_date,
            cheapest_room=extract_room_name(text, self.default_room_name),
            cheapest_price=price,
        )


def _factory(context: ScraperContext) -> TongchengScraper:
    return TongchengScraper(default_room_name=context.default_room_name)


register_real_scraper("tongcheng", _factory)
