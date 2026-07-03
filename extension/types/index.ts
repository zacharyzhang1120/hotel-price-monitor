export interface HotelPlatformMapping {
  id: number;
  platform: Platform;
  platform_hotel_id: string;
  hotel_url: string | null;
  default_room_name: string | null;
  created_at: string;
}

export interface HotelPlatformAutoMatchCandidate {
  hotel_id: string;
  name: string;
  url: string;
  score: number;
}

export interface HotelPlatformAutoMatchResponse {
  matched: boolean;
  hotel_id: number | null;
  hotel_name: string | null;
  mapping: HotelPlatformMapping | null;
  candidates: HotelPlatformAutoMatchCandidate[];
  message: string;
}

export interface HotelPlatformGroupAutoMatchResponse {
  total: number;
  matched: number;
  skipped: number;
  failed: number;
  results: HotelPlatformAutoMatchResponse[];
}

export interface Hotel {
  id: number;
  name: string;
  is_mine: boolean;
  distance_km: number | null;
  created_at: string;
  platform_mappings: HotelPlatformMapping[];
  competitor_ids: number[];
}

export type Platform = 'ctrip';

export interface CalendarPriceItem {
  hotel_id: number;
  hotel_name: string;
  is_mine: boolean;
  platform: Platform;
  check_in_date: string;
  cheapest_room: string | null;
  cheapest_price: number | null;
  scraped_at: string | null;
  batch_id: number | null;
  is_current_batch: boolean;
  is_fallback: boolean;
  task_status?: string | null;
  task_error_message?: string | null;
}

export interface CalendarResponse {
  data: CalendarPriceItem[];
}

export interface ScrapeTriggerResponse {
  task_id: string;
  status: string;
  message: string;
}

export interface ScrapeMilestone {
  type: 'success' | 'timeout' | 'failed';
  elapsed_s: number;
  message: string;
  hotel_id: number | null;
  hotel_name: string | null;
  platform: Platform | null;
}

export interface ScrapeStatusResponse {
  status: string;
  progress: string | null;
  error: string | null;
  batch_id: number | null;
  milestones: ScrapeMilestone[];
  wall_time_s: number | null;
  total_tasks: number;
  success_tasks: number;
  failed_tasks: number;
  completed_tasks: number;
}

export interface ScrapeRun {
  id: number;
  trigger_type: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  total_tasks: number;
  success_tasks: number;
  failed_tasks: number;
  error_summary: string | null;
  wall_time_s?: number | null;
}

export interface ScrapeTaskResult {
  id: number;
  batch_id: number;
  hotel_id: number;
  hotel_name: string;
  platform: Platform;
  status: string;
  records_count: number;
  error_message: string | null;
  has_evidence: boolean;
  started_at: string;
  finished_at: string;
}

export interface ScrapeTaskEvidence {
  id: number;
  batch_id: number;
  hotel_id: number;
  hotel_name: string;
  platform: Platform;
  status: string;
  evidence: Record<string, unknown> | null;
}

export interface ScrapeConfig {
  scraper_mode: string;
  enabled_platforms: Platform[];
  real_platforms: Platform[];
  scheduler_enabled: boolean;
  schedule_hours: number[];
  scheduled_scrape_scope: 'today' | 'future' | 'all' | string;
  future_days: number;
  scrape_concurrency: number;
  scrape_goto_wait_until: string;
  scrape_mapping_timeout: number;
  scrape_probe_timeout: number;
  scrape_today_first: boolean;
  scrape_fast_mapping_timeout: number;
  scheduled_scrape_fast_mapping_timeout: number;
  scheduled_scrape_retry_failed_today: boolean;
  price_fallback_max_age_hours: number;
  report_push_enabled: boolean;
  wecom_webhook_configured: boolean;
}

export interface ScrapeProbePoint {
  check_in_date: string;
  cheapest_room: string | null;
  cheapest_price: number | null;
}

export interface ScrapeProbeResponse {
  success: boolean;
  platform: Platform;
  mode: 'mock' | 'real';
  points: ScrapeProbePoint[];
  error: string | null;
}

export interface SchedulerJob {
  id: string;
  name: string;
  next_run_time: string | null;
}

export interface SchedulerEvent {
  type: string;
  status: string;
  batch_id: number | null;
  success: number;
  failed: number;
  scope?: string;
  target_hotel_count?: number | null;
  wall_time_s?: number | null;
  message: string;
  finished_at: string;
}

export interface SchedulerHealth {
  status: 'ok' | 'warning' | 'stale' | 'down' | 'disabled' | 'running' | string;
  message: string;
  latest_scheduled_batch_id?: number | null;
  latest_scheduled_status?: string | null;
  latest_scheduled_finished_at?: string | null;
  latest_scheduled_wall_time_s?: number | null;
  last_success_batch_id?: number | null;
  last_success_finished_at?: string | null;
  last_success_status?: string | null;
  last_success_target_hotel_count?: number | null;
  last_success_wall_time_s?: number | null;
  expected_previous_run_at?: string | null;
  grace_minutes?: number | null;
}

export interface SchedulerStatus {
  enabled: boolean;
  running: boolean;
  schedule_hours: number[];
  scheduled_scrape_scope?: 'today' | 'future' | 'all' | string;
  scheduled_target_hotel_count?: number;
  last_scheduler_event?: SchedulerEvent | null;
  scheduler_health?: SchedulerHealth | null;
  jobs: SchedulerJob[];
}

export interface BackupItem {
  filename: string;
  path: string;
  size_bytes: number;
  created_at: string;
}

export interface BackupListResponse {
  data: BackupItem[];
}

export interface BackupCreateResponse {
  filename: string;
  path: string;
}

export interface MissingMappingItem {
  hotel_id: number;
  hotel_name: string;
  platform: Platform;
  reason: string | null;
}

export interface SessionStatus {
  platform: Platform;
  has_session: boolean;
  cookie_count: number;
}

export interface ScrapeReadiness {
  scraper_mode: string;
  enabled_platforms: Platform[];
  active_real_platforms: Platform[];
  hotels_total: number;
  my_hotels_count: number;
  competitors_count: number;
  mappings_total: number;
  sessions: SessionStatus[];
  mappings_with_url: number;
  missing_enabled_mappings: MissingMappingItem[];
  missing_real_urls: MissingMappingItem[];
  invalid_real_urls: MissingMappingItem[];
  ready_for_mock: boolean;
  ready_for_real: boolean;
  messages: string[];
}
