"""Export a local diagnostics bundle for MVP testing."""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

DEFAULT_BASE_URL = "http://127.0.0.1:8080"
ROOT_DIR = Path(__file__).resolve().parents[1]
DIAGNOSTICS_DIR = ROOT_DIR / "diagnostics"


def main() -> None:
    parser = argparse.ArgumentParser(description="Export local hotel-price-monitor diagnostics.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    args = parser.parse_args()

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target_dir = DIAGNOSTICS_DIR / f"diagnostics_{stamp}"
    target_dir.mkdir(parents=True, exist_ok=True)

    files: list[Path] = []
    summary: dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "base_url": args.base_url,
        "ok": True,
        "errors": [],
    }

    json_paths = {
        "health": "/health",
        "root": "/",
        "hotels": "/api/v1/hotels",
        "scrape_config": "/api/v1/scrape/config",
        "scrape_readiness": "/api/v1/scrape/readiness",
        "scheduler_status": "/api/v1/scheduler/status",
        "latest_scrape": "/api/v1/scrape/latest",
        "scrape_runs": "/api/v1/scrape/runs?limit=5",
        "backups": "/api/v1/backups",
    }

    for name, path in json_paths.items():
        try:
            payload = get_json(args.base_url, path)
            files.append(write_json(target_dir / f"{name}.json", payload))
            if name == "scrape_readiness":
                summary["ready_for_mock"] = payload.get("ready_for_mock")
                summary["ready_for_real"] = payload.get("ready_for_real")
                summary["invalid_real_urls"] = len(payload.get("invalid_real_urls", []))
            if name == "scheduler_status":
                summary["scheduler_enabled"] = payload.get("enabled")
                summary["scheduler_jobs"] = len(payload.get("jobs", []))
        except Exception as exc:
            summary["ok"] = False
            summary["errors"].append({"name": name, "path": path, "error": str(exc)})

    latest = read_json_if_exists(target_dir / "latest_scrape.json")
    if latest and latest.get("id"):
        try:
            tasks = get_json(args.base_url, f"/api/v1/scrape/runs/{latest['id']}/tasks")
            files.append(write_json(target_dir / "latest_scrape_tasks.json", tasks))
            summary["latest_batch_id"] = latest["id"]
            summary["latest_batch_status"] = latest.get("status")
            summary["latest_task_count"] = len(tasks)
        except Exception as exc:
            summary["ok"] = False
            summary["errors"].append({"name": "latest_scrape_tasks", "error": str(exc)})

    try:
        report_text = get_text(args.base_url, "/api/v1/reports/latest?format=wechat_text")
        files.append(write_text(target_dir / "latest_report_wechat.txt", report_text))
    except Exception as exc:
        summary["ok"] = False
        summary["errors"].append({"name": "latest_report_wechat", "error": str(exc)})

    hotels = read_json_if_exists(target_dir / "hotels.json") or []
    files.append(write_text(target_dir / "platform_mappings.txt", format_platform_mappings(hotels)))

    files.append(write_json(target_dir / "summary.json", summary))
    print(f"Diagnostics exported: {target_dir}")
    print(f"Files: {len(files)}")
    print(f"Ready for mock: {summary.get('ready_for_mock')}")
    print(f"Ready for real: {summary.get('ready_for_real')}")
    if summary["errors"]:
        print(f"Errors: {len(summary['errors'])}")


def get_json(base_url: str, path: str) -> Any:
    with urllib.request.urlopen(base_url + path, timeout=10) as response:
        return json.loads(response.read())


def get_text(base_url: str, path: str) -> str:
    with urllib.request.urlopen(base_url + path, timeout=10) as response:
        return response.read().decode("utf-8")


def write_json(path: Path, payload: Any) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_text(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def read_json_if_exists(path: Path) -> Any:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def format_platform_mappings(hotels: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for hotel in hotels:
        role = "我方" if hotel.get("is_mine") else "竞对"
        distance = hotel.get("distance_km")
        distance_label = "" if distance is None else f" {distance:g}km"
        lines.append(f"[{role}] #{hotel['id']} {hotel['name']}{distance_label}")
        mappings = sorted(hotel.get("platform_mappings", []), key=lambda item: item.get("platform", ""))
        for mapping in mappings:
            room = mapping.get("default_room_name") or "-"
            url = mapping.get("hotel_url") or "-"
            lines.append(f"  - {mapping.get('platform')}: room={room} url={url}")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
