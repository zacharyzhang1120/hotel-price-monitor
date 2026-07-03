"""Hotel routes."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import PLATFORMS
from app.database import get_db
from app.models import Hotel, HotelCompetitor, HotelPlatformMapping, PriceRecord
from app.schemas.hotel import (
    HotelPlatformAutoMatchCandidate,
    HotelPlatformGroupAutoMatchResponse,
    HotelPlatformAutoMatchResponse,
    HotelCompetitorsUpdate,
    HotelCreate,
    HotelPlatformResponse,
    HotelPlatformUpsert,
    HotelResponse,
    HotelUpdate,
)
from app.services.ctrip_search import best_ctrip_match, search_ctrip_hotel_by_name
from app.services.mapping_utils import infer_platform_hotel_id

router = APIRouter(prefix="/hotels", tags=["hotels"])


@router.get("", response_model=list[HotelResponse])
async def list_hotels(db: AsyncSession = Depends(get_db)):
    await _ensure_default_competitor_links(db)
    stmt = (
        select(Hotel)
        .options(selectinload(Hotel.platform_mappings), selectinload(Hotel.competitor_links))
        .order_by(Hotel.is_mine.desc(), Hotel.id)
    )
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("", response_model=HotelResponse)
async def create_hotel(payload: HotelCreate, db: AsyncSession = Depends(get_db)):
    hotel = Hotel(name=payload.name, is_mine=payload.is_mine, distance_km=payload.distance_km)
    db.add(hotel)
    await db.commit()
    await db.refresh(hotel)
    return await _load_hotel(db, hotel.id)


@router.patch("/{hotel_id}", response_model=HotelResponse)
async def update_hotel(hotel_id: int, payload: HotelUpdate, db: AsyncSession = Depends(get_db)):
    hotel = await db.get(Hotel, hotel_id)
    if not hotel:
        raise HTTPException(status_code=404, detail="酒店不存在")
    if payload.name is not None:
        hotel.name = payload.name
    if payload.is_mine is not None:
        hotel.is_mine = payload.is_mine
    if payload.distance_km is not None:
        hotel.distance_km = payload.distance_km
    if payload.is_mine is False:
        await db.execute(delete(HotelCompetitor).where(HotelCompetitor.mine_hotel_id == hotel_id))
    await db.commit()
    return await _load_hotel(db, hotel_id)


@router.delete("/{hotel_id}")
async def delete_hotel(hotel_id: int, db: AsyncSession = Depends(get_db)):
    hotel = await db.get(Hotel, hotel_id)
    if not hotel:
        raise HTTPException(status_code=404, detail="酒店不存在")

    records_count = (
        await db.execute(select(func.count()).select_from(PriceRecord).where(PriceRecord.hotel_id == hotel_id))
    ).scalar_one()
    if records_count:
        raise HTTPException(status_code=409, detail="该酒店已有价格记录，不能直接删除")

    await db.execute(
        delete(HotelCompetitor).where(
            (HotelCompetitor.mine_hotel_id == hotel_id) | (HotelCompetitor.competitor_hotel_id == hotel_id)
        )
    )
    await db.delete(hotel)
    await db.commit()
    return {"deleted": True, "hotel_id": hotel_id}


@router.put("/{hotel_id}/competitors", response_model=HotelResponse)
async def update_hotel_competitors(
    hotel_id: int,
    payload: HotelCompetitorsUpdate,
    db: AsyncSession = Depends(get_db),
):
    mine_hotel = await db.get(Hotel, hotel_id)
    if not mine_hotel:
        raise HTTPException(status_code=404, detail="我方酒店不存在")
    if not mine_hotel.is_mine:
        raise HTTPException(status_code=400, detail="只能为我方酒店配置竞对")

    competitor_ids = list(dict.fromkeys(payload.competitor_ids))
    if len(competitor_ids) > 5:
        raise HTTPException(status_code=400, detail="每家门店最多配置 5 家竞对")
    if hotel_id in competitor_ids:
        raise HTTPException(status_code=400, detail="我方酒店不能作为自己的竞对")

    if competitor_ids:
        stmt = select(Hotel).where(Hotel.id.in_(competitor_ids))
        competitors = list((await db.execute(stmt)).scalars().all())
        found_ids = {hotel.id for hotel in competitors}
        missing_ids = [item for item in competitor_ids if item not in found_ids]
        if missing_ids:
            raise HTTPException(status_code=404, detail=f"竞对酒店不存在：{','.join(map(str, missing_ids))}")
        if any(hotel.is_mine for hotel in competitors):
            raise HTTPException(status_code=400, detail="竞对列表不能包含我方酒店")

    await db.execute(delete(HotelCompetitor).where(HotelCompetitor.mine_hotel_id == hotel_id))
    for competitor_id in competitor_ids:
        db.add(HotelCompetitor(mine_hotel_id=hotel_id, competitor_hotel_id=competitor_id))
    await db.commit()
    return await _load_hotel(db, hotel_id)


@router.put("/{hotel_id}/platforms/{platform}", response_model=HotelPlatformResponse)
async def upsert_platform_mapping(
    hotel_id: int,
    platform: str,
    payload: HotelPlatformUpsert,
    db: AsyncSession = Depends(get_db),
):
    if platform not in PLATFORMS:
        raise HTTPException(status_code=400, detail="不支持的平台")
    hotel = await db.get(Hotel, hotel_id)
    if not hotel:
        raise HTTPException(status_code=404, detail="酒店不存在")

    platform_hotel_id = payload.platform_hotel_id or infer_platform_hotel_id(platform, payload.hotel_url)
    if not platform_hotel_id:
        raise HTTPException(status_code=400, detail="无法从 URL 推断平台酒店 ID，请传 platform_hotel_id")

    duplicate_stmt = select(HotelPlatformMapping).where(
        HotelPlatformMapping.platform == platform,
        HotelPlatformMapping.platform_hotel_id == platform_hotel_id,
        HotelPlatformMapping.hotel_id != hotel_id,
    )
    duplicate = (await db.execute(duplicate_stmt)).scalar_one_or_none()
    if duplicate:
        raise HTTPException(status_code=409, detail="该平台酒店 ID 已绑定到其他酒店")

    stmt = select(HotelPlatformMapping).where(
        HotelPlatformMapping.hotel_id == hotel_id,
        HotelPlatformMapping.platform == platform,
    )
    mapping = (await db.execute(stmt)).scalar_one_or_none()
    if not mapping:
        mapping = HotelPlatformMapping(hotel_id=hotel_id, platform=platform, platform_hotel_id=platform_hotel_id)
        db.add(mapping)

    mapping.platform_hotel_id = platform_hotel_id
    mapping.hotel_url = payload.hotel_url
    if payload.default_room_name is not None:
        mapping.default_room_name = payload.default_room_name

    await db.commit()
    await db.refresh(mapping)
    return mapping


@router.post("/{hotel_id}/platforms/ctrip/auto-match", response_model=HotelPlatformAutoMatchResponse)
async def auto_match_ctrip_mapping(
    hotel_id: int,
    city_id: int = 42,
    db: AsyncSession = Depends(get_db),
):
    hotel = await db.get(Hotel, hotel_id)
    if not hotel:
        raise HTTPException(status_code=404, detail="酒店不存在")
    return await _auto_match_ctrip_for_hotel(db, hotel, city_id=city_id, skip_existing=False)


@router.post("/{hotel_id}/platforms/ctrip/auto-match-group", response_model=HotelPlatformGroupAutoMatchResponse)
async def auto_match_ctrip_group(
    hotel_id: int,
    city_id: int = 42,
    db: AsyncSession = Depends(get_db),
):
    mine_hotel = await db.get(Hotel, hotel_id)
    if not mine_hotel:
        raise HTTPException(status_code=404, detail="我方酒店不存在")
    mine_hotel = await _load_hotel(db, hotel_id)
    if not mine_hotel.is_mine:
        raise HTTPException(status_code=400, detail="只能为我方酒店批量匹配当前门店组")

    group_ids = [mine_hotel.id, *mine_hotel.competitor_ids]
    hotels = list(
        (
            await db.execute(
                select(Hotel)
                .options(selectinload(Hotel.platform_mappings))
                .where(Hotel.id.in_(group_ids))
                .order_by(Hotel.is_mine.desc(), Hotel.id)
            )
        ).scalars().all()
    )
    results = [
        await _auto_match_ctrip_for_hotel(db, hotel, city_id=city_id, skip_existing=True)
        for hotel in hotels
    ]
    return HotelPlatformGroupAutoMatchResponse(
        total=len(results),
        matched=sum(1 for item in results if item.matched),
        skipped=sum(1 for item in results if item.message.startswith("已存在")),
        failed=sum(1 for item in results if not item.matched and not item.message.startswith("已存在")),
        results=results,
    )


async def _auto_match_ctrip_for_hotel(
    db: AsyncSession,
    hotel: Hotel,
    city_id: int = 42,
    skip_existing: bool = False,
) -> HotelPlatformAutoMatchResponse:
    existing_stmt = select(HotelPlatformMapping).where(
        HotelPlatformMapping.hotel_id == hotel.id,
        HotelPlatformMapping.platform == "ctrip",
    )
    existing = (await db.execute(existing_stmt)).scalar_one_or_none()
    if skip_existing and existing and existing.hotel_url:
        return HotelPlatformAutoMatchResponse(
            matched=False,
            hotel_id=hotel.id,
            hotel_name=hotel.name,
            mapping=existing,
            candidates=[],
            message="已存在携程 URL，跳过",
        )

    candidates = await search_ctrip_hotel_by_name(hotel.name, city_id=city_id)
    candidate_items = [
        HotelPlatformAutoMatchCandidate(
            hotel_id=item.hotel_id,
            name=item.name,
            url=item.url,
            score=round(item.score, 3),
        )
        for item in candidates
    ]
    match = best_ctrip_match(candidates)
    if match is None:
        return HotelPlatformAutoMatchResponse(
            matched=False,
            hotel_id=hotel.id,
            hotel_name=hotel.name,
            candidates=candidate_items,
            message="未找到足够匹配的携程酒店，请手动粘贴 URL 或调整酒店名称后重试",
        )

    duplicate_stmt = select(HotelPlatformMapping).where(
        HotelPlatformMapping.platform == "ctrip",
        HotelPlatformMapping.platform_hotel_id == match.hotel_id,
        HotelPlatformMapping.hotel_id != hotel.id,
    )
    duplicate = (await db.execute(duplicate_stmt)).scalar_one_or_none()
    if duplicate:
        return HotelPlatformAutoMatchResponse(
            matched=False,
            hotel_id=hotel.id,
            hotel_name=hotel.name,
            candidates=candidate_items,
            message="匹配到的携程酒店已绑定到其他酒店，请检查名称或手动处理",
        )

    mapping = existing
    if not mapping:
        mapping = HotelPlatformMapping(hotel_id=hotel.id, platform="ctrip", platform_hotel_id=match.hotel_id)
        db.add(mapping)

    mapping.platform_hotel_id = match.hotel_id
    mapping.hotel_url = match.url
    if not mapping.default_room_name:
        mapping.default_room_name = None

    await db.commit()
    await db.refresh(mapping)
    return HotelPlatformAutoMatchResponse(
        matched=True,
        hotel_id=hotel.id,
        hotel_name=hotel.name,
        mapping=mapping,
        candidates=candidate_items,
        message=f"已匹配携程：{match.name}",
    )


async def _load_hotel(db: AsyncSession, hotel_id: int) -> Hotel:
    stmt = (
        select(Hotel)
        .options(selectinload(Hotel.platform_mappings), selectinload(Hotel.competitor_links))
        .where(Hotel.id == hotel_id)
    )
    hotel = (await db.execute(stmt)).scalar_one()
    return hotel


async def _ensure_default_competitor_links(db: AsyncSession):
    links_count = (await db.execute(select(func.count()).select_from(HotelCompetitor))).scalar_one()
    if links_count:
        return

    hotels = list((await db.execute(select(Hotel).order_by(Hotel.is_mine.desc(), Hotel.id))).scalars().all())
    my_hotels = [hotel for hotel in hotels if hotel.is_mine]
    competitors = [hotel for hotel in hotels if not hotel.is_mine]
    if len(my_hotels) != 1 or not competitors:
        return

    for competitor in competitors[:5]:
        db.add(HotelCompetitor(mine_hotel_id=my_hotels[0].id, competitor_hotel_id=competitor.id))
    await db.commit()
