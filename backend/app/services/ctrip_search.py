"""Ctrip hotel name search helpers."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote

import httpx


CTRIP_LIST_URL = "https://hotels.ctrip.com/hotels/list"
CTRIP_DETAIL_URL = "https://hotels.ctrip.com/hotels/detail/"
CTRIP_SUGGEST_URL = "https://m.ctrip.com/restapi/soa2/21881/json/gaHotelSearchEngine"
DEFAULT_CITY_ID = 42


@dataclass(frozen=True)
class CtripHotelCandidate:
    hotel_id: str
    name: str
    url: str
    score: float


async def search_ctrip_hotel_by_name(
    hotel_name: str,
    city_id: int = DEFAULT_CITY_ID,
    timeout: float = 15,
) -> list[CtripHotelCandidate]:
    """Search Ctrip list page and return likely candidates for a hotel name."""
    keyword = hotel_name.strip()
    if not keyword:
        return []

    url = f"{CTRIP_LIST_URL}?cityId={city_id}&keyword={quote(keyword)}"
    async with httpx.AsyncClient(
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9",
        },
        follow_redirects=True,
        timeout=timeout,
    ) as client:
        candidates = await _search_ctrip_suggest(client, keyword, city_id)
        if candidates:
            candidates.sort(key=lambda item: item.score, reverse=True)
            return candidates[:8]

        response = await client.get(url)
        response.raise_for_status()
    candidates = _parse_ctrip_candidates(response.text, keyword, city_id)
    candidates.sort(key=lambda item: item.score, reverse=True)
    return candidates[:8]


def best_ctrip_match(candidates: list[CtripHotelCandidate], min_score: float = 0.82) -> Optional[CtripHotelCandidate]:
    if not candidates:
        return None
    candidate = candidates[0]
    return candidate if candidate.score >= min_score else None


def _parse_ctrip_candidates(html_text: str, keyword: str, city_id: int) -> list[CtripHotelCandidate]:
    text = html.unescape(html_text)
    pattern = re.compile(
        r'data-offline-hotelId="(?P<hotel_id>\d+)".{0,2500}?<span class="hotelName">(?P<name>.*?)</span>',
        re.DOTALL,
    )
    seen: set[str] = set()
    candidates: list[CtripHotelCandidate] = []
    for match in pattern.finditer(text):
        hotel_id = match.group("hotel_id")
        name = _strip_tags(match.group("name"))
        if not hotel_id or not name or hotel_id in seen:
            continue
        seen.add(hotel_id)
        candidates.append(
            CtripHotelCandidate(
                hotel_id=hotel_id,
                name=name,
                url=f"{CTRIP_DETAIL_URL}?cityId={city_id}&hotelId={hotel_id}",
                score=_score_name_match(keyword, name),
            )
        )
    return candidates


async def _search_ctrip_suggest(
    client: httpx.AsyncClient,
    keyword: str,
    city_id: int,
) -> list[CtripHotelCandidate]:
    response = await client.post(
        CTRIP_SUGGEST_URL,
        json={"keyword": keyword, "searchType": "H", "cityId": city_id},
    )
    response.raise_for_status()
    payload = response.json()
    results = payload.get("Response", {}).get("searchResults", [])
    candidates: list[CtripHotelCandidate] = []
    seen: set[str] = set()
    for item in results:
        if item.get("type") != "Hotel":
            continue
        if item.get("cityId") and int(item["cityId"]) != city_id:
            continue
        hotel_id = str(item.get("id") or "")
        name = str(item.get("word") or item.get("displayName") or "").split(",")[0].strip()
        if not hotel_id or not name or hotel_id in seen:
            continue
        seen.add(hotel_id)
        candidates.append(
            CtripHotelCandidate(
                hotel_id=hotel_id,
                name=name,
                url=f"{CTRIP_DETAIL_URL}?cityId={city_id}&hotelId={hotel_id}",
                score=_score_name_match(keyword, name),
            )
        )
    return candidates


def _strip_tags(value: str) -> str:
    text = re.sub(r"<[^>]+>", "", value)
    return re.sub(r"\s+", "", text)


def _normalize_name(value: str) -> str:
    text = re.sub(r"\s+", "", value)
    text = text.replace("（", "(").replace("）", ")")
    return text.lower()


def _score_name_match(keyword: str, candidate: str) -> float:
    expected = _normalize_name(keyword)
    actual = _normalize_name(candidate)
    if not expected or not actual:
        return 0
    if expected == actual:
        return 1
    if expected in actual or actual in expected:
        return 0.94

    expected_parts = set(_split_name_tokens(expected))
    actual_parts = set(_split_name_tokens(actual))
    if not expected_parts or not actual_parts:
        return 0
    overlap = len(expected_parts & actual_parts)
    union = len(expected_parts | actual_parts)
    return overlap / union if union else 0


def _split_name_tokens(value: str) -> list[str]:
    return [item for item in re.split(r"[()·\-_/|,，.。]+", value) if item]
