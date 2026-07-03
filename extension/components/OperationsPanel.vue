<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { API_BASE, useApi } from '../composables/useApi';
import type { BackupItem, SchedulerStatus, ScrapeConfig, ScrapeReadiness, ScrapeRun, ScrapeTaskEvidence, ScrapeTaskResult } from '../types';
import { writeClipboardText } from '../utils/clipboard';

const props = defineProps<{
  hotelIds?: number[];
}>();

const api = useApi();
const scheduler = ref<SchedulerStatus | null>(null);
const scrapeConfig = ref<ScrapeConfig | null>(null);
const readiness = ref<ScrapeReadiness | null>(null);
const backups = ref<BackupItem[]>([]);
const scrapeRuns = ref<ScrapeRun[]>([]);
const taskResults = ref<ScrapeTaskResult[]>([]);
const runTaskCounts = ref<Record<number, { ok: number; total: number }>>({});
const loading = ref(false);
const creating = ref(false);
const copying = ref(false);
const loggingIn = ref(false);
const loadingEvidenceId = ref<number | null>(null);
const selectedEvidence = ref<ScrapeTaskEvidence | null>(null);
const message = ref('');
const diagnosticLabel = ref('复制诊断');

const runStatusLabels: Record<string, string> = {
  success: '成功',
  partial_success: '部分成功',
  failed: '失败',
  running: '进行中'
};

const triggerTypeLabels: Record<string, string> = {
  manual: '手动',
  scheduled: '定时'
};

const taskStatusLabels: Record<string, string> = {
  success: '成功',
  failed: '失败',
  retry_success: '补抓成功',
  retry_failed: '补抓失败'
};

function aggregatedTaskResults() {
  const groups = new Map<string, ScrapeTaskResult>();
  for (const task of taskResults.value) {
    const key = `${task.hotel_id}-${task.platform}`;
    const existing = groups.get(key);
    if (!existing) {
      groups.set(key, task);
    } else if (task.status === 'retry_success' && existing.status !== 'retry_success') {
      // retry_success beats failed/retry_failed — take retry result for final status
      groups.set(key, task);
    } else if (task.status === 'success' && existing.status === 'failed') {
      groups.set(key, task);
    }
  }
  return Array.from(groups.values());
}

// Cached aggregated results for template — avoids re-running the grouping in multiple places
const aggregatedResults = computed(() => aggregatedTaskResults());

function realStatusText() {
  if (!readiness.value?.active_real_platforms.length) return '未启用';
  if (readiness.value.ready_for_real) return '就绪';
  const missing = readiness.value.missing_real_urls.length;
  const invalid = readiness.value.invalid_real_urls.length;
  return `缺 ${missing} / 异常 ${invalid}`;
}

function readinessHint() {
  const current = readiness.value;
  if (!current) return '-';
  const firstMissing = current.missing_real_urls[0];
  if (firstMissing) return `${firstMissing.hotel_name}·${firstMissing.platform}: ${firstMissing.reason || '缺少 URL'}`;
  const firstInvalid = current.invalid_real_urls[0];
  if (firstInvalid) return `${firstInvalid.hotel_name}·${firstInvalid.platform}: ${firstInvalid.reason || 'URL 异常'}`;
  if (current.active_real_platforms.length) return current.messages[1] || current.messages[0] || '-';
  return current.messages[0] || '-';
}

function recentFailureHint() {
  const failedTask = aggregatedResults.value.find((task) => task.status !== 'success' && task.status !== 'retry_success');
  if (!failedTask) return '';
  const messageText = failedTask.error_message || '';
  if (/login|passport|登录|session/i.test(messageText)) {
    return `${failedTask.hotel_name} 抓取失败：携程登录可能已失效`;
  }
  if (/timeout|超时/i.test(messageText)) {
    return `${failedTask.hotel_name} 抓取超时：可等待下次定时或单酒店刷新`;
  }
  if (/URL|映射|mapping/i.test(messageText)) {
    return `${failedTask.hotel_name} 抓取失败：请检查携程 URL 配置`;
  }
  return `${failedTask.hotel_name} 抓取失败：${messageText || '请查看任务证据'}`;
}

