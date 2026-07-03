"""Helpers for platform mapping maintenance."""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse


PLACEHOLDER_HOSTS = {"example.com", "www.example.com"}


def infer_platform_hotel_id(platform: str, url: str) -> Optional[str]:
    parsed = urlparse(url)
    text = f"{parsed.path}?{parsed.query}"
    if platform == "ctrip":
        match = re.search(r"/hotel/(\d+)\.html", text)
        if match:
            return match.group(1)
        match = re.search(r"(?:[?&])hotelId=(\d+)", text)
        if match:
            return match.group(1)
    if platform == "tongcheng":
        match = re.search(r"/hotel/(\d+)/?", text)
        if match:
            return match.group(1)
    if platform == "qunar":
        match = re.search(r"(?:seq|hotelId|id)=([^&]+)", text)
        if match:
            return match.group(1)
        return parsed.path.strip("/") or parsed.netloc
    return None


def validate_platform_hotel_url(platform: str, url: Optional[str]) -> Optional[str]:
    if not url:
        return "缺少 URL"

    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.strip("/")
    text = f"{parsed.path}?{parsed.query}"
    if parsed.scheme not in {"http", "https"} or not host:
        return "URL 格式不正确"
    if host in PLACEHOLDER_HOSTS:
        return "示例 URL 不能用于真实抓取"

    if platform == "ctrip":
        if "ctrip.com" not in host:
            return "携程 URL 域名不匹配"
        if not re.search(r"/hotel/\d+\.html", text) and not re.search(r"(?:[?&])hotelId=\d+", text):
            return "携程 URL 应为酒店详情页"
        return None

    if platform == "tongcheng":
        if "ly.com" not in host and "elong.com" not in host:
            return "同程 URL 域名不匹配"
        if not re.search(r"/hotel/\d+/?", text):
            return "同程 URL 应为酒店详情页"
        return None

    if platform == "qunar":
        if "qunar.com" not in host:
            return "去哪儿 URL 域名不匹配"
        if re.search(r"(?:seq|hotelId|id)=([^&]+)", text):
            return None
        if not path or path in {"hotel", "hotels"}:
            return "去哪儿 URL 应为酒店详情页，不能是首页"
        return None

    return "不支持的平台"
