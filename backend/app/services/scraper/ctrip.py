"""Ctrip scraper for P1.2.

Uses a saved browser session (storage_state) to bypass Ctrip's login wall.
Run scripts/login_ctrip.py first to generate the session file.
"""

from __future__ import annotations

import json
import logging
import time as time_mod
from datetime import date
from typing import Optional

from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

from app.config import (
    CTRIP_STATE_FILE, HEADLESS,
    SCRAPE_BLOCK_RESOURCES, SCRAPE_BLOCK_STYLESHEET,
    SCRAPE_GOTO_WAIT_UNTIL,
    SCRAPE_RENDER_WAIT_INTERVAL_MS, SCRAPE_RENDER_WAIT_MAX_MS,
    SCRAPE_TIMEOUT,
)
from app.services.scraper.base import BaseScraper, PricePoint
from app.services.scraper.playwright_utils import (
    extract_cheapest_room_price_candidate,
    extract_lowest_price,
    extract_room_price_candidates,
    RoomPriceCandidate,
    human_delay,
    with_check_in_params,
)
from app.services.scraper.registry import ScraperContext, register_real_scraper

logger = logging.getLogger(__name__)

def _get_blocked_resource_types() -> list[str]:
    """Build list of resource types to block based on config."""
    blocked = ["image", "font", "media"]
    if SCRAPE_BLOCK_STYLESHEET:
        blocked.append("stylesheet")
    return blocked

ROOM_BLOCK_SELECTORS = (
    "[class*='RoomList']",
    "[class*='roomList']",
    "[class*='room-list']",
    "[class*='RoomCard']",
    "[class*='room-card']",
    "[class*='RoomItem']",
    "[class*='roomItem']",
    "[class*='SaleRoom']",
    "[class*='saleRoom']",
)