function schedulerHealthText() {
  const health = scheduler.value?.scheduler_health;
  if (!health) return '-';
  if (health.status === 'ok') return '正常';
  if (health.status === 'disabled') return '未开启';
  if (health.status === 'down') return '未运行';
  if (health.status === 'running') return '抓取中';
  if (health.status === 'stale') return '过期';
  if (health.status === 'warning') return '注意';
  return health.status || '-';
}

function schedulerHealthClass() {
  const status = scheduler.value?.scheduler_health?.status;
  return {
    'text-green': status === 'ok',
    'text-red': status === 'down' || status === 'stale',
    'text-warning': status === 'warning' || status === 'running'
  };
}

function schedulerHealthHint() {
  const health = scheduler.value?.scheduler_health;
  if (!health || health.status === 'ok') return '';
  return health.message || '';
}

function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function formatTime(value: string) {
  const date = parseBackendDate(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

function parseBackendDate(value: string) {
  const hasTimezone = /(?:Z|[+-]\d{2}:?\d{2})$/.test(value);
  return new Date(hasTimezone ? value : `${value}Z`);
}

function durationText(startedAt: string, finishedAt: string | null) {
  if (!finishedAt) return '-';
  const started = parseBackendDate(startedAt).getTime();
  const finished = parseBackendDate(finishedAt).getTime();
  if (Number.isNaN(started) || Number.isNaN(finished) || finished < started) return '-';
  const seconds = Math.round((finished - started) / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return rest ? `${minutes}m${rest}s` : `${minutes}m`;
}

function durationSecondsText(seconds: number | null | undefined) {
  if (seconds == null) return '';
  const safeSeconds = Math.max(0, Math.round(seconds));
  if (safeSeconds < 60) return `${safeSeconds}s`;
  const minutes = Math.floor(safeSeconds / 60);
  const rest = safeSeconds % 60;
  return rest ? `${minutes}m${rest}s` : `${minutes}m`;
}

function runStatusText(status: string) {
  return runStatusLabels[status] || status;
}

function triggerTypeText(triggerType: string) {
  return triggerTypeLabels[triggerType] || triggerType;
}

function taskStatusText(status: string) {
  return taskStatusLabels[status] || status;
}

function runCountText(run: ScrapeRun) {
  const scopedCount = runTaskCounts.value[run.id];
  if (scopedCount) return `${scopedCount.ok}/${scopedCount.total}`;
  if (scrapeRuns.value[0]?.id === run.id && taskResults.value.length) {
    const ok = aggregatedResults.value.filter((task) => task.status === 'success' || task.status === 'retry_success').length;
    return `${ok}/${aggregatedResults.value.length}`;
  }
  return `${run.success_tasks}/${run.total_tasks}`;
}

function runTimeText(run: ScrapeRun) {
  const time = formatTime(run.finished_at || run.started_at);
  const duration = durationSecondsText(run.wall_time_s);
  return duration ? `${time} · ${duration}` : time;
}

function evidencePoints() {
  const points = selectedEvidence.value?.evidence?.points;
  return Array.isArray(points) ? points as EvidencePoint[] : [];
}

function activePoint() {
  return evidencePoints()[0] || null;
}

function scraperEvidence() {
  const point = activePoint();
  const value = point?.scraper_evidence;
  return value && typeof value === 'object' ? value as ScraperEvidence : null;
}

function selectedRoomText() {
  const selected = scraperEvidence()?.selected || activePoint()?.selected;
  if (!selected?.room || selected.price == null) return '-';
  return `${selected.room} ¥${selected.price}`;
}

function candidateItems() {
  const candidates = scraperEvidence()?.candidates;
  return Array.isArray(candidates) ? candidates as EvidenceCandidate[] : [];
}

function timingItems() {
  const timings = scraperEvidence()?.timings;
  if (!timings || typeof timings !== 'object') return [];
  return Object.entries(timings).map(([key, value]) => `${key} ${Number(value).toFixed(1)}s`);
}

function evidenceErrorText() {
  const evidence = selectedEvidence.value?.evidence;
  const topError = evidence?.error;
  if (typeof topError === 'string') return topError;
  const scraperError = scraperEvidence()?.error;
  return typeof scraperError === 'string' ? scraperError : '';
}

function pageSignalText() {
  const signals = scraperEvidence()?.page_signals;
  if (!signals || typeof signals !== 'object') return '';
  const items = [];
  if (signals.has_price) items.push('有价格');
  if (signals.has_room_summary) items.push('有房型摘要');
  if (signals.has_unlock_offer) items.push('解锁优惠');
  if (signals.has_login) items.push('登录提示');
  if (signals.has_verify) items.push('验证/风控');
  const textLength = typeof signals.text_length === 'number' ? signals.text_length : 0;
  items.push(`正文 ${textLength} 字`);
  return items.join(' · ');
}

function bodyExcerptText() {
  const signals = scraperEvidence()?.page_signals;
  if (!signals || typeof signals !== 'object') return '';
  const excerpt = signals.body_excerpt;
  return typeof excerpt === 'string' ? excerpt : '';
}

function ctripSessionStatus() {
  const session = readiness.value?.sessions?.find((s) => s.platform === 'ctrip');
  if (!session) return '未知';
  return session.has_session ? `已登录 (${session.cookie_count} cookies)` : '未登录';
}

async function loginCtrip() {
  if (loggingIn.value) return;
  loggingIn.value = true;
  message.value = '';
  try {
    const result = await api.loginCtrip();
    if (result.success) {
      message.value = result.message;
      await loadOperations();
    } else {
      message.value = result.message || '登录失败';
    }
  } catch (error) {
    message.value = error instanceof Error ? error.message : '登录失败';
  } finally {
    loggingIn.value = false;
  }
}

function nextJobTime() {
  const next = scheduler.value?.jobs.find((job) => job.next_run_time)?.next_run_time;
  return next ? formatTime(next) : '-';
}

function scheduledScopeText() {
  const scope = scheduler.value?.scheduled_scrape_scope;
  if (scope === 'today') return '今日';
  if (scope === 'future') return '远期';
  if (scope === 'all') return '全部';
  return scope || '-';
}

function timeoutText() {
  const manual = scrapeConfig.value?.scrape_fast_mapping_timeout;
  const scheduled = scrapeConfig.value?.scheduled_scrape_fast_mapping_timeout;
  if (manual == null && scheduled == null) return '-';
  return `手动 ${manual ?? '-'}s / 后台 ${scheduled ?? '-'}s`;
}

function fallbackWindowText() {
  const hours = scrapeConfig.value?.price_fallback_max_age_hours;
  if (hours == null) return '-';
  return `${hours}小时内`;
}

function scheduledRetryText() {
  if (!scrapeConfig.value) return '-';
  return scrapeConfig.value.scheduled_scrape_retry_failed_today ? '开启' : '关闭';
}

function lastSchedulerEventText() {
  const event = scheduler.value?.last_scheduler_event;
  if (!event) return '-';
  const duration = durationSecondsText(event.wall_time_s);
  const text = duration ? `${event.message}，耗时 ${duration}` : event.message;
  return event.finished_at ? `${formatTime(event.finished_at)} ${text}` : text;
}

function buildDiagnosticsText(latestBatch: Awaited<ReturnType<typeof api.fetchLatestScrape>>) {
  const currentReadiness = readiness.value;
  const currentScheduler = scheduler.value;
  const latestBackup = backups.value[0];
  return [
    '酒店竞对价格监控诊断',
    `生成时间：${new Date().toLocaleString('zh-CN')}`,
    `Mock：${currentReadiness?.ready_for_mock ? '就绪' : '待配置'}`,
    `真实：${realStatusText()}`,
    `提示：${readinessHint()}`,
    `最近失败：${recentFailureHint() || '-'}`,
    `抓取模式：${currentReadiness?.scraper_mode || '-'}`,
    `真实平台：${currentReadiness?.active_real_platforms.join(',') || '-'}`,
    `酒店/映射：${currentReadiness?.hotels_total ?? '-'} / ${currentReadiness?.mappings_total ?? '-'}`,
    `定时：${currentScheduler?.enabled ? '开启' : '关闭'}，进程${currentScheduler?.running ? '运行中' : '未运行'}，任务${currentScheduler?.jobs.length || 0}`,
    `定时范围：${scheduledScopeText()}`,
    `定时目标：${currentScheduler?.scheduled_target_hotel_count ?? '-'} 家`,
    `定时健康：${schedulerHealthText()}${currentScheduler?.scheduler_health?.message ? `（${currentScheduler.scheduler_health.message}）` : ''}`,
    `最近定时批次：${currentScheduler?.scheduler_health?.latest_scheduled_batch_id ? `#${currentScheduler.scheduler_health.latest_scheduled_batch_id} ${currentScheduler.scheduler_health.latest_scheduled_status || ''}` : '-'}`,
    `定时耗时：${durationSecondsText(currentScheduler?.last_scheduler_event?.wall_time_s) || '-'}`,
    `抓取超时：${timeoutText()}`,
    `后台补抓：${scheduledRetryText()}`,
    `兜底窗口：${fallbackWindowText()}`,
    `后台事件：${lastSchedulerEventText()}`,
    `下次任务：${nextJobTime()}`,
    `最近备份：${latestBackup ? `${formatTime(latestBackup.created_at)} ${formatSize(latestBackup.size_bytes)}` : '-'}`,
    `最新批次：${latestBatch ? `#${latestBatch.id} ${triggerTypeText(latestBatch.trigger_type)} ${latestBatch.status} ${latestBatch.success_tasks}/${latestBatch.total_tasks}` : '-'}`,
    `后端：${API_BASE}`
  ].join('\n');
}

async function loadOperations() {
  loading.value = true;
  message.value = '';
  try {
    const [schedulerResult, configResult, readinessResult, backupResult, runsResult] = await Promise.allSettled([
      api.fetchSchedulerStatus(),
      api.fetchScrapeConfig(),
      api.fetchScrapeReadiness(props.hotelIds),
      api.fetchBackups(),
      api.fetchScrapeRuns(3, props.hotelIds)
    ]);

    if (schedulerResult.status === 'fulfilled') scheduler.value = schedulerResult.value;
    if (configResult.status === 'fulfilled') scrapeConfig.value = configResult.value;
    if (readinessResult.status === 'fulfilled') readiness.value = readinessResult.value;
    if (backupResult.status === 'fulfilled') backups.value = backupResult.value.data.slice(0, 3);
    if (runsResult.status === 'fulfilled') {
      scrapeRuns.value = runsResult.value;
      const latestRun = runsResult.value[0];
      const currentIds = new Set(props.hotelIds || []);
      const taskEntries = await Promise.all(
        runsResult.value.map(async (run) => {
          try {
            const tasks = await api.fetchScrapeTaskResults(run.id);
            const scopedTasks = currentIds.size
              ? tasks.filter((task) => currentIds.has(task.hotel_id))
              : tasks;
            return [run.id, scopedTasks] as const;
          } catch {
            return [run.id, []] as const;
          }
        })
      );

      runTaskCounts.value = Object.fromEntries(
        taskEntries
          .filter(([, tasks]) => tasks.length)
          .map(([runId, tasks]) => {
            // Aggregate by (hotel_id, platform) for correct ok/total counts
            const groups = new Map<string, typeof tasks[number]>();
            for (const task of tasks) {
              const key = `${task.hotel_id}-${task.platform}`;
              const existing = groups.get(key);
              if (!existing) {
                groups.set(key, task);
              } else if (task.status === 'retry_success' && existing.status !== 'retry_success') {
                groups.set(key, task);
              } else if (task.status === 'success' && existing.status === 'failed') {
                groups.set(key, task);
              }
            }
            const aggregated = Array.from(groups.values());
            return [
              runId,
              {
                ok: aggregated.filter((task) => task.status === 'success' || task.status === 'retry_success').length,
                total: aggregated.length
              }
            ];
          })
      );

      if (latestRun) {
        taskResults.value = taskEntries.find(([runId]) => runId === latestRun.id)?.[1] || [];
        selectedEvidence.value = null;
      } else {
        taskResults.value = [];
        runTaskCounts.value = {};
      }
    }

    const failedCount = [schedulerResult, configResult, readinessResult, backupResult, runsResult].filter((item) => item.status === 'rejected').length;
    if (failedCount) message.value = `${failedCount} 项状态暂未加载`;
  } catch (error) {
    message.value = error instanceof Error ? error.message : '加载失败';
  } finally {
    loading.value = false;
  }
}

async function showEvidence(task: ScrapeTaskResult) {
  if (!task.has_evidence || loadingEvidenceId.value) return;
  if (selectedEvidence.value?.id === task.id) {
    selectedEvidence.value = null;
    return;
  }
  loadingEvidenceId.value = task.id;
  message.value = '';
  try {
    selectedEvidence.value = await api.fetchScrapeTaskEvidence(task.batch_id, task.id);
  } catch (error) {
    message.value = error instanceof Error ? error.message : '证据加载失败';
  } finally {
    loadingEvidenceId.value = null;
  }
}

interface EvidenceCandidate {
  room?: string;
  price?: number;
}

interface EvidenceSelection {
  room?: string | null;
  price?: number | null;
}

interface ScraperEvidence {
  source?: string;
  selected?: EvidenceSelection | null;
  candidates?: EvidenceCandidate[];
  timings?: Record<string, number>;
  error?: string;
  page_signals?: Record<string, unknown>;
}

interface EvidencePoint {
  check_in_date?: string;
  selected?: EvidenceSelection | null;
  scraper_evidence?: ScraperEvidence | null;
}

async function createBackup() {
  creating.value = true;
  message.value = '';
  try {
    const result = await api.createBackup();
    message.value = `已备份 ${result.filename}`;
    await loadOperations();
  } catch (error) {
    message.value = error instanceof Error ? error.message : '备份失败';
  } finally {
    creating.value = false;
  }
}

async function copyDiagnostics() {
  if (copying.value) return;
  copying.value = true;
  diagnosticLabel.value = '复制中';
  message.value = '';
  try {
    const latestBatch = await api.fetchLatestScrape(props.hotelIds);
    await writeClipboardText(buildDiagnosticsText(latestBatch));
    diagnosticLabel.value = '已复制';
  } catch (error) {
    diagnosticLabel.value = '复制失败';
    message.value = error instanceof Error ? error.message : '复制失败';
  } finally {
    setTimeout(() => {
      diagnosticLabel.value = '复制诊断';
      copying.value = false;
    }, 1400);
  }
}

onMounted(loadOperations);

watch(
  () => props.hotelIds?.join(',') || '',
  () => {
    void loadOperations();
  }
);
</script>

<template>
  <section class="operations-section">
    <div class="section-title">
      <span>运行状态</span>
      <button class="ghost-button" :disabled="loading" @click="loadOperations">
        {{ loading ? '刷新中' : '刷新' }}
      </button>
    </div>

    <div class="ops-body">
      <div class="ops-row">
        <span>定时</span>
        <strong>{{ scheduler?.enabled ? '开启' : '关闭' }}</strong>
      </div>
      <div class="ops-row">
        <span>进程</span>
        <strong>{{ scheduler?.running ? '运行中' : '未运行' }}</strong>
      </div>
      <div class="ops-row">
        <span>时间</span>
        <strong>{{ scheduler?.schedule_hours?.length ? scheduler.schedule_hours.join(', ') : '-' }}</strong>
      </div>
      <div class="ops-row">
        <span>范围</span>
        <strong>{{ scheduledScopeText() }}</strong>
      </div>
      <div class="ops-row">
        <span>超时</span>
        <strong>{{ timeoutText() }}</strong>
      </div>
      <div class="ops-row">
        <span>补抓</span>
        <strong>{{ scheduledRetryText() }}</strong>
      </div>
      <div class="ops-row">
        <span>兜底</span>
        <strong>{{ fallbackWindowText() }}</strong>
      </div>
      <div class="ops-row">
        <span>目标</span>
        <strong>{{ scheduler?.scheduled_target_hotel_count ?? '-' }} 家</strong>
      </div>
      <div class="ops-row">
        <span>任务</span>
        <strong>{{ scheduler?.jobs.length || 0 }}</strong>
      </div>
      <div class="ops-row">
        <span>下次</span>
        <strong>{{ nextJobTime() }}</strong>
      </div>
      <div class="ops-row">
        <span>后台</span>
        <strong class="truncate-strong" :title="lastSchedulerEventText()">{{ lastSchedulerEventText() }}</strong>
      </div>
      <div class="ops-row">
        <span>健康</span>
        <strong :class="schedulerHealthClass()">{{ schedulerHealthText() }}</strong>
      </div>
      <div v-if="schedulerHealthHint()" class="ops-hint warning">{{ schedulerHealthHint() }}</div>
      <div class="ops-row">
        <span>Mock</span>
        <strong>{{ readiness?.ready_for_mock ? '就绪' : '待配置' }}</strong>
      </div>
      <div class="ops-row">
        <span>真实</span>
        <strong>{{ realStatusText() }}</strong>
      </div>
      <div class="ops-hint">{{ readinessHint() }}</div>
      <div v-if="recentFailureHint()" class="ops-hint warning">{{ recentFailureHint() }}</div>

      <div class="ops-subtitle">携程登录</div>
      <div class="ops-row">
        <span>状态</span>
        <strong :class="{ 'text-green': readiness?.sessions?.find(s => s.platform === 'ctrip')?.has_session, 'text-red': !readiness?.sessions?.find(s => s.platform === 'ctrip')?.has_session }">
          {{ ctripSessionStatus() }}
        </strong>
      </div>
      <div class="ops-actions" style="margin-top: 6px;">
        <button class="primary-button backup-button" :disabled="loggingIn" @click="loginCtrip">
          {{ loggingIn ? '登录中...' : '打开携程登录' }}
        </button>
      </div>

      <div class="ops-subtitle">最近备份</div>
      <div v-if="!backups.length" class="ops-empty">暂无备份</div>
      <div v-for="backup in backups" :key="backup.filename" class="backup-item">
        <span>{{ formatTime(backup.created_at) }}</span>
        <strong>{{ formatSize(backup.size_bytes) }}</strong>
      </div>

      <div class="ops-actions">
        <button class="primary-button backup-button" :disabled="creating" @click="createBackup">
          {{ creating ? '备份中' : '立即备份' }}
        </button>
        <button class="ghost-button backup-button" :disabled="copying" @click="copyDiagnostics">
          {{ diagnosticLabel }}
        </button>
      </div>

      <div class="ops-subtitle">最近抓取</div>
      <div v-if="!scrapeRuns.length" class="ops-empty">暂无抓取记录</div>
      <div v-for="run in scrapeRuns" :key="run.id" class="scrape-run-item" :class="run.status">
        <span>#{{ run.id }} {{ triggerTypeText(run.trigger_type) }} {{ runStatusText(run.status) }}</span>
        <strong>{{ runCountText(run) }}</strong>
        <em>{{ runTimeText(run) }}</em>
      </div>

      <div class="ops-subtitle">任务明细</div>
      <div v-if="!aggregatedResults.length" class="ops-empty">暂无任务明细</div>
      <div v-for="task in aggregatedResults" :key="`${task.hotel_id}-${task.platform}`" class="task-result-item" :class="task.status">
        <div class="task-main">
          <span>{{ task.hotel_name }}</span>
          <strong>{{ taskStatusText(task.status) }} · {{ durationText(task.started_at, task.finished_at) }}</strong>
        </div>
        <div class="task-sub">
          {{ task.status === 'success' || task.status === 'retry_success' ? `记录 ${task.records_count} 条` : (task.error_message || '抓取失败') }}
        </div>
        <button
          v-if="task.has_evidence"
          class="evidence-button"
          :disabled="loadingEvidenceId === task.id"
          @click="showEvidence(task)"
        >
          {{ loadingEvidenceId === task.id ? '加载中' : selectedEvidence?.id === task.id ? '收起证据' : '查看证据' }}
        </button>
        <div v-if="selectedEvidence?.id === task.id" class="evidence-panel">
          <div class="evidence-row">
            <span>选中</span>
            <strong>{{ selectedRoomText() }}</strong>
          </div>
          <div v-if="activePoint()?.check_in_date" class="evidence-row">
            <span>日期</span>
            <strong>{{ activePoint()?.check_in_date }}</strong>
          </div>
          <div v-if="candidateItems().length" class="candidate-list">
            <div v-for="candidate in candidateItems()" :key="`${candidate.room}-${candidate.price}`" class="candidate-item">
              <span>{{ candidate.room || '-' }}</span>
              <strong>¥{{ candidate.price ?? '-' }}</strong>
            </div>
          </div>
          <div v-if="timingItems().length" class="timing-list">
            {{ timingItems().join(' · ') }}
          </div>
          <div v-if="pageSignalText()" class="signal-list">
            {{ pageSignalText() }}
          </div>
          <div v-if="evidenceErrorText()" class="evidence-error">
            {{ evidenceErrorText() }}
          </div>
          <div v-if="bodyExcerptText()" class="body-excerpt">
            {{ bodyExcerptText() }}
          </div>
        </div>
      </div>
      <div class="ops-message">{{ message }}</div>
    </div>
  </section>
</template>
