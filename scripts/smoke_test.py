"""Smoke test for the local MVP backend."""

import json
import os
import time
import urllib.parse
import urllib.request
from datetime import date
from typing import Optional

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8080").rstrip("/")


def main():
    assert get_json("/health")["status"] == "ok"
    assert get_json("/")["api_prefix"] == "/api/v1"

    hotels = get_json("/api/v1/hotels")
    assert len(hotels) >= 6, f"expected at least 6 hotels, got {len(hotels)}"
    mapping_count = sum(len(item["platform_mappings"]) for item in hotels)
    assert mapping_count >= 6, f"expected at least 6 mappings, got {mapping_count}"
    assert hotels[0]["platform_mappings"][0]["hotel_url"], "expected platform mapping urls"

    scrape_config = get_json("/api/v1/scrape/config")
    assert "ctrip" in scrape_config["enabled_platforms"], scrape_config
    assert scrape_config["report_push_enabled"] is False, scrape_config
    scheduler_status = get_json("/api/v1/scheduler/status")
    assert scheduler_status["schedule_hours"] == [12, 18, 22], scheduler_status
    readiness = get_json("/api/v1/scrape/readiness")
    assert readiness["ready_for_mock"] is True, readiness
    assert readiness["hotels_total"] >= 6, readiness
    assert readiness["missing_enabled_mappings"] == [], readiness

    if scrape_config["scraper_mode"] == "mock":
        trigger = post_json("/api/v1/scrape/trigger")
        task_id = trigger["task_id"]
        status = wait_for_task(task_id, attempts=100, interval=0.1)
        assert status["status"] in {"completed", "partial_success"}, status
        assert status["progress"] == f"{mapping_count}/{mapping_count}", status
        batch_id = status["batch_id"]
    else:
        runs = get_json("/api/v1/scrape/runs?limit=1")
        assert runs, "expected at least one scrape run in real mode; trigger from the UI if empty"
        batch_id = runs[0]["id"]

    runs = get_json("/api/v1/scrape/runs?limit=3")
    assert runs[0]["id"] == batch_id, runs
    task_results = get_json(f"/api/v1/scrape/runs/{batch_id}/tasks")
    assert len(task_results) == mapping_count, f"expected {mapping_count} task results, got {len(task_results)}"
    assert {item["status"] for item in task_results} <= {"success", "failed"}, task_results

    latest = get_json("/api/v1/scrape/latest")
    assert latest["id"] == batch_id, latest

    today = date.today().isoformat()
    calendar = get_json(f"/api/v1/prices/calendar?date={today}&days=8")
    expected_calendar_rows = mapping_count * 8
    assert len(calendar["data"]) == expected_calendar_rows, (
        f"expected {expected_calendar_rows} calendar rows, got {len(calendar['data'])}"
    )

    competitor = next(item for item in calendar["data"] if not item["is_mine"])
    params = urllib.parse.urlencode(
        {
            "hotel_id": competitor["hotel_id"],
            "check_in_date": today,
        }
    )
    trend = get_json(f"/api/v1/prices/trend?{params}")
    assert len(trend["data"]) >= 1, f"expected trend rows, got {len(trend['data'])}"

    probe_payload = {
        "platform": "ctrip",
        "hotel_url": "https://hotels.ctrip.com/hotel/1234567.html",
        "check_in_date": today,
        "room_name": "豪华大床房",
        "mode": "mock",
    }
    probe = post_json("/api/v1/scrape/probe", probe_payload)
    assert probe["success"] is True, probe
    assert probe["points"][0]["cheapest_price"] is not None, probe

    report = get_json(f"/api/v1/reports/latest?date={today}")
    assert report["my_hotel"], "expected my_hotel in report"
    assert len(report["competitors"]) == 5, f"expected 5 competitors, got {len(report['competitors'])}"

    report_text = get_text(f"/api/v1/reports/latest?date={today}&format=wechat_text")
    assert "竞对价格日报" in report_text, "expected wechat report text"

    backup = post_json("/api/v1/backups/create")
    assert backup["filename"].startswith("hotel_prices_"), backup
    backups = get_json("/api/v1/backups")
    assert any(item["filename"] == backup["filename"] for item in backups["data"]), backups

    print("Smoke test passed.")
    print(f"Batch: {batch_id}")
    print(f"Calendar rows: {len(calendar['data'])}")


def get_json(path: str):
    with urllib.request.urlopen(BASE_URL + path, timeout=10) as response:
        return json.loads(response.read())


def post_json(path: str, payload: Optional[dict] = None):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(BASE_URL + path, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read())


def get_text(path: str):
    with urllib.request.urlopen(BASE_URL + path, timeout=10) as response:
        return response.read().decode("utf-8")


def wait_for_task(task_id: str, attempts: int, interval: float):
    for _ in range(attempts):
        status = get_json(f"/api/v1/scrape/status/{task_id}")
        if status["status"] in {"completed", "partial_success", "failed"}:
            return status
        time.sleep(interval)
    raise TimeoutError("scrape task did not finish")


if __name__ == "__main__":
    main()
