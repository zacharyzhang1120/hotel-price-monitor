"""Shared Playwright helpers for real OTA scrapers."""

from __future__ import annotations

from dataclasses import dataclass
import re
import random
from datetime import date, timedelta
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.config import SCRAPE_DELAY_MAX_MS, SCRAPE_DELAY_MIN_MS

PRICE_PATTERN = re.compile(r"[¥￥]\s*([0-9][0-9,]{1,8}(?:\.[0-9]+)?)")
ROOM_KEYWORDS = ("房", "床", "套")
GENERIC_ROOM_NAMES = {"大床房", "双床房", "标准房", "标准间", "客房", "单人房", "双人房"}
ROOM_PRICE_CONTEXT_MARKERS = ("房型摘要", "今日价格", "可住人数", "无早餐", "份早餐", "在线付", "预订")
ROOM_NOISE_WORDS = (
    "早餐",
    "预订",
    "立即",
    "取消",
    "在线",
    "到店",
    "积分",
    "红包",
    "券",
    "低价",
    "每间",
    "均价",
    "含税",
    "支付",
    "担保",
    "规则",
    "查看",
    "展开",
    "收起",
    "仅剩",
    "入住",
    "退房",
    "加床",
    "婴儿床",
    "儿童",
    "政策",
    "时间",
    "电话",
    "摘要",
    "详情",
    "可住人数",
    "今日价格",
    "选择房间",
    "房量",
    "洗衣房",
    "健身房",
    "客房数",
    "停车",
    "酒店设施",
    "酒店特色",
    "房间",
    "类型",
    "固定套餐",
)
PRICE_NOISE_WORDS = (
    "积分",
    "券",
    "代金券",
    "红包",
    "立减",
    "返",
    "火车新客",
    "接送机",
    "礼包",
)
VALID_RATE_LABELS = ("会员价", "贵宾价", "特惠", "一口价", "专享价", "品牌首单")


@dataclass(frozen=True)
class RoomPriceCandidate:
    room: str
    price: float


def with_check_in_params(url: str, check_in_date: date) -> str:
    check_out_date = check_in_date + timedelta(days=1)
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update(
        {
            "checkIn": check_in_date.isoformat(),
            "checkOut": check_out_date.isoformat(),
            "checkin": check_in_date.isoformat(),
            "checkout": check_out_date.isoformat(),
        }
    )
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def with_qunar_date_params(url: str, check_in_date: date) -> str:
    check_out_date = check_in_date + timedelta(days=1)
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update(
        {
            "fromDate": check_in_date.isoformat(),
            "toDate": check_out_date.isoformat(),
        }
    )
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _extract_prices(text: str) -> list[float]:
    prices = [float(match.group(1).replace(",", "")) for match in PRICE_PATTERN.finditer(text)]
    return [price for price in prices if 80 <= price <= 10000]


def extract_lowest_price(text: str) -> Optional[float]:
    prices = _extract_prices(text)
    if not prices:
        return None
    return min(prices)


def _normalize_line(line: str) -> str:
    return re.sub(r"\s+", " ", line.strip())


def _is_room_candidate(line: str) -> bool:
    cleaned = _normalize_line(line)
    if not 2 <= len(cleaned) <= 80:
        return False
    if PRICE_PATTERN.search(cleaned):
        return False
    if re.search(r"\d+\s*张.*床", cleaned):
        return False
    if len(cleaned) > 28 and any(mark in cleaned for mark in "，。；："):
        return False
    if not any(keyword in cleaned for keyword in ROOM_KEYWORDS):
        return False
    return not any(word in cleaned for word in ROOM_NOISE_WORDS)


def _room_name_score(line: str, distance: int = 0) -> int:
    cleaned = _normalize_line(line)
    score = min(len(cleaned), 40) - distance * 2
    if cleaned in GENERIC_ROOM_NAMES:
        score -= 18
    if any(mark in cleaned for mark in ("【", "】", "[", "]", "（", "）", "(", ")", "「", "」", "『", "』")):
        score += 6
    if any(word in cleaned for word in ("高级", "豪华", "精选", "智能", "影音", "贵宾", "商务", "景观", "零压", "亲子")):
        score += 5
    return score


def _has_room_price_context(lines: list[str], room_idx: int, price_idx: int) -> bool:
    start = min(room_idx, price_idx)
    end = max(room_idx, price_idx) + 1
    context = "\n".join(lines[start:end])
    return any(marker in context for marker in ROOM_PRICE_CONTEXT_MARKERS)


