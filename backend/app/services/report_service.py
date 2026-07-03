"""Report generation service."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any, Optional, Union
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Hotel, ScrapeRun
from app.services.price_service import PriceService

PLATFORM_LABELS = {
    "ctrip": "携程",
}
LOCAL_TIMEZONE = ZoneInfo("Asia/Shanghai")


class ReportService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.price_service = PriceService(session)

    async def generate_daily_summary(
        self,
        report_date: date,
        batch_id: Optional[int] = None,
        mine_hotel_id: Optional[int] = None,
    ) -> dict[str, Any]:
        hotels = {
            hotel.id: hotel
            for hotel in (
                await self.session.execute(select(Hotel).options(selectinload(Hotel.competitor_links)))
            ).scalars().all()
        }
        selected_mine_hotel_id = self._resolve_mine_hotel_id(hotels, mine_hotel_id)
        calendar_hotel_ids = self._resolve_report_hotel_ids(hotels, selected_mine_hotel_id)
        calendar = await self.price_service.get_calendar(
            report_date,
            days=1,
            hotel_ids=calendar_hotel_ids,
            batch_id=batch_id,
        )
        resolved_batch_id = batch_id or self._resolve_calendar_batch_id(calendar)
        scrape_run = None
        if resolved_batch_id:
            scrape_run = await self.session.get(ScrapeRun, resolved_batch_id)

        my_items = [item for item in calendar if item.is_mine and item.cheapest_price is not None]
        if not my_items:
            return {
                "date": report_date.isoformat(),
                "batch_id": resolved_batch_id,
                "scrape_time": scrape_run.finished_at.isoformat() if scrape_run and scrape_run.finished_at else None,
                "my_hotel": None,
                "competitors": [],
                "missing_competitors": [],
            }

        my_hotel_name = my_items[0].hotel_name
        my_platforms = {
            item.platform: {"room": item.cheapest_room, "price": item.cheapest_price}
            for item in my_items
        }
        baseline_item = min(my_items, key=lambda item: item.cheapest_price or float("inf"))
        my_hotel = {
            "name": my_hotel_name,
            "baseline_platform": baseline_item.platform,
            "baseline_room": baseline_item.cheapest_room,
            "baseline_price": baseline_item.cheapest_price,
            "platforms": my_platforms,
        }

        my_prices_by_platform = {
            item.platform: item.cheapest_price
            for item in my_items
            if item.cheapest_price is not None
        }
        competitors = []
        missing_competitors = []
        competitor_ids = sorted({item.hotel_id for item in calendar if not item.is_mine})
        for hotel_id in competitor_ids:
            hotel_calendar_items = [
                item
                for item in calendar
                if item.hotel_id == hotel_id
            ]
            items = [
                item
                for item in hotel_calendar_items
                if item.cheapest_price is not None
            ]
            if not items:
                if hotel_calendar_items:
                    missing_competitors.append(
                        {
                            "id": hotel_id,
                            "name": hotel_calendar_items[0].hotel_name,
                            "platforms": sorted({item.platform for item in hotel_calendar_items}),
                        }
                    )
                continue
            lowest_item = min(items, key=lambda item: item.cheapest_price or float("inf"))
            platforms = {}
            for item in items:
                my_platform_price = my_prices_by_platform.get(item.platform)
                platforms[item.platform] = {
                    "room": item.cheapest_room,
                    "price": item.cheapest_price,
                    "vs_mine_same_platform": (
                        item.cheapest_price - my_platform_price
                        if my_platform_price is not None and item.cheapest_price is not None
                        else None
                    ),
                }

            competitors.append(
                {
                    "id": hotel_id,
                    "name": items[0].hotel_name,
                    "distance_km": hotels[hotel_id].distance_km if hotel_id in hotels else None,
                    "platforms": platforms,
                    "lowest_price": lowest_item.cheapest_price,
                    "lowest_platform": lowest_item.platform,
                    "vs_mine": (
                        lowest_item.cheapest_price - baseline_item.cheapest_price
                        if lowest_item.cheapest_price is not None and baseline_item.cheapest_price is not None
                        else None
                    ),
                }
            )

        competitors.sort(key=lambda item: item["lowest_price"] or float("inf"))
        return {
            "date": report_date.isoformat(),
            "batch_id": resolved_batch_id,
            "scrape_time": scrape_run.finished_at.isoformat() if scrape_run and scrape_run.finished_at else None,
            "my_hotel": my_hotel,
            "competitors": competitors,
            "missing_competitors": missing_competitors,
        }

    def _resolve_mine_hotel_id(self, hotels: dict[int, Hotel], mine_hotel_id: Optional[int]) -> Optional[int]:
        if mine_hotel_id and hotels.get(mine_hotel_id) and hotels[mine_hotel_id].is_mine:
            return mine_hotel_id
        my_hotels = sorted((hotel for hotel in hotels.values() if hotel.is_mine), key=lambda hotel: hotel.id)
        return my_hotels[0].id if my_hotels else None

    def _resolve_report_hotel_ids(self, hotels: dict[int, Hotel], mine_hotel_id: Optional[int]) -> Optional[list[int]]:
        if not mine_hotel_id:
            return None
        mine_hotel = hotels.get(mine_hotel_id)
        if not mine_hotel:
            return None
        competitor_ids = mine_hotel.competitor_ids
        if not competitor_ids:
            competitor_ids = [hotel.id for hotel in sorted(hotels.values(), key=lambda item: item.id) if not hotel.is_mine]
        return [mine_hotel_id, *competitor_ids]

    @staticmethod
    def _resolve_calendar_batch_id(calendar: list[Any]) -> Optional[int]:
        priced_items = [
            item
            for item in calendar
            if item.cheapest_price is not None and item.batch_id is not None
        ]
        if not priced_items:
            return None
        return max(
            priced_items,
            key=lambda item: (item.scraped_at or datetime.min, item.batch_id or 0),
        ).batch_id

    def format_for_push(self, summary: dict[str, Any], output_format: str) -> str:
        if output_format == "json":
            return json.dumps(summary, ensure_ascii=False, indent=2)
        if output_format == "wechat_markdown":
            return self._format_wechat_text(summary)
        if output_format == "wechat_text":
            return self._format_wechat_text(summary)
        raise ValueError(f"Unsupported report format: {output_format}")

    def _format_wechat_text(self, summary: dict[str, Any]) -> str:
        my_hotel = summary.get("my_hotel")
        if not my_hotel:
            return "暂无可用价格数据"

        time_label = _local_time_label(summary.get("scrape_time"))
        baseline_platform = my_hotel["baseline_platform"]
        baseline_platform_label = PLATFORM_LABELS.get(baseline_platform, baseline_platform)

        lines = [
            f"📊 {summary['date']} {time_label[-5:]} 竞对价格日报",
            "━━━━━━━━━━━━━━━━━━━━",
            f"🏨 我方：{my_hotel['name']}",
            (
                f"最低起价：{baseline_platform_label} "
                f"{my_hotel.get('baseline_room') or ''} ¥{_money(my_hotel['baseline_price'])}"
            ),
            "平台价格：" + " | ".join(
                f"{PLATFORM_LABELS.get(platform, platform)} ¥{_money(data['price'])}"
                for platform, data in my_hotel["platforms"].items()
            ),
            "",
            "竞对价格：",
        ]

        threats = []
        for competitor in summary["competitors"]:
            distance = competitor.get("distance_km")
            distance_label = f"（{distance:g}km）" if distance is not None else ""
            lines.append(f"{competitor['name']}{distance_label}")
            for platform, data in competitor["platforms"].items():
                platform_label = PLATFORM_LABELS.get(platform, platform)
                diff = data.get("vs_mine_same_platform")
                diff_label = _diff(diff)
                lowest_mark = "⚠️最低" if platform == competitor["lowest_platform"] and competitor["vs_mine"] < 0 else (
                    "最低" if platform == competitor["lowest_platform"] else ""
                )
                room = f"{data.get('room')} " if data.get("room") else ""
                lines.append(
                    f"  {platform_label} {room}¥{_money(data['price'])}（较我方同平台 {diff_label}）{lowest_mark}"
                )
            lines.append("")
            if competitor.get("vs_mine") is not None and competitor["vs_mine"] < 0:
                threats.append(
                    f"{competitor['name']}·{PLATFORM_LABELS.get(competitor['lowest_platform'], competitor['lowest_platform'])} "
                    f"¥{_money(competitor['lowest_price'])}（低 ¥{_money(abs(competitor['vs_mine']))}）"
                )

        missing_competitors = summary.get("missing_competitors") or []
        if missing_competitors:
            lines.append("缺价酒店：")
            for item in missing_competitors:
                platforms = "、".join(PLATFORM_LABELS.get(platform, platform) for platform in item.get("platforms", []))
                lines.append(f"  {item['name']}：{platforms or '启用平台'} 暂无有效价格")
            lines.append("")

        if threats:
            lines.append("⚠️ 低于我方最低价：")
            lines.extend(threats)
        elif not summary["competitors"] and not missing_competitors:
            lines.append("暂无竞对价格：请先为当前门店组的竞对配置携程 URL 并完成抓取")
        else:
            lines.append("暂无竞对低于我方最低价")
        lines.append("")
        lines.append(f"⏰ 抓取：{time_label}")
        return "\n".join(lines)


def _money(value: Optional[Union[float, int]]) -> str:
    if value is None:
        return "-"
    return str(int(round(value)))


def _local_time_label(value: Optional[str]) -> str:
    if not value:
        return "未知时间"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value.replace("T", " ")[:16]
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(LOCAL_TIMEZONE).strftime("%Y-%m-%d %H:%M")


def _diff(value: Optional[Union[float, int]]) -> str:
    if value is None:
        return "-"
    if value > 0:
        return f"+¥{_money(value)}"
    if value < 0:
        return f"-¥{_money(abs(value))}"
    return "¥0"
