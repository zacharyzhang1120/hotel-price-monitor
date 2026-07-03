"""Pydantic schemas for Hotel."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class HotelPlatformResponse(BaseModel):
    id: int
    platform: str
    platform_hotel_id: str
    hotel_url: Optional[str] = None
    default_room_name: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class HotelBase(BaseModel):
    name: str
    is_mine: bool = False
    distance_km: Optional[float] = None


class HotelCreate(HotelBase):
    pass


class HotelUpdate(BaseModel):
    name: Optional[str] = None
    is_mine: Optional[bool] = None
    distance_km: Optional[float] = None


class HotelCompetitorsUpdate(BaseModel):
    competitor_ids: list[int]


class HotelPlatformUpsert(BaseModel):
    hotel_url: str
    default_room_name: Optional[str] = None
    platform_hotel_id: Optional[str] = None


class HotelPlatformAutoMatchCandidate(BaseModel):
    hotel_id: str
    name: str
    url: str
    score: float


class HotelPlatformAutoMatchResponse(BaseModel):
    matched: bool
    hotel_id: Optional[int] = None
    hotel_name: Optional[str] = None
    mapping: Optional[HotelPlatformResponse] = None
    candidates: list[HotelPlatformAutoMatchCandidate] = []
    message: str


class HotelPlatformGroupAutoMatchResponse(BaseModel):
    total: int
    matched: int
    skipped: int
    failed: int
    results: list[HotelPlatformAutoMatchResponse]


class HotelResponse(HotelBase):
    id: int
    created_at: datetime
    platform_mappings: list[HotelPlatformResponse] = []
    competitor_ids: list[int] = []

    model_config = {"from_attributes": True}
