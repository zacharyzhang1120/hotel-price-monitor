import asyncio
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from app.database import async_session, init_db
from app.main import app
from app.models import Hotel, HotelCompetitor, HotelPlatformMapping, PriceRecord, ScrapeRun, ScrapeTaskResult
from app.routers import scheduler as scheduler_router
from app.services import scrape_manager as scrape_manager_module
from app.services import scheduler as scheduler_service
from app.services.ctrip_search import CtripHotelCandidate
from app.services.hotel_groups import load_active_group_hotel_ids
from app.services.scrape_manager import ScraperManager
from app.services.scraper.base import PricePoint
from app.services.startup_cleanup import mark_stale_running_scrape_runs


def setup_module():
    asyncio.run(reset_database())


async def reset_database():
    await init_db()
    async with async_session() as session:
        for model in (PriceRecord, ScrapeTaskResult, ScrapeRun, HotelPlatformMapping, HotelCompetitor, Hotel):
            await session.execute(delete(model))
        my_hotel = Hotel(name="测试我方酒店", is_mine=True, distance_km=0)
        competitors = [
            Hotel(name=f"测试竞对{i}", is_mine=False, distance_km=float(i) / 10)
            for i in range(1, 6)
        ]
        session.add(my_hotel)
        session.add_all(competitors)
        await session.flush()
        for hotel in [my_hotel, *competitors]:
            for platform in ("ctrip",):
                session.add(
                    HotelPlatformMapping(
                        hotel_id=hotel.id,
                        platform=platform,
                        platform_hotel_id=f"test_{hotel.id}_{platform}",
                        hotel_url=f"https://example.com/{hotel.id}/{platform}",
                        default_room_name="测试大床房",
                    )
                )
        await session.commit()


def test_mvp_api_flow():
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get("/").json()["api_prefix"] == "/api/v1"

        hotels = client.get("/api/v1/hotels").json()
        assert len(hotels) == 6
        assert sum(len(hotel["platform_mappings"]) for hotel in hotels) == 6
        my_hotel = next(hotel for hotel in hotels if hotel["is_mine"])
        assert len(my_hotel["competitor_ids"]) == 5

        scrape_config = client.get("/api/v1/scrape/config").json()
        assert scrape_config["scraper_mode"] == "mock"
        assert scrape_config["enabled_platforms"] == ["ctrip"]
        assert scrape_config["report_push_enabled"] is False
        readiness = client.get("/api/v1/scrape/readiness").json()
        assert readiness["ready_for_mock"] is True
        assert readiness["ready_for_real"] is False
        assert readiness["active_real_platforms"] == []
        assert readiness["hotels_total"] == 6
        assert readiness["mappings_total"] == 6
        assert readiness["missing_enabled_mappings"] == []
        scheduler_status = client.get("/api/v1/scheduler/status").json()
        assert scheduler_status["enabled"] is False
        assert scheduler_status["running"] is False
        assert scheduler_status["schedule_hours"] == [8, 11, 14, 17, 20, 23]
        assert scheduler_status["scheduled_target_hotel_count"] == 6
        assert scheduler_status["scheduler_health"]["status"] == "disabled"

        trigger = client.post("/api/v1/scrape/trigger").json()
        status = wait_for_task(client, trigger["task_id"])
        assert status["status"] == "completed"
        assert status["progress"] == "12/12"
        assert status["total_tasks"] == 12
        assert status["success_tasks"] == 12
        assert status["failed_tasks"] == 0
        assert status["completed_tasks"] == 12
        assert status["batch_id"]

        runs = client.get("/api/v1/scrape/runs?limit=3").json()
        assert runs[0]["id"] == status["batch_id"]
        assert runs[0]["total_tasks"] == 12
        assert runs[0]["success_tasks"] == 12
        assert runs[0]["failed_tasks"] == 0
        assert runs[0]["wall_time_s"] is not None
        assert runs[0]["wall_time_s"] >= 0
        task_results = client.get(f"/api/v1/scrape/runs/{status['batch_id']}/tasks").json()
        assert len(task_results) == 12
        assert {item["status"] for item in task_results} == {"success"}
        assert all(item["has_evidence"] for item in task_results)
        records_set = {item["records_count"] for item in task_results}
        assert records_set == {1, 7}
        evidence = client.get(
            f"/api/v1/scrape/runs/{status['batch_id']}/tasks/{task_results[0]['id']}/evidence"
        ).json()
        assert evidence["evidence"]["hotel_url"].startswith("https://example.com/")
        assert evidence["evidence"]["points"][0]["selected"]["price"] is not None

        today = date.today().isoformat()
        probe = client.post(
            "/api/v1/scrape/probe",
            json={
                "platform": "ctrip",
                "hotel_url": "https://hotels.ctrip.com/hotel/1234567.html",
                "check_in_date": today,
                "room_name": "测试大床房",
                "mode": "mock",
            },
        ).json()
        assert probe["success"] is True
        assert probe["points"][0]["check_in_date"] == today
        assert probe["points"][0]["cheapest_price"] is not None

        calendar = client.get(f"/api/v1/prices/calendar?date={today}&days=8").json()
        assert len(calendar["data"]) == 48
        assert calendar["data"][0]["cheapest_room"]
        assert calendar["data"][0]["cheapest_price"] is not None

        competitor = next(item for item in calendar["data"] if not item["is_mine"])
        trend = client.get(
            "/api/v1/prices/trend",
            params={"hotel_id": competitor["hotel_id"], "check_in_date": today},
        ).json()
        assert len(trend["data"]) == 1
        assert {item["platform"] for item in trend["data"]} == {"ctrip"}

        report = client.post("/api/v1/reports/generate", params={"format": "json", "date": today}).json()
        assert report["my_hotel"]["baseline_price"] is not None
        assert len(report["competitors"]) == 5

        text = client.post("/api/v1/reports/generate", params={"format": "wechat_text", "date": today}).text
        assert "竞对价格日报" in text
        assert "低于我方最低价" in text or "暂无竞对低于我方最低价" in text

        latest_text = client.get(
            "/api/v1/reports/latest",
            params={"format": "wechat_text", "date": today},
        ).text
        assert "竞对价格日报" in latest_text

        backup = client.post("/api/v1/backups/create").json()
        assert backup["filename"].startswith("hotel_prices_")
        backups = client.get("/api/v1/backups").json()
        assert any(item["filename"] == backup["filename"] for item in backups["data"])


