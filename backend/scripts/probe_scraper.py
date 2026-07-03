"""Probe a real OTA scraper without writing data to the database."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from app.services.probe_service import probe_scraper  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe a real OTA scraper with one URL and one date.")
    parser.add_argument("--platform", required=True, choices=["ctrip", "qunar", "tongcheng"])
    parser.add_argument("--url", required=True)
    parser.add_argument("--date", default=date.today().isoformat(), help="入住日期，格式 YYYY-MM-DD")
    parser.add_argument("--room", default=None, help="可选：期望房型名，用于辅助识别房型")
    parser.add_argument("--mode", default="real", choices=["real", "mock"], help="real 真实抓取；mock 仅验证链路")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    check_in_date = date.fromisoformat(args.date)
    payload = await probe_scraper(args.platform, args.url, check_in_date, room_name=args.room, mode=args.mode)
    for point in payload["points"]:
        point["check_in_date"] = point["check_in_date"].isoformat()
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
