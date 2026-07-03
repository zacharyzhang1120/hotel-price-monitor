"""Open a visible browser for manual Ctrip login, save session state.

Usage:
    python3 scripts/login_ctrip.py

This opens a real Chrome window. Log in by any method:
  - Scan QR code with Ctrip App
  - Phone number + password
  - SMS verification code

After successful login, the session (cookies, localStorage) is saved
to data/ctrip_state.json for reuse by the scraper.

To use on a remote server: copy data/ctrip_state.json from local to server.
"""

import asyncio
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from playwright.async_api import async_playwright
from app.config import CTRIP_STATE_FILE

HOTEL_URL = "https://hotels.ctrip.com/hotels/detail/?cityEnName=Haikou&cityId=42&hotelId=436575"


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)  # visible browser!
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

        print("=" * 60)
        print("  携程登录助手")
        print("=" * 60)
        print()
        print("即将打开携程酒店页面。如果跳转到登录页，请登录：")
        print("  - 扫码登录（推荐，有效期长）")
        print("  - 手机号 + 密码")
        print("  - 短信验证码")
        print()
        print("登录成功后，页面会显示酒店价格。")
        print("看到价格后，回到本终端按 Enter 保存登录状态。")
        print()

        await page.goto(HOTEL_URL, wait_until="domcontentloaded", timeout=30000)
        print(f"当前页面: {page.url}")
        print()

        input(">>> 登录完成后按 Enter 继续... ")

        # Check if we're on the hotel page (not login page)
        current_url = page.url
        if "passport.ctrip.com" in current_url or "login" in current_url.lower():
            print()
            print("⚠️  警告: 当前仍在登录页面。是否仍然保存?")
            print("   如果未登录，抓取器将无法获取价格。")
            confirm = input(">>> 输入 y 继续保存, n 取消: ")
            if confirm.lower() != "y":
                print("已取消。")
                await browser.close()
                return

        # Save storage state
        state = await context.storage_state()
        CTRIP_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CTRIP_STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n✅ 登录状态已保存到: {CTRIP_STATE_FILE}")
        print(f"   文件大小: {CTRIP_STATE_FILE.stat().st_size} bytes")

        # Quick verify
        try:
            await page.goto(HOTEL_URL, wait_until="domcontentloaded", timeout=15000)
            await page.wait_for_timeout(3000)
            text = await page.locator("body").inner_text()
            has_price = "¥" in text or "￥" in text
            print(f"   价格可见: {'✅ 是' if has_price else '⚠️ 未检测到价格符号'}")
        except Exception as e:
            print(f"   验证失败: {e}")

        await browser.close()
        print("\n完成。现在可以运行抓取器了。")


if __name__ == "__main__":
    asyncio.run(main())
