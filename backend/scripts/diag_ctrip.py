"""Diagnose Ctrip scraper — save page content for inspection."""
import asyncio
import sys
from datetime import date
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from playwright.async_api import async_playwright

HOTEL_URL = "https://hotels.ctrip.com/hotels/detail/?cityEnName=Haikou&cityId=42&hotelId=436575"
CHECK_IN = date.today()
OUT_DIR = ROOT_DIR / "data" / "diag"
OUT_DIR.mkdir(parents=True, exist_ok=True)


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 900},
            locale="zh-CN",
        )

        print(f"Navigating to Ctrip...")
        await page.goto(HOTEL_URL, wait_until="domcontentloaded", timeout=30000)
        print(f"  URL after load: {page.url}")
        print(f"  Title: {await page.title()}")

        # Wait extra for dynamic content
        await page.wait_for_timeout(5000)

        # Save screenshot
        await page.screenshot(path=str(OUT_DIR / "ctrip_page.png"), full_page=False)
        print(f"  Screenshot saved to data/diag/ctrip_page.png")

        # Save HTML (first 50000 chars)
        html = await page.content()
        (OUT_DIR / "ctrip_page.html").write_text(html, encoding="utf-8")
        print(f"  HTML saved to data/diag/ctrip_page.html ({len(html)} chars)")

        # Save inner text (first 10000 chars)
        text = await page.locator("body").inner_text(timeout=10000)
        (OUT_DIR / "ctrip_page.txt").write_text(text[:20000], encoding="utf-8")
        print(f"  Body text saved to data/diag/ctrip_page.txt ({len(text)} chars)")

        # Try to find price elements
        price_elements = await page.locator('[class*="price"], [class*="Price"]').all()
        print(f"\n  Elements with 'price' in class: {len(price_elements)}")
        for el in price_elements[:5]:
            try:
                txt = await el.inner_text()
                print(f"    → {txt[:80]}")
            except:
                pass

        # Check for common Ctrip price selectors
        for sel in [".price", ".real-price", ".base-price", "[data-price]", ".J_price", ".hotel-price"]:
            count = await page.locator(sel).count()
            if count > 0:
                txt = await page.locator(sel).first.inner_text()
                print(f"  Selector '{sel}': {count} matches, first text: {txt[:60]}")

        # Check if page has ¥ symbol at all
        yen_count = text.count("¥") + text.count("￥")
        print(f"\n  '¥' or '￥' occurrences in body text: {yen_count}")

        # Print first 30 lines that contain ¥ or price-like numbers
        for line in text.splitlines()[:200]:
            if "¥" in line or "￥" in line or "price" in line.lower():
                print(f"  [PRICE LINE] {line.strip()[:120]}")

        await browser.close()
        print("\nDone. Check data/diag/ for output files.")


asyncio.run(main())