def test_scrape_readiness_can_be_scoped_to_current_group():
    with TestClient(app) as client:
        hotels = client.get("/api/v1/hotels").json()
        current_group_ids = [hotel["id"] for hotel in hotels]
        extra = client.post(
            "/api/v1/hotels",
            json={"name": "未加入当前组酒店", "is_mine": False},
        ).json()

        global_readiness = client.get("/api/v1/scrape/readiness").json()
        scoped_readiness = client.get(
            f"/api/v1/scrape/readiness?hotel_ids={','.join(str(item) for item in current_group_ids)}"
        ).json()

        assert global_readiness["hotels_total"] == len(current_group_ids) + 1
        assert global_readiness["ready_for_mock"] is False
        assert global_readiness["missing_enabled_mappings"]
        assert scoped_readiness["hotels_total"] == len(current_group_ids)
        assert scoped_readiness["ready_for_mock"] is True
        assert scoped_readiness["missing_enabled_mappings"] == []

        delete_response = client.delete(f"/api/v1/hotels/{extra['id']}").json()
        assert delete_response["deleted"] is True


def test_startup_cleanup_marks_stale_running_scrape_runs_failed():
    async def run():
        async with async_session() as session:
            scrape_run = ScrapeRun(trigger_type="manual", status="running", total_tasks=1)
            partial_run = ScrapeRun(trigger_type="scheduled", status="partial_success", total_tasks=2, success_tasks=1)
            session.add(scrape_run)
            session.add(partial_run)
            await session.commit()
            batch_id = scrape_run.id
            partial_batch_id = partial_run.id

        cleaned = await mark_stale_running_scrape_runs()

        async with async_session() as session:
            refreshed = await session.get(ScrapeRun, batch_id)
            partial_refreshed = await session.get(ScrapeRun, partial_batch_id)
            assert cleaned >= 1
            assert refreshed is not None
            assert refreshed.status == "failed"
            assert refreshed.finished_at is not None
            assert "服务重启" in (refreshed.error_summary or "")
            assert partial_refreshed is not None
            assert partial_refreshed.status == "partial_success"
            assert partial_refreshed.finished_at is not None
            assert "服务重启" in (partial_refreshed.error_summary or "")

    asyncio.run(run())


def test_scheduler_status_falls_back_to_latest_scheduled_run(monkeypatch):
    async def create_run():
        async with async_session() as session:
            scrape_run = ScrapeRun(
                trigger_type="scheduled",
                status="success",
                total_tasks=6,
                success_tasks=6,
                failed_tasks=0,
                finished_at=datetime.utcnow(),
            )
            session.add(scrape_run)
            await session.commit()
            return scrape_run.id

    batch_id = asyncio.run(create_run())
    monkeypatch.setattr(scheduler_service, "_last_scheduler_event", None)

    with TestClient(app) as client:
        status = client.get("/api/v1/scheduler/status").json()

    assert status["last_scheduler_event"]["type"] == "scrape"
    assert status["last_scheduler_event"]["batch_id"] == batch_id
    assert status["last_scheduler_event"]["message"] == "最近定时抓取 6/6，目标 6 家"
    assert status["scheduled_target_hotel_count"] == 6


def test_scheduler_status_treats_incremental_partial_run_as_running(monkeypatch):
    async def create_incremental_run():
        async with async_session() as session:
            hotel = (await session.execute(select(Hotel).order_by(Hotel.id).limit(1))).scalar_one()
            started_at = datetime.utcnow() + timedelta(seconds=10)
            scrape_run = ScrapeRun(
                trigger_type="scheduled",
                status="partial_success",
                started_at=started_at,
                finished_at=None,
                total_tasks=6,
                success_tasks=1,
                failed_tasks=0,
            )
            session.add(scrape_run)
            await session.flush()
            session.add(
                ScrapeTaskResult(
                    batch_id=scrape_run.id,
                    hotel_id=hotel.id,
                    hotel_name=hotel.name,
                    platform="ctrip",
                    status="success",
                    records_count=1,
                    started_at=started_at,
                    finished_at=datetime.utcnow(),
                )
            )
            await session.commit()
            return scrape_run.id

    batch_id = asyncio.run(create_incremental_run())
    monkeypatch.setattr(scheduler_router, "SCHEDULER_ENABLED", True)

    async def run():
        async with async_session() as session:
            health = await scheduler_router._scheduler_health(session, {"running": True}, 6)
            event = await scheduler_router._latest_scheduled_scrape_event(session, 6)
            await session.execute(delete(ScrapeTaskResult).where(ScrapeTaskResult.batch_id == batch_id))
            await session.execute(delete(ScrapeRun).where(ScrapeRun.id == batch_id))
            await session.commit()
            return health, event

    health, event = asyncio.run(run())
    assert health["status"] == "running"
    assert health["latest_scheduled_batch_id"] == batch_id
    assert event["batch_id"] == batch_id
    assert event["target_hotel_count"] == 6
    assert event["message"] == "最近定时抓取 1/6，目标 6 家"


