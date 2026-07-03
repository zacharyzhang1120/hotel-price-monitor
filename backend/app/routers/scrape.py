"""Scrape trigger and status routes."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import (
    CTRIP_STATE_FILE,
    ENABLED_PLATFORMS,
    FUTURE_DAYS,
    PRICE_FALLBACK_MAX_AGE_HOURS,
    REAL_PLATFORMS,
    REPORT_PUSH_ENABLED,
    SCRAPE_CONCURRENCY,
    SCRAPE_FAST_MAPPING_TIMEOUT,
    SCRAPE_GOTO_WAIT_UNTIL,
    SCRAPE_MAPPING_TIMEOUT,
    SCRAPE_PROBE_TIMEOUT,
    SCHEDULER_ENABLED,
    SCRAPE_SCHEDULE_HOURS,
    SCRAPER_MODE,
    SCRAPE_TODAY_FIRST,
    SCHEDULED_SCRAPE_FAST_MAPPING_TIMEOUT,
    SCHEDULED_SCRAPE_RETRY_FAILED_TODAY,
    SCHEDULED_SCRAPE_SCOPE,
    WECOM_WEBHOOK_URL,
)
from app.database import get_db
from app.models import Hotel, ScrapeRun, ScrapeTaskResult
from app.schemas.price import (
    MissingMappingItem,
    SessionStatus,
    ScrapeConfigResponse,
    ScrapeProbeRequest,
    ScrapeProbeResponse,
    ScrapeReadinessResponse,
    ScrapeRunResponse,
    ScrapeTaskEvidenceResponse,
    ScrapeStatusResponse,
    ScrapeTaskResultResponse,
    ScrapeTriggerResponse,
)
from app.services.probe_service import probe_scraper
from app.services.scrape_job import ScrapeAlreadyRunningError, scrape_and_report
from app.services.mapping_utils import validate_platform_hotel_url

router = APIRouter(prefix="/scrape", tags=["scrape"])

TASKS: dict[str, dict[str, Any]] = {}


@router.post("/trigger", response_model=ScrapeTriggerResponse)
async def trigger_scrape(hotel_ids: Optional[str] = None, scope: str = "all"):
    running_task_id = next(
        (task_id for task_id, task in TASKS.items() if task["status"] in {"started", "running"}),
        None,
    )
    if running_task_id:
        return ScrapeTriggerResponse(
            task_id=running_task_id,
            status="running",
            message="已有抓取任务正在运行",
        )

    hotel_id_list = _parse_hotel_ids_param(hotel_ids)

    if scope not in {"today", "future", "all"}:
        raise HTTPException(status_code=400, detail="scope 必须是 today、future 或 all")

    task_id = str(uuid.uuid4())
    TASKS[task_id] = {
        "status": "started",
        "progress": "等待执行",
        "batch_id": None,
        "error": None,
        "milestones": [],
        "wall_time_s": None,
        "total_tasks": 0,
        "success_tasks": 0,
        "failed_tasks": 0,
        "completed_tasks": 0,
    }
    asyncio.create_task(_run_scrape_task(task_id, hotel_id_list, scope))
    return ScrapeTriggerResponse(
        task_id=task_id,
        status="started",
        message="抓取任务已启动",
    )


@router.get("/status/{task_id}", response_model=ScrapeStatusResponse)
async def get_scrape_status(task_id: str):
    task = TASKS.get(task_id)
    if not task:
        return ScrapeStatusResponse(status="not_found", error="任务不存在")
    return ScrapeStatusResponse(
        status=task["status"],
        progress=task.get("progress"),
        error=task.get("error"),
        batch_id=task.get("batch_id"),
        milestones=task.get("milestones", []),
        wall_time_s=task.get("wall_time_s"),
        total_tasks=task.get("total_tasks", 0),
        success_tasks=task.get("success_tasks", 0),
        failed_tasks=task.get("failed_tasks", 0),
        completed_tasks=task.get("completed_tasks", 0),
    )


@router.get("/latest", response_model=Optional[ScrapeRunResponse])
async def get_latest_scrape_run(hotel_ids: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    hotel_id_list = _parse_hotel_ids_param(hotel_ids)
    stmt = select(ScrapeRun)
    if hotel_id_list:
        stmt = (
            stmt.join(ScrapeTaskResult, ScrapeTaskResult.batch_id == ScrapeRun.id)
            .where(ScrapeTaskResult.hotel_id.in_(hotel_id_list))
            .distinct()
        )
    stmt = stmt.order_by(desc(ScrapeRun.started_at), desc(ScrapeRun.id)).limit(1)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


@router.get("/runs", response_model=list[ScrapeRunResponse])
async def list_scrape_runs(
    limit: int = 10,
    hotel_ids: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    safe_limit = max(1, min(limit, 50))
    hotel_id_list = _parse_hotel_ids_param(hotel_ids)
    stmt = select(ScrapeRun)
    if hotel_id_list:
        stmt = (
            stmt.join(ScrapeTaskResult, ScrapeTaskResult.batch_id == ScrapeRun.id)
            .where(ScrapeTaskResult.hotel_id.in_(hotel_id_list))
            .distinct()
        )
    stmt = stmt.order_by(desc(ScrapeRun.started_at), desc(ScrapeRun.id)).limit(safe_limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/runs/{batch_id}/tasks", response_model=list[ScrapeTaskResultResponse])
async def list_scrape_task_results(batch_id: int, db: AsyncSession = Depends(get_db)):
    stmt = (
        select(ScrapeTaskResult)
        .where(ScrapeTaskResult.batch_id == batch_id)
        .order_by(ScrapeTaskResult.hotel_id, ScrapeTaskResult.platform)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/runs/{batch_id}/tasks/{task_result_id}/evidence", response_model=ScrapeTaskEvidenceResponse)
async def get_scrape_task_evidence(
    batch_id: int,
    task_result_id: int,
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(ScrapeTaskResult)
        .where(ScrapeTaskResult.batch_id == batch_id)
        .where(ScrapeTaskResult.id == task_result_id)
    )
    result = await db.execute(stmt)
    task_result = result.scalar_one_or_none()
    if task_result is None:
        raise HTTPException(status_code=404, detail="任务明细不存在")
    return ScrapeTaskEvidenceResponse(
        id=task_result.id,
        batch_id=task_result.batch_id,
        hotel_id=task_result.hotel_id,
        hotel_name=task_result.hotel_name,
        platform=task_result.platform,
        status=task_result.status,
        evidence=task_result.evidence,
    )


@router.get("/config", response_model=ScrapeConfigResponse)
async def get_scrape_config():
    return ScrapeConfigResponse(
        scraper_mode=SCRAPER_MODE,
        enabled_platforms=ENABLED_PLATFORMS,
        real_platforms=REAL_PLATFORMS,
        scheduler_enabled=SCHEDULER_ENABLED,
        schedule_hours=SCRAPE_SCHEDULE_HOURS,
        scheduled_scrape_scope=SCHEDULED_SCRAPE_SCOPE,
        future_days=FUTURE_DAYS,
        scrape_concurrency=SCRAPE_CONCURRENCY,
        scrape_goto_wait_until=SCRAPE_GOTO_WAIT_UNTIL,
        scrape_mapping_timeout=SCRAPE_MAPPING_TIMEOUT,
        scrape_probe_timeout=SCRAPE_PROBE_TIMEOUT,
        scrape_today_first=SCRAPE_TODAY_FIRST,
        scrape_fast_mapping_timeout=SCRAPE_FAST_MAPPING_TIMEOUT,
        scheduled_scrape_fast_mapping_timeout=SCHEDULED_SCRAPE_FAST_MAPPING_TIMEOUT,
        scheduled_scrape_retry_failed_today=SCHEDULED_SCRAPE_RETRY_FAILED_TODAY,
        price_fallback_max_age_hours=PRICE_FALLBACK_MAX_AGE_HOURS,
        report_push_enabled=REPORT_PUSH_ENABLED,
        wecom_webhook_configured=bool(WECOM_WEBHOOK_URL),
    )


@router.get("/readiness", response_model=ScrapeReadinessResponse)
async def get_scrape_readiness(hotel_ids: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    hotel_id_list = _parse_hotel_ids_param(hotel_ids)
    stmt = select(Hotel).options(selectinload(Hotel.platform_mappings)).order_by(Hotel.is_mine.desc(), Hotel.id)
    if hotel_id_list:
        stmt = stmt.where(Hotel.id.in_(hotel_id_list))
    result = await db.execute(stmt)
    hotels = list(result.scalars().all())

    active_real_platforms = _active_real_platforms()
    missing_enabled: list[MissingMappingItem] = []
    missing_real_urls: list[MissingMappingItem] = []
    invalid_real_urls: list[MissingMappingItem] = []
    mappings_total = 0
    mappings_with_url = 0

    for hotel in hotels:
        mappings = {mapping.platform: mapping for mapping in hotel.platform_mappings}
        mappings_total += len(mappings)
        mappings_with_url += sum(1 for mapping in mappings.values() if mapping.hotel_url)
        for platform in ENABLED_PLATFORMS:
            mapping = mappings.get(platform)
            if not mapping:
                missing_enabled.append(
                    MissingMappingItem(hotel_id=hotel.id, hotel_name=hotel.name, platform=platform, reason="缺少平台映射")
                )
                if platform in active_real_platforms:
                    missing_real_urls.append(
                        MissingMappingItem(hotel_id=hotel.id, hotel_name=hotel.name, platform=platform, reason="缺少平台映射")
                    )
                continue
            if platform in active_real_platforms and not mapping.hotel_url:
                missing_real_urls.append(
                    MissingMappingItem(hotel_id=hotel.id, hotel_name=hotel.name, platform=platform, reason="缺少 URL")
                )
            elif platform in active_real_platforms:
                invalid_reason = validate_platform_hotel_url(platform, mapping.hotel_url)
                if invalid_reason:
                    invalid_real_urls.append(
                        MissingMappingItem(
                            hotel_id=hotel.id,
                            hotel_name=hotel.name,
                            platform=platform,
                            reason=invalid_reason,
                        )
                    )

    my_hotels_count = sum(1 for hotel in hotels if hotel.is_mine)
    competitors_count = sum(1 for hotel in hotels if not hotel.is_mine)

    # Check platform sessions
    sessions = _check_platform_sessions()

    ready_for_mock = bool(hotels) and my_hotels_count >= 1 and competitors_count >= 1 and not missing_enabled
    ready_for_real = (
        ready_for_mock
        and bool(active_real_platforms)
        and not missing_real_urls
        and not invalid_real_urls
    )
    # If real mode requires Ctrip, session must exist
    if "ctrip" in active_real_platforms:
        ctrip_session = next((s for s in sessions if s.platform == "ctrip"), None)
        if ctrip_session and not ctrip_session.has_session:
            ready_for_real = False

    messages = _readiness_messages(
        ready_for_mock,
        ready_for_real,
        active_real_platforms,
        missing_enabled,
        missing_real_urls,
        invalid_real_urls,
        sessions,
    )

    return ScrapeReadinessResponse(
        scraper_mode=SCRAPER_MODE,
        enabled_platforms=ENABLED_PLATFORMS,
        active_real_platforms=active_real_platforms,
        hotels_total=len(hotels),
        my_hotels_count=my_hotels_count,
        competitors_count=competitors_count,
        mappings_total=mappings_total,
        mappings_with_url=mappings_with_url,
        missing_enabled_mappings=missing_enabled,
        missing_real_urls=missing_real_urls,
        invalid_real_urls=invalid_real_urls,
        ready_for_mock=ready_for_mock,
        ready_for_real=ready_for_real,
        messages=messages,
        sessions=sessions,
    )


@router.post("/login")
async def launch_ctrip_login():
    """Launch visible browser for Ctrip login, auto-save session on completion."""
    import json as _json
    from playwright.async_api import async_playwright

    if "ctrip" not in ENABLED_PLATFORMS:
        return {"success": False, "message": "Ctrip platform not enabled"}

    HOTEL_URL = "https://hotels.ctrip.com/hotels/detail/?cityEnName=Haikou&cityId=42&hotelId=436575"

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=False)
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
            await page.goto(HOTEL_URL, wait_until="domcontentloaded", timeout=30000)

            # Wait for user to complete login (detect URL change away from passport)
            for _ in range(60):  # max 2 minutes
                await asyncio.sleep(2)
                current_url = page.url
                if "passport.ctrip.com" not in current_url and "login" not in current_url.lower():
                    # User logged in! Wait a bit for page to settle
                    await page.wait_for_timeout(3000)
                    break
            else:
                await browser.close()
                return {"success": False, "message": "登录超时（2分钟），请重试"}

            # Save session
            state = await context.storage_state()
            CTRIP_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            CTRIP_STATE_FILE.write_text(_json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

            # Verify
            has_price = False
            try:
                text = await page.locator("body").inner_text(timeout=5000)
                has_price = "¥" in text or "￥" in text
            except Exception:
                pass

            await browser.close()

            return {
                "success": True,
                "message": "携程登录成功" + ("，价格可见" if has_price else "（但未检测到价格，可重试）"),
                "cookies": len(state.get("cookies", [])),
                "has_prices": has_price,
            }
    except Exception as e:
        return {"success": False, "message": f"登录失败: {str(e)[:100]}"}


@router.post("/probe", response_model=ScrapeProbeResponse)
async def probe_platform_url(payload: ScrapeProbeRequest):
    if payload.platform not in ENABLED_PLATFORMS:
        return ScrapeProbeResponse(
            success=False,
            platform=payload.platform,
            mode=payload.mode,
            points=[],
            error="平台未启用或不支持",
        )
    result = await probe_scraper(
        platform=payload.platform,
        hotel_url=payload.hotel_url,
        check_in_date=payload.check_in_date,
        room_name=payload.room_name,
        mode=payload.mode,
    )
    return ScrapeProbeResponse(**result)


async def _run_scrape_task(task_id: str, hotel_ids: list[int] | None = None, scope: str = "all"):
    import time as _time
    _t0 = _time.monotonic()
    TASKS[task_id]["status"] = "running"
    TASKS[task_id]["progress"] = "抓取中"
    TASKS[task_id]["milestones"] = []
    try:
        def update_progress(event: dict[str, Any]) -> None:
            elapsed = _time.monotonic() - _t0
            TASKS[task_id]["progress"] = event["message"]
            if event.get("total"):
                TASKS[task_id]["total_tasks"] = event.get("overall_total") or event["total"]
            if event["type"] in {"success", "timeout", "failed"}:
                TASKS[task_id]["milestones"].append({
                    "type": event["type"],
                    "elapsed_s": round(elapsed, 1),
                    "message": event["message"],
                    "hotel_id": event.get("hotel_id"),
                    "hotel_name": event.get("hotel_name"),
                    "platform": event.get("platform"),
                })
                success_tasks = sum(1 for item in TASKS[task_id]["milestones"] if item["type"] == "success")
                failed_tasks = sum(1 for item in TASKS[task_id]["milestones"] if item["type"] in {"timeout", "failed"})
                TASKS[task_id]["success_tasks"] = success_tasks
                TASKS[task_id]["failed_tasks"] = failed_tasks
                TASKS[task_id]["completed_tasks"] = success_tasks + failed_tasks

        stats = await scrape_and_report(
            trigger_type="manual",
            progress_callback=update_progress,
            hotel_ids=hotel_ids or [],
            scope=scope,
        )
        TASKS[task_id]["status"] = "completed" if stats["failed"] == 0 else "partial_success"
        TASKS[task_id]["progress"] = f"{stats['success']}/{stats['total']}"
        TASKS[task_id]["batch_id"] = stats["batch_id"]
        TASKS[task_id]["error"] = "\n".join(stats["errors"]) if stats["errors"] else None
        TASKS[task_id]["wall_time_s"] = round(_time.monotonic() - _t0, 1)
        TASKS[task_id]["total_tasks"] = stats["total"]
        TASKS[task_id]["success_tasks"] = stats["success"]
        TASKS[task_id]["failed_tasks"] = stats["failed"]
        TASKS[task_id]["completed_tasks"] = stats["success"] + stats["failed"]
    except ScrapeAlreadyRunningError as exc:
        TASKS[task_id]["status"] = "failed"
        TASKS[task_id]["progress"] = "已有任务运行中"
        TASKS[task_id]["error"] = str(exc)
        TASKS[task_id]["wall_time_s"] = round(_time.monotonic() - _t0, 1)
    except Exception as exc:
        TASKS[task_id]["status"] = "failed"
        TASKS[task_id]["error"] = str(exc)
        TASKS[task_id]["wall_time_s"] = round(_time.monotonic() - _t0, 1)


def _active_real_platforms() -> list[str]:
    if SCRAPER_MODE == "real":
        return list(ENABLED_PLATFORMS)
    if SCRAPER_MODE == "mixed":
        return [platform for platform in REAL_PLATFORMS if platform in ENABLED_PLATFORMS]
    return []


def _parse_hotel_ids_param(hotel_ids: Optional[str]) -> Optional[list[int]]:
    if hotel_ids is None:
        return None
    try:
        hotel_id_list = [int(item.strip()) for item in hotel_ids.split(",") if item.strip()]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="hotel_ids 必须是逗号分隔的数字") from exc
    if not hotel_id_list or any(item <= 0 for item in hotel_id_list):
        raise HTTPException(status_code=400, detail="hotel_ids 必须至少包含一个有效酒店 ID")
    return hotel_id_list


def _check_platform_sessions() -> list[SessionStatus]:
    """Check which platforms have saved login sessions."""
    sessions: list[SessionStatus] = []
    if "ctrip" in ENABLED_PLATFORMS:
        if CTRIP_STATE_FILE.exists():
            try:
                import json
                state = json.loads(CTRIP_STATE_FILE.read_text(encoding="utf-8"))
                cookie_count = len(state.get("cookies", []))
                sessions.append(SessionStatus(
                    platform="ctrip", has_session=True, cookie_count=cookie_count
                ))
            except Exception:
                sessions.append(SessionStatus(
                    platform="ctrip", has_session=False, cookie_count=0
                ))
        else:
            sessions.append(SessionStatus(
                platform="ctrip", has_session=False, cookie_count=0
            ))
    return sessions


def _readiness_messages(
    ready_for_mock: bool,
    ready_for_real: bool,
    active_real_platforms: list[str],
    missing_enabled: list[MissingMappingItem],
    missing_real_urls: list[MissingMappingItem],
    invalid_real_urls: list[MissingMappingItem],
    sessions: list[SessionStatus],
) -> list[str]:
    messages: list[str] = []
    if ready_for_mock:
        messages.append("Mock MVP 数据链路已具备测试条件")
    else:
        messages.append("Mock MVP 还缺少酒店或平台映射")
    if missing_enabled:
        messages.append(f"有 {len(missing_enabled)} 个启用平台映射缺失")
    if not active_real_platforms:
        messages.append("当前未启用真实抓取平台")
    elif ready_for_real:
        messages.append("真实抓取 URL 配置已齐，可逐个平台探测")
    else:
        messages.append(f"真实抓取还缺少 {len(missing_real_urls)} 个平台 URL，且有 {len(invalid_real_urls)} 个 URL 形态异常")

    # Session status messages
    for s in sessions:
        if s.platform == "ctrip" and not s.has_session:
            messages.append("携程未登录：请运行 python3 scripts/login_ctrip.py 扫码登录")
        elif s.platform == "ctrip" and s.has_session:
            messages.append(f"携程已登录 ({s.cookie_count} cookies)")

    return messages
