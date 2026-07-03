import asyncio

from app.services import scheduler


def test_scheduler_enabled_registers_scrape_and_backup_jobs(monkeypatch):
    asyncio.run(_assert_scheduler_enabled_registers_jobs(monkeypatch))


def test_scheduled_scrape_event_includes_target_scope_and_duration(monkeypatch):
    asyncio.run(_assert_scheduled_scrape_event_includes_target_scope_and_duration(monkeypatch))


async def _assert_scheduler_enabled_registers_jobs(monkeypatch):
    scheduler.stop_scheduler()
    monkeypatch.setattr(scheduler, "SCHEDULER_ENABLED", True)
    monkeypatch.setattr(scheduler, "SCRAPE_SCHEDULE_HOURS", [12, 18, 22])

    scheduler.start_scheduler()
    try:
        status = scheduler.get_scheduler_status()
        job_ids = {job["id"] for job in status["jobs"]}
        assert status["enabled"] is True
        assert status["running"] is True
        assert status["schedule_hours"] == [12, 18, 22]
        assert "last_scheduler_event" in status
        assert {"scrape_12", "scrape_18", "scrape_22", "daily_sqlite_backup"} <= job_ids
        assert all("next_run_time" in job for job in status["jobs"])
    finally:
        scheduler.stop_scheduler()


async def _assert_scheduled_scrape_event_includes_target_scope_and_duration(monkeypatch):
    async def fake_load_hotel_ids():
        return [7, 8, 9, 10, 11, 12]

    async def fake_scrape_and_report(**kwargs):
        assert kwargs["trigger_type"] == "scheduled"
        assert kwargs["scope"] == scheduler.SCHEDULED_SCRAPE_SCOPE
        assert kwargs["hotel_ids"] == [7, 8, 9, 10, 11, 12]
        return {
            "status": "success",
            "batch_id": 123,
            "success": 6,
            "failed": 0,
            "total": 6,
            "wall_time_s": 280.5,
        }

    monkeypatch.setattr(scheduler, "_last_scheduler_event", None)
    monkeypatch.setattr(scheduler, "_load_scheduled_hotel_ids", fake_load_hotel_ids)
    monkeypatch.setattr(scheduler, "scrape_and_report", fake_scrape_and_report)

    await scheduler.scheduled_scrape_job()

    event = scheduler.get_scheduler_status()["last_scheduler_event"]
    assert event["type"] == "scrape"
    assert event["status"] == "success"
    assert event["batch_id"] == 123
    assert event["scope"] == scheduler.SCHEDULED_SCRAPE_SCOPE
    assert event["target_hotel_count"] == 6
    assert event["wall_time_s"] == 280.5
    assert event["message"] == "定时抓取完成 6/6，目标 6 家"
    assert event["finished_at"].endswith("+08:00")