def test_calendar_current_batch_is_scoped_by_requested_hotels():
    async def create_scoped_runs():
        async with async_session() as session:
            first_hotel = Hotel(name="批次范围测试A", is_mine=False)
            second_hotel = Hotel(name="批次范围测试B", is_mine=False)
            session.add_all([first_hotel, second_hotel])
            await session.flush()
            session.add_all(
                [
                    HotelPlatformMapping(
                        hotel_id=first_hotel.id,
                        platform="ctrip",
                        platform_hotel_id=f"scope_{first_hotel.id}",
                        hotel_url=f"https://example.com/scope/{first_hotel.id}",
                    ),
                    HotelPlatformMapping(
                        hotel_id=second_hotel.id,
                        platform="ctrip",
                        platform_hotel_id=f"scope_{second_hotel.id}",
                        hotel_url=f"https://example.com/scope/{second_hotel.id}",
                    ),
                ]
            )
            today = date.today()
            older = datetime.utcnow() - timedelta(minutes=10)
            newer = datetime.utcnow()

            first_run = ScrapeRun(
                trigger_type="manual",
                status="success",
                started_at=older,
                finished_at=older,
                total_tasks=1,
                success_tasks=1,
                failed_tasks=0,
            )
            second_run = ScrapeRun(
                trigger_type="manual",
                status="success",
                started_at=newer,
                finished_at=newer,
                total_tasks=1,
                success_tasks=1,
                failed_tasks=0,
            )
            session.add_all([first_run, second_run])
            await session.flush()
            session.add_all(
                [
                    PriceRecord(
                        batch_id=first_run.id,
                        hotel_id=first_hotel.id,
                        platform="ctrip",
                        check_in_date=today,
                        cheapest_room="A房型",
                        cheapest_price=100,
                        scraped_at=older,
                    ),
                    PriceRecord(
                        batch_id=second_run.id,
                        hotel_id=second_hotel.id,
                        platform="ctrip",
                        check_in_date=today,
                        cheapest_room="B房型",
                        cheapest_price=200,
                        scraped_at=newer,
                    ),
                ]
            )
            await session.commit()
            return first_hotel.id, second_hotel.id, first_run.id, second_run.id, today.isoformat()

    hotel_id, second_hotel_id, expected_batch_id, second_batch_id, today = asyncio.run(create_scoped_runs())

    with TestClient(app) as client:
        calendar = client.get(f"/api/v1/prices/calendar?date={today}&days=1&hotel_ids={hotel_id}").json()

    item = calendar["data"][0]
    assert item["hotel_id"] == hotel_id
    assert item["batch_id"] == expected_batch_id
    assert item["is_current_batch"] is True
    assert item["is_fallback"] is False

    async def cleanup():
        async with async_session() as session:
            hotel_ids = [hotel_id, second_hotel_id]
            await session.execute(delete(PriceRecord).where(PriceRecord.hotel_id.in_(hotel_ids)))
            await session.execute(delete(HotelPlatformMapping).where(HotelPlatformMapping.hotel_id.in_(hotel_ids)))
            await session.execute(delete(Hotel).where(Hotel.id.in_(hotel_ids)))
            await session.execute(delete(ScrapeRun).where(ScrapeRun.id.in_([expected_batch_id, second_batch_id])))
            await session.commit()

    asyncio.run(cleanup())


def test_calendar_ignores_stale_fallback_prices():
    async def create_stale_fallback_case():
        async with async_session() as session:
            fresh_hotel = Hotel(name="兜底窗口新价格酒店", is_mine=False)
            stale_hotel = Hotel(name="兜底窗口旧价格酒店", is_mine=False)
            session.add_all([fresh_hotel, stale_hotel])
            await session.flush()
            session.add_all(
                [
                    HotelPlatformMapping(
                        hotel_id=fresh_hotel.id,
                        platform="ctrip",
                        platform_hotel_id=f"fresh_{fresh_hotel.id}",
                        hotel_url=f"https://example.com/fresh/{fresh_hotel.id}",
                    ),
                    HotelPlatformMapping(
                        hotel_id=stale_hotel.id,
                        platform="ctrip",
                        platform_hotel_id=f"stale_{stale_hotel.id}",
                        hotel_url=f"https://example.com/stale/{stale_hotel.id}",
                    ),
                ]
            )
            today = date.today()
            fresh_time = datetime.utcnow()
            stale_time = fresh_time - timedelta(days=2)
            fresh_run = ScrapeRun(
                trigger_type="scheduled",
                status="partial_success",
                started_at=fresh_time,
                finished_at=fresh_time,
                total_tasks=2,
                success_tasks=1,
                failed_tasks=1,
            )
            stale_run = ScrapeRun(
                trigger_type="manual",
                status="success",
                started_at=stale_time,
                finished_at=stale_time,
                total_tasks=1,
                success_tasks=1,
                failed_tasks=0,
            )
            session.add_all([stale_run, fresh_run])
            await session.flush()
            session.add_all(
                [
                    ScrapeTaskResult(
                        batch_id=fresh_run.id,
                        hotel_id=fresh_hotel.id,
                        hotel_name=fresh_hotel.name,
                        platform="ctrip",
                        status="success",
                        records_count=1,
                        started_at=fresh_time,
                        finished_at=fresh_time,
                    ),
                    ScrapeTaskResult(
                        batch_id=fresh_run.id,
                        hotel_id=stale_hotel.id,
                        hotel_name=stale_hotel.name,
                        platform="ctrip",
                        status="failed",
                        records_count=0,
                        error_message="兜底窗口旧价格酒店/ctrip: 抓取超过 120 秒，已自动中止",
                        started_at=fresh_time,
                        finished_at=fresh_time,
                    ),
                    PriceRecord(
                        batch_id=fresh_run.id,
                        hotel_id=fresh_hotel.id,
                        platform="ctrip",
                        check_in_date=today,
                        cheapest_room="新价格房",
                        cheapest_price=200,
                        scraped_at=fresh_time,
                    ),
                    PriceRecord(
                        batch_id=stale_run.id,
                        hotel_id=stale_hotel.id,
                        platform="ctrip",
                        check_in_date=today,
                        cheapest_room="旧价格房",
                        cheapest_price=100,
                        scraped_at=stale_time,
                    ),
                ]
            )
            await session.commit()
            return fresh_hotel.id, stale_hotel.id, fresh_run.id, stale_run.id, today.isoformat()

    fresh_hotel_id, stale_hotel_id, fresh_batch_id, stale_batch_id, today = asyncio.run(create_stale_fallback_case())

    with TestClient(app) as client:
        calendar = client.get(
            f"/api/v1/prices/calendar?date={today}&days=1&hotel_ids={fresh_hotel_id},{stale_hotel_id}"
        ).json()

    items = {item["hotel_id"]: item for item in calendar["data"]}
    assert items[fresh_hotel_id]["batch_id"] == fresh_batch_id
    assert items[fresh_hotel_id]["is_current_batch"] is True
    assert items[stale_hotel_id]["batch_id"] is None
    assert items[stale_hotel_id]["cheapest_price"] is None
    assert items[stale_hotel_id]["is_fallback"] is False
    assert items[stale_hotel_id]["task_status"] == "failed"
    assert "抓取超过 120 秒" in items[stale_hotel_id]["task_error_message"]

    async def cleanup():
        async with async_session() as session:
            hotel_ids = [fresh_hotel_id, stale_hotel_id]
            await session.execute(delete(ScrapeTaskResult).where(ScrapeTaskResult.batch_id.in_([fresh_batch_id, stale_batch_id])))
            await session.execute(delete(PriceRecord).where(PriceRecord.hotel_id.in_(hotel_ids)))
            await session.execute(delete(HotelPlatformMapping).where(HotelPlatformMapping.hotel_id.in_(hotel_ids)))
            await session.execute(delete(Hotel).where(Hotel.id.in_(hotel_ids)))
            await session.execute(delete(ScrapeRun).where(ScrapeRun.id.in_([fresh_batch_id, stale_batch_id])))
            await session.commit()

    asyncio.run(cleanup())