def extract_room_name(
    text: str,
    default_room_name: Optional[str],
    *,
    prefer_default: bool = True,
) -> Optional[str]:
    if default_room_name and default_room_name in text:
        if prefer_default:
            return default_room_name

    candidates = [_normalize_line(line) for line in text.splitlines() if _is_room_candidate(line)]
    if candidates:
        if not prefer_default:
            return max(candidates, key=_room_name_score)
        return candidates[0]

    if default_room_name and default_room_name in text:
        return default_room_name

    return default_room_name


def extract_room_name_for_price(
    text: str,
    target_price: float,
    default_room_name: Optional[str] = None,
    *,
    fallback_to_default: bool = True,
) -> Optional[str]:
    """Find the room name nearest to a specific visible price."""
    lines = [_normalize_line(line) for line in text.splitlines() if _normalize_line(line)]
    if not lines:
        return default_room_name if fallback_to_default else None

    target_indices = []
    for idx, line in enumerate(lines):
        line_prices = _extract_prices(line)
        if any(abs(price - target_price) < 0.01 for price in line_prices):
            target_indices.append(idx)

    scored_candidates: list[tuple[int, str]] = []
    for price_idx in target_indices:
        lower_bound = max(-1, price_idx - 28)
        for room_idx in range(price_idx - 1, lower_bound, -1):
            if PRICE_PATTERN.search(lines[room_idx]):
                continue
            if _is_room_candidate(lines[room_idx]):
                has_context = _has_room_price_context(lines, room_idx, price_idx)
                if lines[room_idx] in GENERIC_ROOM_NAMES and not has_context:
                    continue
                distance = price_idx - room_idx
                context_bonus = 12 if has_context else 0
                scored_candidates.append((_room_name_score(lines[room_idx], distance) + context_bonus, lines[room_idx]))

        upper_bound = min(len(lines), price_idx + 6)
        for room_idx in range(price_idx + 1, upper_bound):
            if PRICE_PATTERN.search(lines[room_idx]):
                break
            if _is_room_candidate(lines[room_idx]):
                has_context = _has_room_price_context(lines, room_idx, price_idx)
                if lines[room_idx] in GENERIC_ROOM_NAMES and not has_context:
                    continue
                distance = room_idx - price_idx
                context_bonus = 12 if has_context else 0
                scored_candidates.append((_room_name_score(lines[room_idx], distance) + context_bonus, lines[room_idx]))

    if scored_candidates:
        return max(scored_candidates, key=lambda item: item[0])[1]

    if not fallback_to_default:
        return None

    dynamic_room = extract_room_name(text, default_room_name, prefer_default=False)
    if dynamic_room:
        return dynamic_room

    if default_room_name and default_room_name in text:
        return default_room_name
    return default_room_name


def _is_price_noise_line(line: str) -> bool:
    cleaned = _normalize_line(line)
    if any(label in cleaned for label in VALID_RATE_LABELS):
        return False
    return any(word in cleaned for word in PRICE_NOISE_WORDS)


def _split_room_price_groups(lines: list[str]) -> list[tuple[str, list[str]]]:
    groups: list[tuple[str, list[str]]] = []
    current_room: Optional[str] = None
    current_lines: list[str] = []

    for line in lines:
        if _is_room_candidate(line):
            if current_room and current_lines:
                groups.append((current_room, current_lines))
            current_room = line
            current_lines = [line]
            continue

        if current_room:
            current_lines.append(line)

    if current_room and current_lines:
        groups.append((current_room, current_lines))
    return groups


def extract_room_price_candidates(text: str) -> list[RoomPriceCandidate]:
    """Extract same-card room/price pairs from Ctrip-style room text."""
    lines = [_normalize_line(line) for line in text.splitlines() if _normalize_line(line)]
    groups = _split_room_price_groups(lines)
    candidates: list[RoomPriceCandidate] = []
    seen: set[tuple[str, float]] = set()

    for room, group_lines in groups:
        prices: list[float] = []
        for idx, line in enumerate(group_lines):
            if not PRICE_PATTERN.search(line):
                continue

            nearby_context = "\n".join(group_lines[max(0, idx - 1): idx + 1])
            if _is_price_noise_line(nearby_context):
                continue

            prices.extend(_extract_prices(line))

        if not prices:
            continue

        price = min(prices)
        key = (room, price)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(RoomPriceCandidate(room=room, price=price))

    return candidates


def extract_cheapest_room_price_candidate(text: str) -> Optional[RoomPriceCandidate]:
    candidates = extract_room_price_candidates(text)
    if not candidates:
        return None
    return min(candidates, key=lambda candidate: candidate.price)


async def human_delay(page) -> None:
    min_ms = max(0, SCRAPE_DELAY_MIN_MS)
    max_ms = max(min_ms, SCRAPE_DELAY_MAX_MS)
    await page.wait_for_timeout(random.randint(min_ms, max_ms))
