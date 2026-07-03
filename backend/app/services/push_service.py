"""Optional report push channels."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import httpx

from app.config import REPORT_PUSH_ENABLED, WECOM_PUSH_TIMEOUT, WECOM_WEBHOOK_URL

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PushResult:
    enabled: bool
    sent: bool
    channel: Optional[str] = None
    error: Optional[str] = None


class ReportPushService:
    async def push_text(self, text: str) -> PushResult:
        if not REPORT_PUSH_ENABLED:
            return PushResult(enabled=False, sent=False)
        if not WECOM_WEBHOOK_URL:
            return PushResult(enabled=True, sent=False, channel="wecom", error="WECOM_WEBHOOK_URL is not configured")

        payload = {
            "msgtype": "text",
            "text": {"content": text},
        }
        try:
            async with httpx.AsyncClient(timeout=WECOM_PUSH_TIMEOUT) as client:
                response = await client.post(WECOM_WEBHOOK_URL, json=payload)
                response.raise_for_status()
        except Exception as exc:
            logger.exception("Report push failed")
            return PushResult(enabled=True, sent=False, channel="wecom", error=str(exc))

        return PushResult(enabled=True, sent=True, channel="wecom")