def test_report_lists_missing_competitors_when_fallback_is_stale():
    async def create_missing_report_case():
        async with async_session() as session:
            mine = Hotel(name="日报缺价我方酒店", is_mine=True)
            competitor = Hotel(name="日报缺价竞对酒店", is_mine=False)
            session.add_all([mine, competitor])
            await session.flush()
            session.add(HotelCompetitor(mine_hotel_id=mine.id, competitor_hotel_id=competitor.id))
            session.add_all(
                [
                    HotelPlatformMapping(
                        hotel_id=mine.id,
                        platform="ctrip",
                        platform_hotel_id=f"report_mine_{mine.id}",
                        hotel_url=f"https://example.com/report/mine/{mine.id}",
                    ),
                    HotelPlatformMapping(
                        hotel_id=competitor.id,
                        platform="ctrip",
                        platform_hotel_id=f"report_competitor_{competitor.id}",
                        hotel_url=f"https://example.com/report/competitor/{competitor.id}",
                    ),
                ]
            )
            today = date.today()
            fresh_time = datetime.utcnow()
            stale_time = fresh_time - timedelta(days=2)
            fresh_run = ScrapeRun(
                trigger_type="scheduled",
                status="partial_success",
                started_at=fresh_time,
                finished_at=fresh_time,
                total_tasks=2,
                success_tasks=1,
                failed_tasks=1,
            )
            stale_run = ScrapeRun(
                trigger_type="manual",
                status="success",
                started_at=stale_time,
                finished_at=stale_time,
                total_tasks=1,
                success_tasks=1,
                failed_tasks=0,
            )
            session.add_all([stale_run, fresh_run])
            await session.flush()
            session.add_all(
                [
                    PriceRecord(
                        batch_id=fresh_run.id,
                        hotel_id=mine.id,
                        platform="ctrip",
                        check_in_date=today,
                        cheapest_room="我方新价格房",
                        cheapest_price=300,
                        scraped_at=fresh_time,
                    ),
                    PriceRecord(
                        batch_id=stale_run.id,
                        hotel_id=competitor.id,
                        platform="ctrip",
                        check_in_date=today,
                        cheapest_room="竞对旧价格房",
                        cheapest_price=100,
                        scraped_at=stale_time,
                    ),
                ]
            )
            await session.commit()
            return mine.id, competitor.id, fresh_run.id, stale_run.id, today.isoformat()

    mine_id, competitor_id, fresh_batch_id, stale_batch_id, today = asyncio.run(create_missing_report_case())

    with TestClient(app) as client:
        report = client.post(
            "/api/v1/reports/generate",
            params={"format": "json", "date": today, "mine_hotel_id": mine_id},
        ).json()
        text = client.post(
            "/api/v1/reports/generate",
            params={"format": "wechat_text", "date": today, "mine_hotel_id": mine_id},
        ).text

    assert report["competitors"] == []
    assert report["missing_competitors"][0]["id"] == competitor_id
    assert "缺价酒店" in text
    assert "日报缺价竞对酒店" in text

    async def cleanup():
        async with async_session() as session:
            hotel_ids = [mine_id, competitor_id]
            await session.execute(
                delete(HotelCompetitor).where(HotelCompetitor.mine_hotel_id == mine_id)
            )
            await session.execute(delete(PriceRecord).where(PriceRecord.hotel_id.in_(hotel_ids)))
            await session.execute(delete(HotelPlatformMapping).where(HotelPlatformMapping.hotel_id.in_(hotel_ids)))
            await session.execute(delete(Hotel).where(Hotel.id.in_(hotel_ids)))
            await session.execute(delete(ScrapeRun).where(ScrapeRun.id.in_([fresh_batch_id, stale_batch_id])))
            await session.commit()

    asyncio.run(cleanup())


def test_scheduler_health_reports_recent_success(monkeypatch):
    async def create_recent_success():
        async with async_session() as session:
            hotels = list((await session.execute(select(Hotel).order_by(Hotel.id).limit(6))).scalars().all())
            finished_local = datetime.now(ZoneInfo("Asia/Shanghai")) + timedelta(minutes=5)
            previous_slot = finished_local - timedelta(minutes=5)
            started_local = finished_local - timedelta(seconds=280)
            finished_at = finished_local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
            started_at = started_local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
            scrape_run = ScrapeRun(
                trigger_type="scheduled",
                status="success",
                started_at=started_at,
                finished_at=finished_at,
                total_tasks=6,
                success_tasks=6,
                failed_tasks=0,
            )
            session.add(scrape_run)
            await session.flush()
            for hotel in hotels:
                session.add(
                    ScrapeTaskResult(
                        batch_id=scrape_run.id,
                        hotel_id=hotel.id,
                        hotel_name=hotel.name,
                        platform="ctrip",
                        status="success",
                        records_count=1,
                        started_at=started_at,
                        finished_at=finished_at,
                    )
                )
            await session.commit()
            return scrape_run.id, previous_slot

    batch_id, previous_slot = asyncio.run(create_recent_success())
    monkeypatch.setattr(scheduler_router, "SCHEDULER_ENABLED", True)
    monkeypatch.setattr(scheduler_router, "_previous_schedule_slot", lambda: previous_slot)

    async def run():
        async with async_session() as session:
            health = await scheduler_router._scheduler_health(session, {"running": True}, 6)
            await session.execute(delete(ScrapeTaskResult).where(ScrapeTaskResult.batch_id == batch_id))
            await session.execute(delete(ScrapeRun).where(ScrapeRun.id == batch_id))
            await session.commit()
            return health

    health = asyncio.run(run())
    assert health["status"] == "ok"
    assert health["last_success_batch_id"] == batch_id
    assert health["last_success_target_hotel_count"] == 6
    assert health["last_success_wall_time_s"] == 280.0
    assert health["last_success_finished_at"].endswith("+08:00")


