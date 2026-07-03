import type {
  BackupCreateResponse,
  BackupListResponse,
  CalendarResponse,
  Hotel,
  HotelPlatformAutoMatchResponse,
  HotelPlatformGroupAutoMatchResponse,
  HotelPlatformMapping,
  ScrapeConfig,
  ScrapeProbeResponse,
  ScrapeReadiness,
  ScrapeRun,
  ScrapeStatusResponse,
  ScrapeTaskEvidence,
  ScrapeTaskResult,
  ScrapeTriggerResponse,
  SchedulerStatus
} from '../types';

export const API_BASE = (import.meta.env.VITE_API_BASE || 'http://localhost:8080/api/v1').replace(/\/$/, '');

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, options);
  if (!response.ok) {
    let message = `接口请求失败：${response.status}`;
    try {
      const payload = await response.json();
      if (payload?.detail) message = payload.detail;
    } catch {
      // Keep the status message when the response is not JSON.
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

async function requestText(path: string, options?: RequestInit): Promise<string> {
  const response = await fetch(`${API_BASE}${path}`, options);
  if (!response.ok) {
    throw new Error(`接口请求失败：${response.status}`);
  }
  return response.text();
}

export function useApi() {
  return {
    fetchHotels: () => request<Hotel[]>('/hotels'),
    createHotel: (payload: { name: string; is_mine: boolean; distance_km?: number | null }) =>
      request<Hotel>('/hotels', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      }),
    updateHotel: (hotelId: number, payload: { name?: string; is_mine?: boolean; distance_km?: number | null }) =>
      request<Hotel>(`/hotels/${hotelId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      }),
    deleteHotel: (hotelId: number) =>
      request<{ deleted: boolean; hotel_id: number }>(`/hotels/${hotelId}`, {
        method: 'DELETE'
      }),
    updateHotelCompetitors: (hotelId: number, competitorIds: number[]) =>
      request<Hotel>(`/hotels/${hotelId}/competitors`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ competitor_ids: competitorIds })
      }),
    fetchCalendar: (date: string, days = 8, hotelIds?: number[]) => {
      const params = new URLSearchParams({ date, days: String(days) });
      if (hotelIds?.length) params.set('hotel_ids', hotelIds.join(','));
      return request<CalendarResponse>(`/prices/calendar?${params.toString()}`);
    },
    triggerScrape: (hotelIds?: number[], scope: 'today' | 'future' | 'all' = 'today') => {
      let url = '/scrape/trigger';
      const params = new URLSearchParams({ scope });
      if (hotelIds?.length) params.set('hotel_ids', hotelIds.join(','));
      url += `?${params.toString()}`;
      return request<ScrapeTriggerResponse>(url, { method: 'POST' });
    },
    getScrapeStatus: (taskId: string) => request<ScrapeStatusResponse>(`/scrape/status/${taskId}`),
    fetchScrapeConfig: () => request<ScrapeConfig>('/scrape/config'),
    fetchScrapeReadiness: (hotelIds?: number[]) => {
      const params = new URLSearchParams();
      if (hotelIds?.length) params.set('hotel_ids', hotelIds.join(','));
      const suffix = params.toString() ? `?${params.toString()}` : '';
      return request<ScrapeReadiness>(`/scrape/readiness${suffix}`);
    },
    fetchSchedulerStatus: () => request<SchedulerStatus>('/scheduler/status'),
    fetchBackups: () => request<BackupListResponse>('/backups'),
    createBackup: () => request<BackupCreateResponse>('/backups/create', { method: 'POST' }),
    fetchLatestScrape: (hotelIds?: number[]) => {
      const params = new URLSearchParams();
      if (hotelIds?.length) params.set('hotel_ids', hotelIds.join(','));
      const suffix = params.toString() ? `?${params.toString()}` : '';
      return request<ScrapeRun | null>(`/scrape/latest${suffix}`);
    },
    fetchScrapeRuns: (limit = 3, hotelIds?: number[]) => {
      const params = new URLSearchParams({ limit: String(limit) });
      if (hotelIds?.length) params.set('hotel_ids', hotelIds.join(','));
      return request<ScrapeRun[]>(`/scrape/runs?${params.toString()}`);
    },
    fetchScrapeTaskResults: (batchId: number) => request<ScrapeTaskResult[]>(`/scrape/runs/${batchId}/tasks`),
    fetchScrapeTaskEvidence: (batchId: number, taskResultId: number) =>
      request<ScrapeTaskEvidence>(`/scrape/runs/${batchId}/tasks/${taskResultId}/evidence`),
    updatePlatformMapping: (
      hotelId: number,
      platform: string,
      payload: { hotel_url: string; default_room_name?: string | null; platform_hotel_id?: string | null }
    ) =>
      request<HotelPlatformMapping>(`/hotels/${hotelId}/platforms/${platform}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      }),
    autoMatchCtripMapping: (hotelId: number) =>
      request<HotelPlatformAutoMatchResponse>(`/hotels/${hotelId}/platforms/ctrip/auto-match`, {
        method: 'POST'
      }),
    autoMatchCtripGroup: (hotelId: number) =>
      request<HotelPlatformGroupAutoMatchResponse>(`/hotels/${hotelId}/platforms/ctrip/auto-match-group`, {
        method: 'POST'
      }),
    probeScraper: (payload: {
      platform: string;
      hotel_url: string;
      check_in_date: string;
      room_name?: string | null;
      mode: 'mock' | 'real';
    }) =>
      request<ScrapeProbeResponse>('/scrape/probe', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      }),
    fetchWechatReport: (date: string, mineHotelId?: number | null) => {
      const params = new URLSearchParams({ format: 'wechat_text', date });
      if (mineHotelId) params.set('mine_hotel_id', String(mineHotelId));
      return requestText(`/reports/generate?${params.toString()}`, { method: 'POST' });
    },
    loginCtrip: () =>
      request<{ success: boolean; message: string; cookies?: number; has_prices?: boolean }>(
        '/scrape/login',
        { method: 'POST' }
      ),
  };
}
