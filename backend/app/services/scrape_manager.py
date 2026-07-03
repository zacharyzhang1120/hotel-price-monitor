"""Scrape orchestration."""

from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timedelta
from typing import Any, Callable, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import (
    ENABLED_PLATFORMS,
    FUTURE_DAYS,
    SCHEDULED_SCRAPE_FAST_MAPPING_TIMEOUT,
    SCHEDULED_SCRAPE_RETRY_FAILED_TODAY,
    SCRAPE_CONCURRENCY,
    SCRAPE_FAST_MAPPING_TIMEOUT,
    SCRAPE_MAPPING_TIMEOUT,
    SCRAPE_TODAY_FIRST,
)
from app.models import Hotel, HotelPlatformMapping, PriceRecord, ScrapeRun, ScrapeTaskResult
from app.services.scraper.registry import ScraperContext, create_scraper


class ScraperManager:
    def __init__(
        self,
        session: AsyncSession,
        progress_callback: Optional[Callable[[dict[str, Any]], None]] = None,
    ):
        self.session = session
        self.progress_callback = progress_callback

    async def scrape_all(
        self,
        trigger_type: str = "manual",
        hotel_ids: list[int] | None = None,
        scope: str = "all",
    ) -> dict[str, Any]:
        scrape_run = ScrapeRun(trigger_type=trigger_type, status="running", started_at=datetime.utcnow())
        self.session.add(scrape_run)
        await self.session.flush()
        await self._clear_existing_batch_artifacts(scrape_run.id)

        if scope == "today":
            all_dates = [date.today()]
        elif scope == "future":
            all_dates = [date.today() + timedelta(days=offset) for offset in range(1, FUTURE_DAYS + 1)]
        else:
            all_dates = [date.today() + timedelta(days=offset) for offset in range(FUTURE_DAYS + 1)]
        mappings = await self._load_mappings(hotel_ids=hotel_ids)
        missing_mappings = await self._load_missing_requested_mappings(hotel_ids or [], mappings)
        phase_count = 2 if (scope != "today" and SCRAPE_TODAY_FIRST and FUTURE_DAYS > 0) else 1
        if scope == "future":
            phase_count = 1
        total_tasks = len(mappings) * phase_count + len(missing_mappings)
        scrape_run.total_tasks = total_tasks
        await self.session.commit()
        today_timeout = (
            SCHEDULED_SCRAPE_FAST_MAPPING_TIMEOUT
            if trigger_type == "scheduled"
            else SCRAPE_FAST_MAPPING_TIMEOUT
        )

        semaphore = asyncio.Semaphore(max(1, SCRAPE_CONCURRENCY))
        success = 0
        failed = 0
        errors: list[str] = []
        if missing_mappings:
            missing_failed, missing_errors = await self._record_missing_mapping_failures(scrape_run, missing_mappings)
            failed += missing_failed
            errors.extend(missing_errors)

        # Two-phase: today first, then future dates (non-blocking)
        if scope == "today":
            self._report_phase("今日价格抓取中")
            base_success_before_today = success
            base_failed_before_today = failed
            base_errors_before_today = list(errors)
            phase_success, phase_failed, phase_errors, phase_failed_results, _ = await self._run_phase(
                scrape_run, mappings, all_dates, semaphore, "今日",
                phase_timeout=today_timeout,
                base_success=success,
                base_failed=failed,
                overall_total=total_tasks,
            )
            success += phase_success
            failed += phase_failed
            errors.extend(phase_errors)
            if trigger_type == "scheduled" and SCHEDULED_SCRAPE_RETRY_FAILED_TODAY:
                retry_mappings = self._mappings_for_retry(mappings, phase_failed_results)
                if retry_mappings:
                    self._report_phase("今日失败补抓中")
                    s_retry, f_retry, e_retry, retry_failed_results, retry_success_results = await self._run_phase(
                        scrape_run, retry_mappings, all_dates, semaphore, "今日补抓",
                        base_success=success,
                        base_failed=failed,
                        overall_total=total_tasks,
                    )
                    retry_success_keys = self._result_keys(retry_success_results)
                    retried_keys = self._mapping_keys(retry_mappings)
                    non_retryable_failed_results = [
                        result
                        for result in phase_failed_results
                        if (result["hotel_id"], result["platform"]) not in retried_keys
                    ]
                    unresolved_retry_keys = self._result_keys(retry_failed_results)
                    success = success + s_retry
                    failed = base_failed_before_today + len(non_retryable_failed_results) + len(unresolved_retry_keys)
                    errors = base_errors_before_today + [
                        self._result_error(result)
                        for result in non_retryable_failed_results
                    ] + e_retry
        elif scope == "future":
            self._report_phase("远期价格补抓中")
            phase_success, phase_failed, phase_errors, _, _ = await self._run_phase(
                scrape_run, mappings, all_dates, semaphore, "远期",
                base_success=success,
                base_failed=failed,
                overall_total=total_tasks,
            )
            success += phase_success
            failed += phase_failed
            errors.extend(phase_errors)
        elif SCRAPE_TODAY_FIRST and FUTURE_DAYS > 0:
            today_dates = all_dates[:1]
            future_dates = all_dates[1:]

            # Phase 1: today only (fast timeout)
            self._report_phase("今日价格抓取中")
            s_today, f_today, e_today, today_failed_results, _ = await self._run_phase(
                scrape_run, mappings, today_dates, semaphore, "今日",
                phase_timeout=today_timeout,
                base_success=success,
                base_failed=failed,
                overall_total=total_tasks,
                phase_offset=0,
            )
            success += s_today
            failed += f_today
            errors.extend(e_today)
            retry_mappings = self._mappings_for_retry(mappings, today_failed_results)

            # Phase 2: future dates
            if future_dates:
                self._report_phase("远期价格补抓中")
                s_future, f_future, e_future, _, _ = await self._run_phase(
                    scrape_run, mappings, future_dates, semaphore, "远期",
                    base_success=success,
                    base_failed=failed,
                    overall_total=total_tasks,
                    phase_offset=len(mappings),
                )
                success += s_future
                failed += f_future
                errors.extend(e_future)

            # Phase 3: long retry for today's fast timeouts.
            if retry_mappings:
                total_tasks += len(retry_mappings)
                scrape_run.total_tasks = total_tasks
                await self.session.commit()
                self._report_phase("今日超时补抓中")
                s_retry, f_retry, e_retry, _, _ = await self._run_phase(
                    scrape_run, retry_mappings, today_dates, semaphore, "今日补抓",
                    base_success=success,
                    base_failed=failed,
                    overall_total=total_tasks,
                    phase_offset=len(mappings) + len(future_dates and mappings or []),
                )
                success += s_retry
                failed += f_retry
                errors.extend(e_retry)
        else:
            phase_success, phase_failed, phase_errors, _, _ = await self._run_phase(
                scrape_run, mappings, all_dates, semaphore, "",
                base_success=success,
                base_failed=failed,
                overall_total=total_tasks,
            )
            success += phase_success
            failed += phase_failed
            errors.extend(phase_errors)

        scrape_run.success_tasks = success
        scrape_run.failed_tasks = failed
        scrape_run.status = "success" if failed == 0 else ("partial_success" if success else "failed")
        scrape_run.finished_at = datetime.utcnow()
        scrape_run.error_summary = "\n".join(errors) if errors else None
        await self.session.commit()

        return {
            "batch_id": scrape_run.id,
            "total": total_tasks,
            "success": success,
            "failed": failed,
            "errors": errors,
            "status": scrape_run.status,
            "wall_time_s": round((scrape_run.finished_at - scrape_run.started_at).total_seconds(), 1),
        }

    async def _run_phase(
        self,
        scrape_run: ScrapeRun,
        mappings: list[HotelPlatformMapping],
        check_in_dates: list[date],
        semaphore: asyncio.Semaphore,
        phase_label: str,
        phase_timeout: int | None = None,
        base_success: int = 0,
        base_failed: int = 0,
        overall_total: int | None = None,
        phase_offset: int = 0,
    ) -> tuple[int, int, list[str], list[dict[str, Any]], list[dict[str, Any]]]:
        """Run one scraping phase and return (success, failed, errors)."""
        timeout = phase_timeout if phase_timeout is not None else SCRAPE_MAPPING_TIMEOUT
        overall_total = overall_total if overall_total is not None else len(mappings)
        tasks = [
            self._scrape_mapping_with_limits(
                mapping, check_in_dates, scrape_run.id, semaphore, index, len(mappings),
                phase_label, timeout, overall_total, phase_offset,
            )
            for index, mapping in enumerate(mappings, start=1)
        ]

        errors: list[str] = []
        failed_results: list[dict[str, Any]] = []
        success_results: list[dict[str, Any]] = []
        success = 0
        failed = 0

        for coro in asyncio.as_completed(tasks):
            result = await coro
            if isinstance(result, Exception):
                failed += 1
                errors.append(str(result))
                continue

            scraped_at = datetime.utcnow()
            valid_points = [
                point
                for point in result.get("points", [])
                if point.cheapest_price is not None
            ]
            if result["ok"] and valid_points:
                success += 1
                success_results.append(result)
                self.session.add(
                    ScrapeTaskResult(
                        batch_id=scrape_run.id,
                        hotel_id=result["hotel_id"],
                        hotel_name=result["hotel_name"],
                        platform=result["platform"],
                        status="retry_success" if phase_label == "今日补抓" else "success",
                        records_count=len(valid_points),
                        evidence_json=self._evidence_json(result.get("evidence")),
                        started_at=result["started_at"],
                        finished_at=result["finished_at"],
                    )
                )
                for point in valid_points:
                    self.session.add(
                        PriceRecord(
                            batch_id=scrape_run.id,
                            hotel_id=result["hotel_id"],
                            platform=result["platform"],
                            check_in_date=point.check_in_date,
                            cheapest_room=point.cheapest_room,
                            cheapest_price=point.cheapest_price,
                            scraped_at=scraped_at,
                        )
                    )
            else:
                failed += 1
                failed_results.append(result)
                error = result.get("error")
                if not error:
                    error = f"{result['hotel_name']}/{result['platform']}: 未抓取到有效价格"
                errors.append(error)
                self.session.add(
                    ScrapeTaskResult(
                        batch_id=scrape_run.id,
                        hotel_id=result["hotel_id"],
                        hotel_name=result["hotel_name"],
                        platform=result["platform"],
                        status="retry_failed" if phase_label == "今日补抓" else "failed",
                        records_count=0,
                        error_message=error,
                        evidence_json=self._evidence_json(result.get("evidence")),
                        started_at=result["started_at"],
                        finished_at=result["finished_at"],
                    )
                )

            scrape_run.success_tasks = base_success + success
            scrape_run.failed_tasks = base_failed + failed
            scrape_run.status = "partial_success" if scrape_run.success_tasks else "running"
            await self.session.commit()

        return success, failed, errors, failed_results, success_results

    def _report_phase(self, message: str) -> None:
        if self.progress_callback:
            self.progress_callback({
                "type": "phase",
                "message": message,
                "hotel_id": 0,
                "hotel_name": "",
                "platform": "",
                "index": 0,
                "total": 0,
            })

    async def _load_mappings(self, hotel_ids: list[int] | None = None) -> list[HotelPlatformMapping]:
        stmt = (
            select(HotelPlatformMapping)
            .options(selectinload(HotelPlatformMapping.hotel))
            .where(HotelPlatformMapping.platform.in_(ENABLED_PLATFORMS))
            .order_by(HotelPlatformMapping.hotel_id, HotelPlatformMapping.platform)
        )
        if hotel_ids:
            stmt = stmt.where(HotelPlatformMapping.hotel_id.in_(hotel_ids))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def _clear_existing_batch_artifacts(self, batch_id: int) -> None:
        await self.session.execute(delete(PriceRecord).where(PriceRecord.batch_id == batch_id))
        await self.session.execute(delete(ScrapeTaskResult).where(ScrapeTaskResult.batch_id == batch_id))

    async def _load_missing_requested_mappings(
        self,
        hotel_ids: list[int],
        mappings: list[HotelPlatformMapping],
    ) -> list[dict[str, Any]]:
        if not hotel_ids:
            return []

        requested_ids = list(dict.fromkeys(hotel_ids))
        hotels = list(
            (
                await self.session.execute(
                    select(Hotel).where(Hotel.id.in_(requested_ids)).order_by(Hotel.id)
                )
            ).scalars().all()
        )
        mapped_keys = {(mapping.hotel_id, mapping.platform) for mapping in mappings}
        missing: list[dict[str, Any]] = []
        for hotel in hotels:
            for platform in ENABLED_PLATFORMS:
                if (hotel.id, platform) in mapped_keys:
                    continue
                missing.append(
                    {
                        "hotel_id": hotel.id,
                        "hotel_name": hotel.name,
                        "platform": platform,
                        "error": f"{hotel.name}/{platform}: 缺少平台映射或携程 URL，无法真实抓取",
                    }
                )
        return missing

    async def _record_missing_mapping_failures(
        self,
        scrape_run: ScrapeRun,
        missing_mappings: list[dict[str, Any]],
    ) -> tuple[int, list[str]]:
        errors: list[str] = []
        now = datetime.utcnow()
        for item in missing_mappings:
            error = item["error"]
            errors.append(error)
            self.session.add(
                ScrapeTaskResult(
                    batch_id=scrape_run.id,
                    hotel_id=item["hotel_id"],
                    hotel_name=item["hotel_name"],
                    platform=item["platform"],
                    status="failed",
                    records_count=0,
                    error_message=error,
                    evidence_json=self._evidence_json(
                        {
                            "hotel_url": None,
                            "check_in_dates": [],
                            "error": error,
                            "points": [],
                        }
                    ),
                    started_at=now,
                    finished_at=now,
                )
            )
        scrape_run.failed_tasks += len(missing_mappings)
        scrape_run.status = "running"
        await self.session.commit()
        return len(missing_mappings), errors

    async def _scrape_mapping(
        self,
        mapping: HotelPlatformMapping,
        check_in_dates: list[date],
        batch_id: int,
    ) -> dict[str, Any]:
        try:
            started_at = datetime.utcnow()
            if not mapping.hotel_url:
                raise RuntimeError("缺少携程 URL，无法真实抓取。请先在配置页保存该酒店的平台 URL")
            scraper = self._create_scraper(mapping, batch_id)
            points = await scraper.fetch_calendar(mapping.hotel_url, check_in_dates)
            evidence = self._build_mapping_evidence(mapping, check_in_dates, points)
            return {
                "ok": True,
                "hotel_id": mapping.hotel_id,
                "hotel_name": mapping.hotel.name,
                "platform": mapping.platform,
                "points": points,
                "evidence": evidence,
                "started_at": started_at,
                "finished_at": datetime.utcnow(),
            }
        except Exception as exc:
            finished_at = datetime.utcnow()
            return {
                "ok": False,
                "hotel_id": mapping.hotel_id,
                "hotel_name": mapping.hotel.name,
                "platform": mapping.platform,
                "error": f"{mapping.hotel.name}/{mapping.platform}: {exc}",
                "evidence": self._build_error_evidence(mapping, check_in_dates, str(exc)),
                "started_at": locals().get("started_at", finished_at),
                "finished_at": finished_at,
            }

    async def _scrape_mapping_with_limits(
        self,
        mapping: HotelPlatformMapping,
        check_in_dates: list[date],
        batch_id: int,
        semaphore: asyncio.Semaphore,
        index: int,
        total: int,
        phase_label: str = "",
        timeout: int | None = None,
        overall_total: int | None = None,
        phase_offset: int = 0,
    ) -> dict[str, Any]:
        effective_timeout = timeout if timeout is not None else SCRAPE_MAPPING_TIMEOUT
        async with semaphore:
            started_at = datetime.utcnow()
            self._report_progress("started", mapping, index, total, phase_label, overall_total, phase_offset)
            try:
                result = await asyncio.wait_for(
                    self._scrape_mapping(mapping, check_in_dates, batch_id),
                    timeout=max(1, effective_timeout),
                )
                result.setdefault("started_at", started_at)
                result.setdefault("finished_at", datetime.utcnow())
                has_valid_price = any(point.cheapest_price is not None for point in result.get("points", []))
                event_type = "success" if result.get("ok") and has_valid_price else "failed"
                self._report_progress(event_type, mapping, index, total, phase_label, overall_total, phase_offset)
                return result
            except asyncio.TimeoutError:
                self._report_progress("timeout", mapping, index, total, phase_label, overall_total, phase_offset)
                return {
                    "ok": False,
                    "hotel_id": mapping.hotel_id,
                    "hotel_name": mapping.hotel.name,
                    "platform": mapping.platform,
                    "retryable": True,
                    "error": (
                        f"{mapping.hotel.name}/{mapping.platform}: "
                        f"抓取超过 {effective_timeout} 秒，已自动中止"
                    ),
                    "evidence": self._build_error_evidence(
                        mapping,
                        check_in_dates,
                        f"抓取超过 {effective_timeout} 秒，已自动中止",
                    ),
                    "started_at": started_at,
                    "finished_at": datetime.utcnow(),
                }

    def _report_progress(
        self,
        event_type: str,
        mapping: HotelPlatformMapping,
        index: int,
        total: int,
        phase_label: str = "",
        overall_total: int | None = None,
        phase_offset: int = 0,
    ) -> None:
        if self.progress_callback:
            status_text = {
                "started": "正在抓取",
                "success": "已完成",
                "failed": "已失败",
                "timeout": "已超时",
            }.get(event_type, "抓取中")
            prefix = f"[{phase_label}] " if phase_label else ""
            self.progress_callback(
                {
                    "type": event_type,
                    "message": f"{prefix}{status_text} {index}/{total}：{mapping.hotel.name} / {mapping.platform}",
                    "hotel_id": mapping.hotel_id,
                    "hotel_name": mapping.hotel.name,
                    "platform": mapping.platform,
                    "index": index,
                    "total": total,
                    "phase": phase_label,
                    "overall_index": phase_offset + index,
                    "overall_total": overall_total or total,
                }
            )

    def _create_scraper(self, mapping: HotelPlatformMapping, batch_id: int):
        return create_scraper(
            ScraperContext(
                platform=mapping.platform,
                hotel_name=mapping.hotel.name,
                default_room_name=mapping.default_room_name,
                batch_seed=batch_id,
            )
        )

    @staticmethod
    def _build_mapping_evidence(
        mapping: HotelPlatformMapping,
        check_in_dates: list[date],
        points,
    ) -> dict[str, Any]:
        return {
            "hotel_url": mapping.hotel_url,
            "check_in_dates": [item.isoformat() for item in check_in_dates],
            "points": [
                {
                    "check_in_date": point.check_in_date.isoformat(),
                    "selected": (
                        {"room": point.cheapest_room, "price": point.cheapest_price}
                        if point.cheapest_room and point.cheapest_price is not None
                        else None
                    ),
                    "scraper_evidence": point.evidence,
                }
                for point in points
            ],
        }

    @staticmethod
    def _build_error_evidence(
        mapping: HotelPlatformMapping,
        check_in_dates: list[date],
        error: str,
    ) -> dict[str, Any]:
        return {
            "hotel_url": mapping.hotel_url,
            "check_in_dates": [item.isoformat() for item in check_in_dates],
            "error": error,
            "points": [],
        }

    @staticmethod
    def _evidence_json(evidence: Optional[dict[str, Any]]) -> Optional[str]:
        if evidence is None:
            return None
        return json.dumps(evidence, ensure_ascii=False, default=str)

    @staticmethod
    def _mappings_for_retry(
        mappings: list[HotelPlatformMapping],
        failed_results: list[dict[str, Any]],
    ) -> list[HotelPlatformMapping]:
        retry_keys = {
            (result["hotel_id"], result["platform"])
            for result in failed_results
            if result.get("retryable")
        }
        return [
            mapping
            for mapping in mappings
            if (mapping.hotel_id, mapping.platform) in retry_keys
        ]

    @staticmethod
    def _mapping_keys(mappings: list[HotelPlatformMapping]) -> set[tuple[int, str]]:
        return {(mapping.hotel_id, mapping.platform) for mapping in mappings}

    @staticmethod
    def _result_keys(results: list[dict[str, Any]]) -> set[tuple[int, str]]:
        return {(result["hotel_id"], result["platform"]) for result in results}

    @staticmethod
    def _result_error(result: dict[str, Any]) -> str:
        error = result.get("error")
        if error:
            return error
        return f"{result['hotel_name']}/{result['platform']}: 未抓取到有效价格"