def test_scheduler_health_warns_when_latest_scheduled_run_failed(monkeypatch):
    async def create_runs():
        async with async_session() as session:
            hotels = list((await session.execute(select(Hotel).order_by(Hotel.id).limit(6))).scalars().all())
            previous_slot = datetime.now(ZoneInfo("Asia/Shanghai")) + timedelta(minutes=10)
            success_finished_local = previous_slot - timedelta(minutes=3)
            failed_finished_local = previous_slot
            success_started = (success_finished_local - timedelta(seconds=260)).astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
            success_finished = success_finished_local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
            failed_started = (failed_finished_local - timedelta(seconds=120)).astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
            failed_finished = failed_finished_local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
            success_run = ScrapeRun(
                trigger_type="scheduled",
                status="success",
                started_at=success_started,
                finished_at=success_finished,
                total_tasks=6,
                success_tasks=6,
                failed_tasks=0,
            )
            failed_run = ScrapeRun(
                trigger_type="scheduled",
                status="partial_success",
                started_at=failed_started,
                finished_at=failed_finished,
                total_tasks=6,
                success_tasks=4,
                failed_tasks=2,
            )
            session.add_all([success_run, failed_run])
            await session.flush()
            for hotel in hotels:
                session.add(
                    ScrapeTaskResult(
                        batch_id=success_run.id,
                        hotel_id=hotel.id,
                        hotel_name=hotel.name,
                        platform="ctrip",
                        status="success",
                        records_count=1,
                        started_at=success_started,
                        finished_at=success_finished,
                    )
                )
            await session.commit()
            return success_run.id, failed_run.id, previous_slot

    success_batch_id, failed_batch_id, previous_slot = asyncio.run(create_runs())
    monkeypatch.setattr(scheduler_router, "SCHEDULER_ENABLED", True)
    monkeypatch.setattr(scheduler_router, "_previous_schedule_slot", lambda: previous_slot)

    async def run():
        async with async_session() as session:
            health = await scheduler_router._scheduler_health(session, {"running": True}, 6)
            await session.execute(
                delete(ScrapeTaskResult).where(ScrapeTaskResult.batch_id.in_([success_batch_id, failed_batch_id]))
            )
            await session.execute(delete(ScrapeRun).where(ScrapeRun.id.in_([success_batch_id, failed_batch_id])))
            await session.commit()
            return health

    health = asyncio.run(run())
    assert health["status"] == "warning"
    assert health["latest_scheduled_batch_id"] == failed_batch_id
    assert health["latest_scheduled_status"] == "partial_success"
    assert health["latest_scheduled_finished_at"].endswith("+08:00")
    assert health["last_success_batch_id"] == success_batch_id


def test_active_group_hotel_ids_exclude_orphan_competitors():
    async def run():
        async with async_session() as session:
            before_ids = await load_active_group_hotel_ids(session)
            orphan = Hotel(name="未加入任何组的竞对", is_mine=False)
            session.add(orphan)
            await session.commit()
            after_ids = await load_active_group_hotel_ids(session)

            assert len(before_ids) == 6
            assert after_ids == before_ids
            assert orphan.id not in after_ids

    asyncio.run(run())


def test_single_hotel_scrape_only_runs_selected_hotel():
    with TestClient(app) as client:
        hotels = client.get("/api/v1/hotels").json()
        target = next(item for item in hotels if not item["is_mine"])

        trigger = client.post("/api/v1/scrape/trigger", params={"hotel_ids": str(target["id"])}).json()
        status = wait_for_task(client, trigger["task_id"])

        assert status["status"] == "completed"
        assert status["progress"] == "2/2"
        assert status["total_tasks"] == 2
        assert status["success_tasks"] == 2
        assert status["failed_tasks"] == 0

        task_results = client.get(f"/api/v1/scrape/runs/{status['batch_id']}/tasks").json()
        assert len(task_results) == 2
        assert {item["hotel_id"] for item in task_results} == {target["id"]}
        assert {item["records_count"] for item in task_results} == {1, 7}

        latest = client.get("/api/v1/scrape/latest", params={"hotel_ids": str(target["id"])}).json()
        runs = client.get("/api/v1/scrape/runs", params={"hotel_ids": str(target["id"]), "limit": 1}).json()
        assert latest["id"] == status["batch_id"]
        assert runs[0]["id"] == status["batch_id"]


def test_manual_trigger_finishes_when_scrape_lock_is_busy(monkeypatch):
    async def fake_scrape_and_report(*args, **kwargs):
        from app.services.scrape_job import ScrapeAlreadyRunningError

        raise ScrapeAlreadyRunningError("已有抓取任务正在运行")

    monkeypatch.setattr("app.routers.scrape.scrape_and_report", fake_scrape_and_report)

    with TestClient(app) as client:
        trigger = client.post("/api/v1/scrape/trigger", params={"hotel_ids": "1", "scope": "today"}).json()
        status = wait_for_task(client, trigger["task_id"])

        assert status["status"] == "failed"
        assert status["progress"] == "已有任务运行中"
        assert status["error"] == "已有抓取任务正在运行"


def test_today_scope_only_scrapes_today_for_selected_hotel():
    with TestClient(app) as client:
        hotels = client.get("/api/v1/hotels").json()
        target = next(item for item in hotels if not item["is_mine"])

        trigger = client.post(
            "/api/v1/scrape/trigger",
            params={"hotel_ids": str(target["id"]), "scope": "today"},
        ).json()
        status = wait_for_task(client, trigger["task_id"])

        assert status["status"] == "completed"
        assert status["progress"] == "1/1"
        assert status["total_tasks"] == 1
        assert status["success_tasks"] == 1
        assert status["failed_tasks"] == 0

        task_results = client.get(f"/api/v1/scrape/runs/{status['batch_id']}/tasks").json()
        assert len(task_results) == 1
        assert task_results[0]["hotel_id"] == target["id"]
        assert task_results[0]["records_count"] == 1


def test_future_scope_only_scrapes_future_dates_for_selected_hotel():
    with TestClient(app) as client:
        hotels = client.get("/api/v1/hotels").json()
        target = next(item for item in hotels if not item["is_mine"])

        trigger = client.post(
            "/api/v1/scrape/trigger",
            params={"hotel_ids": str(target["id"]), "scope": "future"},
        ).json()
        status = wait_for_task(client, trigger["task_id"])

        assert status["status"] == "completed"
        assert status["progress"] == "1/1"
        assert status["total_tasks"] == 1
        assert status["success_tasks"] == 1
        assert status["failed_tasks"] == 0

        task_results = client.get(f"/api/v1/scrape/runs/{status['batch_id']}/tasks").json()
        assert len(task_results) == 1
        assert task_results[0]["hotel_id"] == target["id"]
        assert task_results[0]["records_count"] == 7

        today_records = client.get(
            f"/api/v1/prices/calendar?date={date.today().isoformat()}&days=1&hotel_ids={target['id']}&batch_id={status['batch_id']}"
        ).json()["data"]
        assert today_records[0]["cheapest_price"] is None