def _load_storage_state() -> Optional[dict]:
    """Load saved Ctrip login session if available."""
    if CTRIP_STATE_FILE.exists():
        try:
            return json.loads(CTRIP_STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load Ctrip session state: %s", e)
    return None


async def _block_unused_resources(route):
    """Block configured resource types to reduce page load time."""
    if route.request.resource_type in _get_blocked_resource_types():
        await route.abort()
    else:
        await route.continue_()


class CtripScraper(BaseScraper):
    platform = "ctrip"

    def __init__(self, default_room_name: Optional[str] = None):
        self.default_room_name = default_room_name

    async def fetch_calendar(self, hotel_url: str, check_in_dates: list[date]) -> list[PricePoint]:
        if not hotel_url:
            raise ValueError("Ctrip hotel_url is required")

        storage_state = _load_storage_state()
        if storage_state:
            logger.info("Using saved Ctrip session (%d cookies)",
                        len(storage_state.get("cookies", [])))
        else:
            logger.warning(
                "No Ctrip session found — prices may not load. "
                "Run 'python3 scripts/login_ctrip.py' first."
            )

        points: list[PricePoint] = []
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                headless=HEADLESS,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            context = await browser.new_context(
                storage_state=storage_state,
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36"
                ),
                viewport={"width": 1366, "height": 900},
                locale="zh-CN",
            )
            page = await context.new_page()

            # Block non-essential resources to speed up page load
            if SCRAPE_BLOCK_RESOURCES:
                await page.route("**/*", _block_unused_resources)

            try:
                for check_in_date in check_in_dates:
                    try:
                        point = await self._fetch_single_date(page, hotel_url, check_in_date)
                    except RuntimeError:
                        raise
                    except Exception as exc:
                        logger.warning(
                            "Ctrip date failed for %s; recording an empty price point: %s",
                            check_in_date,
                            exc,
                        )
                        page_signals = await self._capture_page_signals(page)
                        point = PricePoint(
                            check_in_date=check_in_date,
                            cheapest_room=None,
                            cheapest_price=None,
                            evidence={
                                "target_url": with_check_in_params(hotel_url, check_in_date),
                                "final_url": page_signals.get("url"),
                                "source": "fetch_single_date_exception",
                                "selected": None,
                                "candidates": [],
                                "error": str(exc),
                                "page_signals": page_signals,
                            },
                        )
                    points.append(point)
            finally:
                await browser.close()
        return points

    async def _fetch_single_date(self, page, hotel_url: str, check_in_date: date) -> PricePoint:
        t_start = time_mod.monotonic()
        timings: dict[str, float] = {}

        target_url = with_check_in_params(hotel_url, check_in_date)
        t0 = time_mod.monotonic()
        try:
            await page.goto(target_url, wait_until=SCRAPE_GOTO_WAIT_UNTIL, timeout=SCRAPE_TIMEOUT)
        except PlaywrightTimeoutError as exc:
            raise TimeoutError(f"Ctrip page timeout for {check_in_date}: {exc}") from exc
        timings["goto"] = time_mod.monotonic() - t0

        # Smart wait: poll for room content, exit early if detected or prices found
        interval_ms = max(200, min(SCRAPE_RENDER_WAIT_INTERVAL_MS, 2000))
        max_iterations = max(1, SCRAPE_RENDER_WAIT_MAX_MS // interval_ms)
        t0 = time_mod.monotonic()
        for _ in range(max_iterations):
            await page.wait_for_timeout(interval_ms)
            try:
                body_text = await page.locator("body").inner_text(timeout=2000)
                if "房型摘要" in body_text and ("¥" in body_text or "￥" in body_text):
                    break
            except Exception:
                pass
            # Lightweight price check: try first RoomList selector only
            try:
                card = page.locator(ROOM_BLOCK_SELECTORS[0]).first
                if await card.count() > 0:
                    card_text = await card.inner_text(timeout=2000)
                    if extract_lowest_price(card_text) is not None:
                        break
            except Exception:
                pass
        timings["wait_render"] = time_mod.monotonic() - t0

        # Check if redirected to login
        if "passport.ctrip.com" in page.url or "login" in page.url.lower():
            raise RuntimeError(
                "Ctrip session expired or missing. "
                "Re-run: python3 scripts/login_ctrip.py"
            )

        t0 = time_mod.monotonic()
        await self._ensure_room_list_rendered(page)
        timings["ensure_room"] = time_mod.monotonic() - t0

        # Extract price and room name from visible DOM first
        t0 = time_mod.monotonic()
        room, price, candidates = await self._extract_cheapest_room_from_dom(page)
        evidence_source = "dom"
        timings["extract"] = time_mod.monotonic() - t0

        # Only expand if no rooms found yet
        if price is None:
            t0 = time_mod.monotonic()
            try:
                await page.evaluate("""
                    document.querySelectorAll('[class*=\"room\"] div, [class*=\"room\"] span').forEach(el => {
                        if (el.textContent && el.textContent.includes('展示额外')) el.click();
                    });
                """)
                await page.wait_for_timeout(800)
            except Exception:
                pass
            timings["expand"] = time_mod.monotonic() - t0

            room, price, candidates = await self._extract_cheapest_room_from_dom(page)
        if price is None:
            # Fallback to full-text regex
            text = await page.locator("body").inner_text(timeout=SCRAPE_TIMEOUT)
            room_section = self._extract_room_section_text(text)
            if self._is_price_locked(room_section):
                raise RuntimeError(
                    "Ctrip prices are locked behind login/member pricing. "
                    "Re-run: python3 scripts/login_ctrip.py"
                )
            fallback_candidates = extract_room_price_candidates(room_section)
            fallback_candidate = extract_cheapest_room_price_candidate(room_section)
            if fallback_candidate is not None:
                price = fallback_candidate.price
                room = fallback_candidate.room
                candidates = fallback_candidates
                evidence_source = "body_fallback"

        page_signals = await self._capture_page_signals(page) if price is None else None
        evidence = self._build_point_evidence(
            target_url=target_url,
            final_url=page.url,
            source=evidence_source,
            candidates=candidates,
            selected_room=room,
            selected_price=price,
            timings=timings,
            page_signals=page_signals,
            goto_wait_until=SCRAPE_GOTO_WAIT_UNTIL,
        )

        if price is None:
            logger.warning("Ctrip price not found for %s; recording an empty price point", check_in_date)
            logger.info(
                "Ctrip timing [%s %s]: goto=%.1fs wait=%.1fs ensure=%.1fs expand=%.1fs extract=%.1fs total=%.1fs [NO PRICE]",
                check_in_date, check_in_date,
                timings.get("goto", 0), timings.get("wait_render", 0),
                timings.get("ensure_room", 0), timings.get("expand", 0),
                timings.get("extract", 0),
                time_mod.monotonic() - t_start,
            )
            return PricePoint(
                check_in_date=check_in_date,
                cheapest_room=None,
                cheapest_price=None,
                evidence=evidence,
            )

        logger.info(
            "Ctrip timing [%s]: goto=%.1fs wait=%.1fs ensure=%.1fs expand=%.1fs extract=%.1fs total=%.1fs price=¥%s",
            check_in_date,
            timings.get("goto", 0), timings.get("wait_render", 0),
            timings.get("ensure_room", 0), timings.get("expand", 0),
            timings.get("extract", 0),
            time_mod.monotonic() - t_start,
            price,
        )
        return PricePoint(
            check_in_date=check_in_date,
            cheapest_room=room,
            cheapest_price=price,
            evidence=evidence,
        )

    async def _ensure_room_list_rendered(self, page) -> None:
        """Nudge Ctrip detail pages until the room list text is present."""
        # Quick check: already rendered?
        try:
            text = await page.locator("body").inner_text(timeout=3000)
            if "房型摘要" in text and ("¥" in text or "￥" in text):
                return
        except Exception:
            pass

        # Not yet — try clicking/scrolling to trigger rendering
        for attempt in range(3):
            try:
                if attempt == 0:
                    await page.get_by_text("选择房间", exact=True).first.click(timeout=2000)
                else:
                    await page.mouse.wheel(0, 1400)
            except Exception:
                pass

            await page.wait_for_timeout(1000)

            try:
                text = await page.locator("body").inner_text(timeout=3000)
                if "房型摘要" in text and ("¥" in text or "￥" in text):
                    return
            except Exception:
                pass

    async def _extract_cheapest_room_from_dom(
        self,
        page,
    ) -> tuple[Optional[str], Optional[float], list[RoomPriceCandidate]]:
        """Extract the cheapest room name and price from matching DOM text blocks."""
        text_blocks = await self._collect_room_text_blocks(page)
        candidates: list[RoomPriceCandidate] = []
        seen: set[tuple[str, float]] = set()

        for block_text in text_blocks:
            for candidate in extract_room_price_candidates(block_text):
                key = (candidate.room, candidate.price)
                if key in seen:
                    continue
                seen.add(key)
                candidates.append(candidate)

        if not candidates:
            return None, None, []

        selected = min(candidates, key=lambda candidate: candidate.price)
        preview = "; ".join(f"{candidate.room}=¥{candidate.price:g}" for candidate in candidates[:8])
        logger.info("Ctrip room candidates: %s", preview)
        logger.info("Ctrip cheapest room candidate: room=%s price=%s", selected.room, selected.price)
        return selected.room, selected.price, candidates

    @staticmethod
    def _build_point_evidence(
        target_url: str,
        final_url: str,
        source: str,
        candidates: list[RoomPriceCandidate],
        selected_room: Optional[str],
        selected_price: Optional[float],
        timings: dict[str, float],
        page_signals: Optional[dict] = None,
        goto_wait_until: str = "domcontentloaded",
    ) -> dict:
        evidence = {
            "target_url": target_url,
            "final_url": final_url,
            "source": source,
            "goto_wait_until": goto_wait_until,
            "selected": (
                {"room": selected_room, "price": selected_price}
                if selected_room and selected_price is not None
                else None
            ),
            "candidates": [
                {"room": candidate.room, "price": candidate.price}
                for candidate in candidates[:12]
            ],
            "timings": {key: round(value, 3) for key, value in timings.items()},
        }
        if page_signals is not None:
            evidence["page_signals"] = page_signals
        return evidence

    @staticmethod
    async def _capture_page_signals(page) -> dict:
        signals = {
            "url": None,
            "title": None,
            "text_length": 0,
            "has_price": False,
            "has_room_summary": False,
            "has_unlock_offer": False,
            "has_login": False,
            "has_verify": False,
            "body_excerpt": "",
        }
        try:
            signals["url"] = page.url
        except Exception:
            pass
        try:
            signals["title"] = await page.title()
        except Exception:
            pass
        try:
            text = await page.locator("body").inner_text(timeout=2500)
        except Exception as exc:
            signals["body_error"] = str(exc)[:300]
            return signals

        normalized = "\n".join(line.strip() for line in text.splitlines() if line.strip())
        signals.update(
            {
                "text_length": len(normalized),
                "has_price": "¥" in normalized or "￥" in normalized,
                "has_room_summary": "房型摘要" in normalized,
                "has_unlock_offer": "解锁优惠" in normalized,
                "has_login": "登录" in normalized or "passport.ctrip.com" in str(signals.get("url") or ""),
                "has_verify": any(word in normalized for word in ("验证", "安全检测", "滑块", "访问受限")),
                "body_excerpt": normalized[:1200],
            }
        )
        return signals

    async def _collect_room_text_blocks(self, page) -> list[str]:
        """Collect visible room-related text blocks, de-duplicated from specific to broad."""
        texts: list[str] = []
        seen: set[str] = set()

        async def add_text(text: str) -> None:
            normalized = "\n".join(line.strip() for line in text.splitlines() if line.strip())
            if not normalized or normalized in seen:
                return
            seen.add(normalized)
            texts.append(normalized)

        found_enough = False
        for selector in ROOM_BLOCK_SELECTORS:
            locator = page.locator(selector)
            try:
                count = min(await locator.count(), 60)
            except Exception:
                continue

            for idx in range(count):
                try:
                    block_text = await locator.nth(idx).inner_text(timeout=2000)
                except Exception:
                    continue
                if ("¥" in block_text or "￥" in block_text) and ("房" in block_text or "床" in block_text):
                    await add_text(block_text)
                    found_enough = True

        # Only run expensive JS scan if selectors didn't find enough
        if not found_enough:
            try:
                js_texts = await page.evaluate(
                    """
                    () => Array.from(document.querySelectorAll('[class*=\"room\"], [class*=\"Room\"], [class*=\"hotel\"]'))
                        .filter((el) => {
                            const text = el.innerText || '';
                            return /[¥￥]/.test(text) && /[房床套]/.test(text);
                        })
                        .slice(0, 60)
                        .map((el) => el.innerText)
                    """
                )
                for block_text in js_texts:
                    await add_text(block_text)
            except Exception:
                pass

        # Body text fallback only if still nothing found
        if len(texts) == 0:
            try:
                body_text = await page.locator("body").inner_text(timeout=SCRAPE_TIMEOUT)
                room_section = self._extract_room_section_text(body_text)
                if room_section:
                    await add_text(room_section)
            except Exception:
                pass

        return texts

    @staticmethod
    def _extract_room_section_text(text: str) -> str:
        """Keep only the room list area to avoid nearby hotels and policy prices."""
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return ""

        start_idx: Optional[int] = None
        for idx, line in enumerate(lines):
            if line == "房间" and any("房型摘要" in item for item in lines[idx: idx + 120]):
                start_idx = idx
                break

        if start_idx is None:
            for idx, line in enumerate(lines):
                if line == "房型摘要":
                    start_idx = max(0, idx - 60)
                    break

        if start_idx is None:
            return ""

        end_idx = len(lines)
        end_markers = {"住客印象", "酒店简介", "附近", "价格说明", "仍未找到合适的酒店"}
        for idx in range(start_idx + 10, len(lines)):
            if lines[idx] in end_markers:
                end_idx = idx
                break

        return "\n".join(lines[start_idx:end_idx])

    @staticmethod
    def _is_price_locked(room_section: str) -> bool:
        """Detect Ctrip room lists where prices are hidden behind a login/member prompt."""
        if not room_section:
            return False
        return (
            "解锁优惠" in room_section
            and "房型摘要" in room_section
            and extract_lowest_price(room_section) is None
        )

    async def _extract_price_from_dom(self, page) -> Optional[float]:
        """Extract cheapest room price from Ctrip's RoomList DOM elements."""
        _, price, _ = await self._extract_cheapest_room_from_dom(page)
        return price

    async def _extract_room_name_from_dom(self, page) -> Optional[str]:
        """Extract room name from the cheapest RoomList card."""
        room, _, _ = await self._extract_cheapest_room_from_dom(page)
        return room or self.default_room_name


def _factory(context: ScraperContext) -> CtripScraper:
    return CtripScraper(default_room_name=context.default_room_name)


register_real_scraper("ctrip", _factory)
