"""Diagnose Ctrip v2 - wait for full render + try DOM selectors."""
import asyncio
import sys
from datetime import date
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from playwright.async_api import async_playwright

HOTEL_URL = "https://hotels.ctrip.com/hotels/detail/?cityEnName=Haikou&cityId=42&hotelId=436575"
OUT_DIR = ROOT_DIR / "data" / "diag"
OUT_DIR.mkdir(parents=True, exist_ok=True)


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 900},
            locale="zh-CN",
        )
        page = await context.new_page()

        print(f"Navigating to Ctrip (networkidle, 60s timeout)...")
        try:
            await page.goto(HOTEL_URL, wait_until="networkidle", timeout=60000)
        except Exception as e:
            print(f"  Timeout/Error: {e}")
            print(f"  Continuing with partial page...")

        print(f"  URL: {page.url}")
        print(f"  Title: {await page.title()}")

        # Extra wait for any remaining animations
        await page.wait_for_timeout(3000)

        # Screenshot
        await page.screenshot(path=str(OUT_DIR / "ctrip_page2.png"), full_page=False)
        print(f"  Screenshot saved to data/diag/ctrip_page2.png")

        # Try various price selectors
        selectors_to_try = [
            ".price", ".real-price", ".base-price",
            "[class*='price']", "[class*='Price']",
            ".room-price", ".lowest-price",
            "span:has-text('¥')", "span:has-text('￥')",
            "[class*='room'] [class*='price']",
            ".hotel-room-list .price",
            ".roomlist .price",
            "#hotelRoomList [class*='price']",
            ".m-hotel-room",
            ".room-item",
            ".J_roomList",
        ]

        print("\n  --- DOM SELECTOR TEST ---")
        for sel in selectors_to_try:
            try:
                count = await page.locator(sel).count()
                if count > 0:
                    text = await page.locator(sel).first.inner_text()
                    print(f"  ✅ '{sel}': {count} found, text='{text[:80]}'")
                else:
                    print(f"  ❌ '{sel}': 0 found")
            except Exception as e:
                print(f"  ⚠️ '{sel}': error - {str(e)[:60]}")

        # Check body text now (after full render)
        text = await page.locator("body").inner_text(timeout=10000)
        yen_count = text.count("¥") + text.count("￥")
        print(f"\n  Body text length: {len(text)} chars")
        print(f"  '¥' count: {yen_count}")

        # Print lines with price symbols
        price_lines = [l.strip() for l in text.splitlines() if "¥" in l or "￥" in l or "起" in l]
        print(f"  Lines with price info: {len(price_lines)}")
        for line in price_lines[:20]:
            print(f"    → {line[:120]}")

        # NEW: intercept network to find price API
        print("\n  --- NETWORK REQUESTS (XHR/Fetch) ---")
        # We already missed the requests since page loaded. Let's do a reload and capture.

        await browser.close()
        print("\nDone.")


asyncio.run(main())
