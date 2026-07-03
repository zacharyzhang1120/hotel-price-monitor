"""Pydantic schemas for PriceRecord."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Optional, Union

from pydantic import BaseModel, Field, computed_field


class PriceRecordResponse(BaseModel):
    id: int
    hotel_id: int
    hotel_name: Optional[str] = None
    platform: str
    check_in_date: date
    cheapest_room: Optional[str] = None
    cheapest_price: Optional[float] = None
    scraped_at: datetime

    model_config = {"from_attributes": True}


class CalendarPriceItem(BaseModel):
    """Single price point for calendar view."""
    hotel_id: int
    hotel_name: str
    is_mine: bool
    platform: str
    check_in_date: date
    cheapest_room: Optional[str] = None
    cheapest_price: Optional[float]
    scraped_at: Optional[datetime] = None
    batch_id: Optional[int] = None
    is_current_batch: bool = False
    is_fallback: bool = False
    task_status: Optional[str] = None
    task_error_message: Optional[str] = None


class CalendarResponse(BaseModel):
    data: list[CalendarPriceItem]


class TrendItem(BaseModel):
    scraped_at: datetime
    platform: str
    cheapest_price: Optional[float]


class TrendResponse(BaseModel):
    data: list[TrendItem]


class ScrapeTriggerResponse(BaseModel):
    task_id: str
    status: str
    message: str


class ScrapeMilestone(BaseModel):
    type: Literal["success", "timeout", "failed"]
    elapsed_s: float
    message: str
    hotel_id: Optional[int] = None
    hotel_name: Optional[str] = None
    platform: Optional[str] = None


class ScrapeStatusResponse(BaseModel):
    status: str
    progress: Optional[str] = None
    error: Optional[str] = None
    batch_id: Optional[int] = None
    milestones: list[ScrapeMilestone] = Field(default_factory=list)
    wall_time_s: Optional[float] = None
    total_tasks: int = 0
    success_tasks: int = 0
    failed_tasks: int = 0
    completed_tasks: int = 0


class ScrapeRunResponse(BaseModel):
    id: int
    trigger_type: str
    status: str
    started_at: datetime
    finished_at: Optional[datetime] = None
    total_tasks: int
    success_tasks: int
    failed_tasks: int
    error_summary: Optional[str] = None

    model_config = {"from_attributes": True}

    @computed_field
    @property
    def wall_time_s(self) -> Optional[float]:
        if not self.finished_at:
            return None
        return round((self.finished_at - self.started_at).total_seconds(), 1)


class ScrapeTaskResultResponse(BaseModel):
    id: int
    batch_id: int
    hotel_id: int
    hotel_name: str
    platform: str
    status: str
    records_count: int
    error_message: Optional[str] = None
    has_evidence: bool = False
    started_at: datetime
    finished_at: datetime

    model_config = {"from_attributes": True}


class ScrapeTaskEvidenceResponse(BaseModel):
    id: int
    batch_id: int
    hotel_id: int
    hotel_name: str
    platform: str
    status: str
    evidence: Optional[dict] = None


class ScrapeConfigResponse(BaseModel):
    scraper_mode: str
    enabled_platforms: list[str]
    real_platforms: list[str]
    scheduler_enabled: bool
    schedule_hours: list[int]
    scheduled_scrape_scope: str = "today"
    future_days: int
    scrape_concurrency: int
    scrape_goto_wait_until: str = "domcontentloaded"
    scrape_mapping_timeout: int
    scrape_probe_timeout: int
    scrape_today_first: bool = False
    scrape_fast_mapping_timeout: int = 0
    scheduled_scrape_fast_mapping_timeout: int = 0
    scheduled_scrape_retry_failed_today: bool = False
    price_fallback_max_age_hours: int = 24
    report_push_enabled: bool
    wecom_webhook_configured: bool


class MissingMappingItem(BaseModel):
    hotel_id: int
    hotel_name: str
    platform: str
    reason: Optional[str] = None


class SessionStatus(BaseModel):
    platform: str
    has_session: bool
    cookie_count: int


class ScrapeReadinessResponse(BaseModel):
    scraper_mode: str
    enabled_platforms: list[str]
    active_real_platforms: list[str]
    hotels_total: int
    my_hotels_count: int
    competitors_count: int
    mappings_total: int
    sessions: list[SessionStatus] = []
    mappings_with_url: int
    missing_enabled_mappings: list[MissingMappingItem]
    missing_real_urls: list[MissingMappingItem]
    invalid_real_urls: list[MissingMappingItem]
    ready_for_mock: bool
    ready_for_real: bool
    messages: list[str]


class ScrapeProbeRequest(BaseModel):
    platform: str
    hotel_url: str
    check_in_date: date
    room_name: Optional[str] = None
    mode: Literal["real", "mock"] = "real"


class ScrapeProbePoint(BaseModel):
    check_in_date: date
    cheapest_room: Optional[str] = None
    cheapest_price: Optional[float] = None


class ScrapeProbeResponse(BaseModel):
    success: bool
    platform: str
    mode: str
    points: list[ScrapeProbePoint]
    error: Optional[str] = None


class ReportGenerateResponse(BaseModel):
    data: Union[dict, str]