def test_invalid_single_hotel_filter_is_rejected():
    with TestClient(app) as client:
        response = client.post("/api/v1/scrape/trigger", params={"hotel_ids": "abc"})
        assert response.status_code == 400
        assert response.json()["detail"] == "hotel_ids 必须是逗号分隔的数字"


def test_invalid_scrape_scope_is_rejected():
    with TestClient(app) as client:
        response = client.post("/api/v1/scrape/trigger", params={"scope": "bad"})
        assert response.status_code == 400
        assert response.json()["detail"] == "scope 必须是 today、future 或 all"


def test_empty_price_points_are_failed_and_not_written(monkeypatch):
    asyncio.run(_assert_empty_price_points_are_failed_and_not_written(monkeypatch))


async def _assert_empty_price_points_are_failed_and_not_written(monkeypatch):
    async with async_session() as session:
        manager = ScraperManager(session)

        async def fake_scrape_mapping(mapping, check_in_dates, batch_id):
            return {
                "ok": True,
                "hotel_id": mapping.hotel_id,
                "hotel_name": mapping.hotel.name,
                "platform": mapping.platform,
                "points": [
                    PricePoint(
                        check_in_date=check_in_dates[0],
                        cheapest_room=None,
                        cheapest_price=None,
                    )
                ],
                "started_at": datetime.utcnow(),
                "finished_at": datetime.utcnow(),
            }

        monkeypatch.setattr(manager, "_scrape_mapping", fake_scrape_mapping)
        stats = await manager.scrape_all(trigger_type="manual")

        assert stats["total"] == 12
        assert stats["success"] == 0
        assert stats["failed"] == 12
        assert stats["status"] == "failed"

        task_count = (
            await session.execute(
                select(func.count())
                .select_from(ScrapeTaskResult)
                .where(ScrapeTaskResult.batch_id == stats["batch_id"])
                .where(ScrapeTaskResult.status == "failed")
            )
        ).scalar_one()
        price_count = (
            await session.execute(
                select(func.count())
                .select_from(PriceRecord)
                .where(PriceRecord.batch_id == stats["batch_id"])
            )
        ).scalar_one()

        assert task_count == 12
        assert price_count == 0


def test_today_timeout_is_retried_after_future_phase(monkeypatch):
    asyncio.run(_assert_today_timeout_is_retried_after_future_phase(monkeypatch))


async def _assert_today_timeout_is_retried_after_future_phase(monkeypatch):
    monkeypatch.setattr(scrape_manager_module, "SCRAPE_FAST_MAPPING_TIMEOUT", 1)
    monkeypatch.setattr(scrape_manager_module, "SCRAPE_MAPPING_TIMEOUT", 3)

    async with async_session() as session:
        target = (
            await session.execute(
                select(Hotel)
                .where(Hotel.is_mine.is_(False))
                .order_by(Hotel.id)
                .limit(1)
            )
        ).scalar_one()
        target_id = target.id
        target_name = target.name

        manager = ScraperManager(session)
        attempts: dict[tuple[int, date], int] = {}

        async def fake_scrape_mapping(mapping, check_in_dates, batch_id):
            check_in_date = check_in_dates[0]
            key = (mapping.hotel_id, check_in_date)
            attempts[key] = attempts.get(key, 0) + 1
            if check_in_date == date.today() and attempts[key] == 1:
                await asyncio.sleep(1.2)
            return {
                "ok": True,
                "hotel_id": mapping.hotel_id,
                "hotel_name": mapping.hotel.name,
                "platform": mapping.platform,
                "points": [
                    PricePoint(
                        check_in_date=check_in_date,
                        cheapest_room="补抓大床房",
                        cheapest_price=388.0,
                    )
                ],
                "started_at": datetime.utcnow(),
                "finished_at": datetime.utcnow(),
            }

        monkeypatch.setattr(manager, "_scrape_mapping", fake_scrape_mapping)
        stats = await manager.scrape_all(trigger_type="manual", hotel_ids=[target.id])

        assert stats["total"] == 3
        assert stats["success"] == 2
        assert stats["failed"] == 1
        assert stats["status"] == "partial_success"

        task_statuses = [
            item[0]
            for item in (
                await session.execute(
                    select(ScrapeTaskResult.status)
                    .where(ScrapeTaskResult.batch_id == stats["batch_id"])
                    .order_by(ScrapeTaskResult.id)
                )
            ).all()
        ]
        assert task_statuses == ["failed", "success", "retry_success"]

        price_count = (
            await session.execute(
                select(func.count())
                .select_from(PriceRecord)
                .where(PriceRecord.batch_id == stats["batch_id"])
            )
        ).scalar_one()
        assert price_count == 2


def test_scheduled_today_uses_longer_fast_timeout(monkeypatch):
    asyncio.run(_assert_scheduled_today_uses_longer_fast_timeout(monkeypatch))


async def _assert_scheduled_today_uses_longer_fast_timeout(monkeypatch):
    monkeypatch.setattr(scrape_manager_module, "SCRAPE_FAST_MAPPING_TIMEOUT", 1)
    monkeypatch.setattr(scrape_manager_module, "SCHEDULED_SCRAPE_FAST_MAPPING_TIMEOUT", 2)

    async with async_session() as session:
        target = (
            await session.execute(
                select(Hotel)
                .where(Hotel.is_mine.is_(False))
                .order_by(Hotel.id)
                .limit(1)
            )
        ).scalar_one()

        async def fake_scrape_mapping(mapping, check_in_dates, batch_id):
            await asyncio.sleep(1.2)
            return {
                "ok": True,
                "hotel_id": mapping.hotel_id,
                "hotel_name": mapping.hotel.name,
                "platform": mapping.platform,
                "points": [
                    PricePoint(
                        check_in_date=check_in_dates[0],
                        cheapest_room="后台慢速大床房",
                        cheapest_price=288.0,
                    )
                ],
                "started_at": datetime.utcnow(),
                "finished_at": datetime.utcnow(),
            }

        manual_manager = ScraperManager(session)
        monkeypatch.setattr(manual_manager, "_scrape_mapping", fake_scrape_mapping)
        manual_stats = await manual_manager.scrape_all(trigger_type="manual", hotel_ids=[target.id], scope="today")
        assert manual_stats["status"] == "failed"

        scheduled_manager = ScraperManager(session)
        monkeypatch.setattr(scheduled_manager, "_scrape_mapping", fake_scrape_mapping)
        scheduled_stats = await scheduled_manager.scrape_all(
            trigger_type="scheduled",
            hotel_ids=[target.id],
            scope="today",
        )
        assert scheduled_stats["status"] == "success"


