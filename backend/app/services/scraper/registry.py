"""Scraper registry and mode switching."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from app.config import REAL_PLATFORMS, SCRAPER_MODE
from app.services.scraper.base import BaseScraper
from app.services.scraper.mock import MockScraper


class ScraperUnavailableError(RuntimeError):
    """Raised when SCRAPER_MODE requires a real scraper that is not registered."""


@dataclass(frozen=True)
class ScraperContext:
    platform: str
    hotel_name: str
    default_room_name: Optional[str]
    batch_seed: int


RealScraperFactory = Callable[[ScraperContext], BaseScraper]
REAL_SCRAPER_FACTORIES: dict[str, RealScraperFactory] = {}
_REAL_SCRAPERS_IMPORTED = False


def register_real_scraper(platform: str, factory: RealScraperFactory) -> None:
    REAL_SCRAPER_FACTORIES[platform] = factory


def create_scraper(context: ScraperContext) -> BaseScraper:
    ensure_real_scrapers_imported()

    if SCRAPER_MODE == "mock":
        return _create_mock_scraper(context)

    if SCRAPER_MODE == "mixed":
        if context.platform in REAL_PLATFORMS:
            return _create_real_scraper(context)
        return _create_mock_scraper(context)

    if SCRAPER_MODE == "real":
        return _create_real_scraper(context)

    raise ValueError(f"Unsupported SCRAPER_MODE: {SCRAPER_MODE}")


def _create_mock_scraper(context: ScraperContext) -> MockScraper:
    return MockScraper(
        platform=context.platform,
        hotel_name=context.hotel_name,
        default_room_name=context.default_room_name,
        batch_seed=context.batch_seed,
    )


def _create_real_scraper(context: ScraperContext) -> BaseScraper:
    factory = REAL_SCRAPER_FACTORIES.get(context.platform)
    if not factory:
        raise ScraperUnavailableError(
            f"Real scraper for platform '{context.platform}' is not implemented. "
            "Use SCRAPER_MODE=mock, or SCRAPER_MODE=mixed without this platform in REAL_PLATFORMS."
        )
    return factory(context)


def create_real_scraper(context: ScraperContext) -> BaseScraper:
    ensure_real_scrapers_imported()
    return _create_real_scraper(context)


def ensure_real_scrapers_imported() -> None:
    global _REAL_SCRAPERS_IMPORTED
    if _REAL_SCRAPERS_IMPORTED:
        return
    # Import modules with implemented real scrapers so they can self-register.
    import app.services.scraper.ctrip  # noqa: F401
    import app.services.scraper.qunar  # noqa: F401
    import app.services.scraper.tongcheng  # noqa: F401

    _REAL_SCRAPERS_IMPORTED = True