def test_scheduled_today_retries_failed_hotel_once(monkeypatch):
    asyncio.run(_assert_scheduled_today_retries_failed_hotel_once(monkeypatch))


async def _assert_scheduled_today_retries_failed_hotel_once(monkeypatch):
    monkeypatch.setattr(scrape_manager_module, "SCHEDULED_SCRAPE_RETRY_FAILED_TODAY", True)
    monkeypatch.setattr(scrape_manager_module, "SCHEDULED_SCRAPE_FAST_MAPPING_TIMEOUT", 1)
    monkeypatch.setattr(scrape_manager_module, "SCRAPE_MAPPING_TIMEOUT", 3)

    async with async_session() as session:
        target = (
            await session.execute(
                select(Hotel)
                .where(Hotel.is_mine.is_(False))
                .order_by(Hotel.id)
                .limit(1)
            )
        ).scalar_one()

        manager = ScraperManager(session)
        attempts = 0

        async def fake_scrape_mapping(mapping, check_in_dates, batch_id):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                await asyncio.sleep(1.2)
            return {
                "ok": True,
                "hotel_id": mapping.hotel_id,
                "hotel_name": mapping.hotel.name,
                "platform": mapping.platform,
                "points": [
                    PricePoint(
                        check_in_date=check_in_dates[0],
                        cheapest_room="后台补抓成功房",
                        cheapest_price=266.0,
                    )
                ],
                "started_at": datetime.utcnow(),
                "finished_at": datetime.utcnow(),
            }

        monkeypatch.setattr(manager, "_scrape_mapping", fake_scrape_mapping)
        stats = await manager.scrape_all(trigger_type="scheduled", hotel_ids=[target.id], scope="today")

        assert attempts == 2
        assert stats["total"] == 1
        assert stats["success"] == 1
        assert stats["failed"] == 0
        assert stats["status"] == "success"

        task_statuses = [
            item[0]
            for item in (
                await session.execute(
                    select(ScrapeTaskResult.status)
                    .where(ScrapeTaskResult.batch_id == stats["batch_id"])
                    .order_by(ScrapeTaskResult.id)
                )
            ).all()
        ]
        assert task_statuses == ["failed", "retry_success"]


def test_scrape_run_clears_reused_batch_artifacts():
    asyncio.run(_assert_scrape_run_clears_reused_batch_artifacts())


async def _assert_scrape_run_clears_reused_batch_artifacts():
    async with async_session() as session:
        target = (
            await session.execute(
                select(Hotel)
                .where(Hotel.is_mine.is_(False))
                .order_by(Hotel.id)
                .limit(1)
            )
        ).scalar_one()
        target_id = target.id
        target_name = target.name
        old_time = datetime.utcnow() - timedelta(days=3)
        stale_run = ScrapeRun(
            trigger_type="manual",
            status="success",
            started_at=old_time,
            finished_at=old_time,
            total_tasks=1,
            success_tasks=1,
            failed_tasks=0,
        )
        session.add(stale_run)
        await session.flush()
        stale_batch_id = stale_run.id
        session.add(
            ScrapeTaskResult(
                batch_id=stale_batch_id,
                hotel_id=target_id,
                hotel_name=target_name,
                platform="ctrip",
                status="success",
                records_count=1,
                started_at=old_time,
                finished_at=old_time,
            )
        )
        session.add(
            PriceRecord(
                batch_id=stale_batch_id,
                hotel_id=target_id,
                platform="ctrip",
                check_in_date=date.today(),
                cheapest_room="旧批次污染房",
                cheapest_price=99,
                scraped_at=old_time,
            )
        )
        await session.flush()
        await session.execute(delete(ScrapeRun).where(ScrapeRun.id == stale_batch_id))
        await session.commit()

    async with async_session() as session:
        manager = ScraperManager(session)

        async def fake_scrape_mapping(mapping, check_in_dates, batch_id):
            return {
                "ok": True,
                "hotel_id": mapping.hotel_id,
                "hotel_name": mapping.hotel.name,
                "platform": mapping.platform,
                "points": [
                    PricePoint(
                        check_in_date=check_in_dates[0],
                        cheapest_room="新批次干净房",
                        cheapest_price=288.0,
                    )
                ],
                "started_at": datetime.utcnow(),
                "finished_at": datetime.utcnow(),
            }

        manager._scrape_mapping = fake_scrape_mapping  # type: ignore[method-assign]
        stats = await manager.scrape_all(trigger_type="manual", hotel_ids=[target_id], scope="today")

        assert stats["batch_id"] == stale_batch_id
        task_rows = list(
            (
                await session.execute(
                    select(ScrapeTaskResult)
                    .where(ScrapeTaskResult.batch_id == stats["batch_id"])
                    .order_by(ScrapeTaskResult.id)
                )
            ).scalars().all()
        )
        price_rows = list(
            (
                await session.execute(
                    select(PriceRecord)
                    .where(PriceRecord.batch_id == stats["batch_id"])
                    .order_by(PriceRecord.id)
                )
            ).scalars().all()
        )

        assert len(task_rows) == 1
        assert task_rows[0].started_at >= old_time
        assert len(price_rows) == 1
        assert price_rows[0].cheapest_room == "新批次干净房"


def test_duplicate_manual_trigger_returns_running_task():
    with TestClient(app) as client:
        first = client.post("/api/v1/scrape/trigger").json()
        second = client.post("/api/v1/scrape/trigger").json()
        assert second["task_id"] == first["task_id"]
        assert second["status"] == "running"
        wait_for_task(client, first["task_id"])


def test_hotel_mapping_configuration_api():
    with TestClient(app) as client:
        hotels = client.get("/api/v1/hotels").json()
        my_hotel = next(item for item in hotels if item["is_mine"])
        competitor_ids = [item["id"] for item in hotels if not item["is_mine"]]
        competitor_update = client.put(
            f"/api/v1/hotels/{my_hotel['id']}/competitors",
            json={"competitor_ids": competitor_ids[:3]},
        ).json()
        assert competitor_update["competitor_ids"] == competitor_ids[:3]

        too_many = client.put(
            f"/api/v1/hotels/{my_hotel['id']}/competitors",
            json={"competitor_ids": [*competitor_ids, 999]},
        )
        assert too_many.status_code == 400
        assert too_many.json()["detail"] == "每家门店最多配置 5 家竞对"

        hotel = client.post(
            "/api/v1/hotels",
            json={"name": "测试新增竞对", "is_mine": False, "distance_km": 1.8},
        ).json()
        assert hotel["id"]
        assert hotel["platform_mappings"] == []

        updated = client.patch(
            f"/api/v1/hotels/{hotel['id']}",
            json={"distance_km": 2.1},
        ).json()
        assert updated["distance_km"] == 2.1

        mapping = client.put(
            f"/api/v1/hotels/{hotel['id']}/platforms/ctrip",
            json={
                "hotel_url": "https://hotels.ctrip.com/hotel/998877.html",
                "default_room_name": "高级大床房",
            },
        ).json()
        assert mapping["platform"] == "ctrip"
        assert mapping["platform_hotel_id"] == "998877"
        assert mapping["default_room_name"] == "高级大床房"

        duplicate = client.put(
            "/api/v1/hotels/1/platforms/ctrip",
            json={
                "hotel_url": "https://hotels.ctrip.com/hotel/998877.html",
                "default_room_name": "重复大床房",
            },
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["detail"] == "该平台酒店 ID 已绑定到其他酒店"

        created_for_delete = client.post(
            "/api/v1/hotels",
            json={"name": "待删除竞对", "is_mine": False, "distance_km": 3.2},
        ).json()
        deleted = client.delete(f"/api/v1/hotels/{created_for_delete['id']}").json()
        assert deleted == {"deleted": True, "hotel_id": created_for_delete["id"]}
        missing = client.patch(
            f"/api/v1/hotels/{created_for_delete['id']}",
            json={"name": "不应存在"},
        )
        assert missing.status_code == 404


def test_auto_match_ctrip_mapping(monkeypatch):
    async def fake_search(hotel_name: str, city_id: int = 42, timeout: float = 15):
        return [
            CtripHotelCandidate(
                hotel_id="556677",
                name=hotel_name,
                url="https://hotels.ctrip.com/hotels/detail/?cityId=42&hotelId=556677",
                score=1.0,
            )
        ]

    monkeypatch.setattr("app.routers.hotels.search_ctrip_hotel_by_name", fake_search)

    with TestClient(app) as client:
        hotel = client.post(
            "/api/v1/hotels",
            json={"name": "自动匹配酒店", "is_mine": False},
        ).json()
        response = client.post(f"/api/v1/hotels/{hotel['id']}/platforms/ctrip/auto-match").json()

        assert response["matched"] is True
        assert response["mapping"]["platform"] == "ctrip"
        assert response["mapping"]["platform_hotel_id"] == "556677"
        assert response["mapping"]["hotel_url"].endswith("hotelId=556677")
        assert response["candidates"][0]["name"] == "自动匹配酒店"


def test_auto_match_ctrip_mapping_does_not_write_weak_match(monkeypatch):
    async def fake_search(hotel_name: str, city_id: int = 42, timeout: float = 15):
        return [
            CtripHotelCandidate(
                hotel_id="112233",
                name="完全不同酒店",
                url="https://hotels.ctrip.com/hotels/detail/?cityId=42&hotelId=112233",
                score=0.1,
            )
        ]

    monkeypatch.setattr("app.routers.hotels.search_ctrip_hotel_by_name", fake_search)

    with TestClient(app) as client:
        hotel = client.post(
            "/api/v1/hotels",
            json={"name": "自动匹配失败酒店", "is_mine": False},
        ).json()
        response = client.post(f"/api/v1/hotels/{hotel['id']}/platforms/ctrip/auto-match").json()

        assert response["matched"] is False
        assert response["mapping"] is None
        refreshed = client.get("/api/v1/hotels").json()
        target = next(item for item in refreshed if item["id"] == hotel["id"])
        assert target["platform_mappings"] == []


def test_auto_match_ctrip_group_matches_missing_urls(monkeypatch):
    search_ids: dict[str, str] = {}

    async def fake_search(hotel_name: str, city_id: int = 42, timeout: float = 15):
        hotel_id = search_ids.setdefault(hotel_name, str(700000 + len(search_ids)))
        return [
            CtripHotelCandidate(
                hotel_id=hotel_id,
                name=hotel_name,
                url=f"https://hotels.ctrip.com/hotels/detail/?cityId=42&hotelId={hotel_id}",
                score=1.0,
            )
        ]

    monkeypatch.setattr("app.routers.hotels.search_ctrip_hotel_by_name", fake_search)

    with TestClient(app) as client:
        my_hotel = client.post(
            "/api/v1/hotels",
            json={"name": "批量我方酒店", "is_mine": True},
        ).json()
        competitor = client.post(
            "/api/v1/hotels",
            json={"name": "批量竞对酒店", "is_mine": False},
        ).json()
        client.put(
            f"/api/v1/hotels/{my_hotel['id']}/competitors",
            json={"competitor_ids": [competitor["id"]]},
        )

        response = client.post(f"/api/v1/hotels/{my_hotel['id']}/platforms/ctrip/auto-match-group").json()

        assert response["total"] == 2
        assert response["matched"] == 2
        assert response["skipped"] == 0
        assert response["failed"] == 0

        second = client.post(f"/api/v1/hotels/{my_hotel['id']}/platforms/ctrip/auto-match-group").json()
        assert second["matched"] == 0
        assert second["skipped"] == 2


def test_delete_hotel_with_price_records_is_blocked():
    with TestClient(app) as client:
        trigger = client.post("/api/v1/scrape/trigger").json()
        wait_for_task(client, trigger["task_id"])
        response = client.delete("/api/v1/hotels/1")
        assert response.status_code == 409
        assert response.json()["detail"] == "该酒店已有价格记录，不能直接删除"


def wait_for_task(client: TestClient, task_id: str):
    for _ in range(100):
        status = client.get(f"/api/v1/scrape/status/{task_id}").json()
        if status["status"] in {"completed", "partial_success", "failed"}:
            return status
        time.sleep(0.05)
    raise TimeoutError("task did not finish")
