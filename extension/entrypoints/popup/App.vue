<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue';
import CalendarHeatmap from '../../components/CalendarHeatmap.vue';
import ComparisonTable from '../../components/ComparisonTable.vue';
import HotelSelector from '../../components/HotelSelector.vue';
import InsightPanel from '../../components/InsightPanel.vue';
import MappingConfigPanel from '../../components/MappingConfigPanel.vue';
import OperationsPanel from '../../components/OperationsPanel.vue';
import { useApi } from '../../composables/useApi';
import type { CalendarPriceItem, Hotel, ScrapeConfig } from '../../types';
import { writeClipboardText } from '../../utils/clipboard';

const SELECTED_MINE_STORAGE_KEY = 'hotel-price-monitor:selected-mine-hotel-id';
const LATEST_SCRAPE_POLL_MS = 60_000;

const api = useApi();
const hotels = ref<Hotel[]>([]);
const calendarData = ref<CalendarPriceItem[]>([]);
const scrapeConfig = ref<ScrapeConfig | null>(null);
const selectedMineHotelId = ref<number | null>(null);
const hotelFilter = ref<number | null>(null);
const loading = ref(false);
const error = ref<string | null>(null);
const lastScrapeTime = ref<string | null>(null);
const lastScrapeStatus = ref<string | null>(null);
const lastScrapeTriggerType = ref<string | null>(null);
const lastScrapeBatchId = ref<number | null>(null);
const viewMode = ref<'monitor' | 'config' | 'insight'>('monitor');
const menuOpen = ref(false);
const reportLabel = ref('复制日报');
const refreshLabel = ref('立即刷新');
const futureRefreshLabel = ref('补抓远期');
const refreshHint = ref('');
const refreshNotice = ref('');
const reportFallbackText = ref('');
const reportFallbackRef = ref<HTMLTextAreaElement | null>(null);
const isScraping = ref(false);
const latestPollTimer = ref<number | null>(null);

const today = computed(() => formatLocalDate(new Date()));
const myHotels = computed(() => hotels.value.filter((hotel) => hotel.is_mine));
const selectedMineHotel = computed(() => myHotels.value.find((hotel) => hotel.id === selectedMineHotelId.value) || myHotels.value[0] || null);
const selectedCompetitorIds = computed(() => selectedMineHotel.value?.competitor_ids || []);
const selectedGroupHotelIds = computed(() => (
  selectedMineHotel.value ? [selectedMineHotel.value.id, ...selectedCompetitorIds.value] : []
));
const futureDays = computed(() => scrapeConfig.value?.future_days ?? 7);
const calendarDays = computed(() => futureDays.value + 1);
const scrapeWaitSeconds = computed(() => {
  const totalHotels = Math.max(selectedGroupHotelIds.value.length || hotels.value.length || 6, 1);
  const mappingTimeout = scrapeConfig.value?.scrape_mapping_timeout ?? 180;
  return Math.max(600, totalHotels * mappingTimeout + 60);
});

const statusText = computed(() => {
  if (loading.value) return '加载中';
  const time = formatTime(lastScrapeTime.value);
  const source = lastScrapeTriggerType.value === 'scheduled'
    ? '定时'
    : lastScrapeTriggerType.value === 'manual'
      ? '手动'
      : '最近';
  if (lastScrapeStatus.value === 'failed') return `${source}失败 ${time}`;
  return `${source}抓取 ${time}`;
});

function formatLocalDate(value: Date) {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, '0');
  const day = String(value.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function formatTime(value: string | null) {
  if (!value) return '未加载';
  const date = parseBackendDate(value);
  if (Number.isNaN(date.getTime())) return '--:--';
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
}

function parseBackendDate(value: string) {
  const hasTimezone = /(?:Z|[+-]\d{2}:?\d{2})$/.test(value);
  return new Date(hasTimezone ? value : `${value}Z`);
}

function buildRefreshHint(
  successTasks: number,
  failedTasks: number,
  remainingTasks: number,
  scope: 'today' | 'future' | 'all'
) {
  if (scope === 'future') {
    if (successTasks > 0 && failedTasks > 0) {
      return `远期已更新 ${successTasks} 项，${failedTasks} 项未完成，剩余 ${remainingTasks} 项`;
    }
    if (successTasks > 0) {
      return remainingTasks > 0 ? `远期已更新 ${successTasks} 项，剩余 ${remainingTasks} 项` : '远期价格已更新';
    }
    if (failedTasks > 0) {
      return `远期 ${failedTasks} 项未完成，剩余 ${remainingTasks} 项`;
    }
    return '';
  }
  if (successTasks > 0 && failedTasks > 0) {
    return `今日价格已可用，${failedTasks} 项暂用最近有效价格，剩余 ${remainingTasks} 项继续处理`;
  }
  if (successTasks > 0) {
    return remainingTasks > 0
      ? `今日价格已可用，剩余 ${remainingTasks} 项继续处理`
      : `今日价格已可用`;
  }
  if (failedTasks > 0) {
    return `${failedTasks} 项暂用最近有效价格，剩余 ${remainingTasks} 项继续处理`;
  }
  return '';
}

function buildFinalRefreshMessage(status: {
  status: string;
  success_tasks: number;
  failed_tasks: number;
  total_tasks: number;
  batch_id: number | null;
}, scope: 'today' | 'future' | 'all') {
  const batch = status.batch_id ? ` #${status.batch_id}` : '';
  if (scope === 'future') {
    if (status.status === 'completed') {
      return `远期补抓完成${batch}：未来价格已更新`;
    }
    if (status.status === 'partial_success' && status.success_tasks > 0) {
      return `远期部分完成${batch}：${status.failed_tasks} 项未完成，今日价格不受影响`;
    }
    return `远期补抓未完成${batch}：今日价格不受影响`;
  }
  if (status.status === 'completed') {
    return scope === 'all'
      ? `抓取完成${batch}：今日和远期价格已更新`
      : `抓取完成${batch}：今日价格已更新`;
  }
  if (status.status === 'partial_success' && status.success_tasks > 0) {
    return `今日价格已可用${batch}：${status.failed_tasks} 项未完成，已保留最近有效价格，可在任务明细查看原因`;
  }
  return `抓取未完成${batch}：请在任务明细查看失败原因`;
}

async function loadAll() {
  loading.value = true;
  error.value = null;
  try {
    const config = await api.fetchScrapeConfig();
    scrapeConfig.value = config;
    const hotelResult = await api.fetchHotels();

    hotels.value = hotelResult;
    ensureSelectedMineHotel();

    await Promise.all([loadCalendarForCurrentGroup(), loadLatestForCurrentGroup()]);
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载失败';
  } finally {
    loading.value = false;
  }
}

async function loadLatestForCurrentGroup() {
  if (!selectedGroupHotelIds.value.length) {
    lastScrapeTime.value = null;
    lastScrapeStatus.value = null;
    lastScrapeTriggerType.value = null;
    lastScrapeBatchId.value = null;
    return;
  }
  const latest = await api.fetchLatestScrape(selectedGroupHotelIds.value);
  lastScrapeTime.value = latest?.finished_at || latest?.started_at || null;
  lastScrapeStatus.value = latest?.status || null;
  lastScrapeTriggerType.value = latest?.trigger_type || null;
  lastScrapeBatchId.value = latest?.id || null;
}

async function loadCalendarForCurrentGroup() {
  if (!selectedGroupHotelIds.value.length) {
    calendarData.value = [];
    return;
  }
  const calendar = await api.fetchCalendar(today.value, calendarDays.value, selectedGroupHotelIds.value);
  calendarData.value = calendar.data;
}

function ensureSelectedMineHotel() {
  if (!myHotels.value.length) {
    selectedMineHotelId.value = null;
    hotelFilter.value = null;
    return;
  }
  if (selectedMineHotelId.value && myHotels.value.some((hotel) => hotel.id === selectedMineHotelId.value)) {
    return;
  }
  const storedMineHotelId = Number(window.localStorage.getItem(SELECTED_MINE_STORAGE_KEY));
  if (storedMineHotelId && myHotels.value.some((hotel) => hotel.id === storedMineHotelId)) {
    selectedMineHotelId.value = storedMineHotelId;
    return;
  }
  selectedMineHotelId.value = myHotels.value[0].id;
}

function switchView(mode: 'monitor' | 'config' | 'insight') {
  viewMode.value = mode;
  menuOpen.value = false;
}

function selectMineHotel(hotelId: number) {
  selectedMineHotelId.value = hotelId;
}

async function copyReport() {
  if (reportLabel.value !== '复制日报') return;
  reportLabel.value = '复制中';
  let reportText = '';
  try {
    reportText = await api.fetchWechatReport(today.value, selectedMineHotelId.value);
    await writeClipboardText(reportText);
    reportLabel.value = '已复制';
    refreshNotice.value = '日报已复制，可以直接粘贴到微信';
    reportFallbackText.value = '';
  } catch (err) {
    reportLabel.value = '复制失败';
    if (reportText) {
      reportFallbackText.value = reportText;
      await nextTick();
      reportFallbackRef.value?.focus();
      reportFallbackRef.value?.select();
      refreshNotice.value = '复制失败：已展开日报文本，可手动选中复制';
    } else {
      refreshNotice.value = err instanceof Error ? err.message : '复制失败：浏览器没有允许写入剪贴板';
    }
  } finally {
    setTimeout(() => {
      reportLabel.value = '复制日报';
    }, 1400);
  }
}

async function refreshPrices(hotelIds?: number[], scope: 'today' | 'future' | 'all' = 'today') {
  if (isScraping.value) return;
  const targetHotelIds = hotelIds?.length ? hotelIds : selectedGroupHotelIds.value;
  if (!targetHotelIds.length) {
    refreshNotice.value = '请先选择或配置一个我方门店组';
    return;
  }
  isScraping.value = true;
  refreshLabel.value = scope === 'future' ? '远期启动中' : '启动中';
  futureRefreshLabel.value = scope === 'future' ? '远期启动中' : '补抓远期';
  refreshHint.value = '';
  refreshNotice.value = '';
  let lastCompletedTasks = 0;
  try {
    const trigger = await api.triggerScrape(targetHotelIds, scope);
    for (let i = 0; i < scrapeWaitSeconds.value; i += 2) {
      const status = await api.getScrapeStatus(trigger.task_id);
      refreshLabel.value = status.progress || '抓取中';
      const successTasks = status.success_tasks || 0;
      const failedTasks = status.failed_tasks || 0;
      const completedTasks = status.completed_tasks || successTasks + failedTasks;
      const totalTasks = status.total_tasks || hotels.value.length || 0;
      const remainingTasks = Math.max(totalTasks - completedTasks, 0);

      // Reload calendar when successful hotels complete; failed hotels use fallback prices.
      if (completedTasks > lastCompletedTasks) {
        lastCompletedTasks = completedTasks;
        const hint = buildRefreshHint(successTasks, failedTasks, remainingTasks, scope);
        if (hint) {
          refreshHint.value = hint;
          refreshNotice.value = hint;
        }
        if (successTasks > 0 || failedTasks > 0) {
          api.fetchCalendar(today.value, calendarDays.value, targetHotelIds).then((cal) => {
            calendarData.value = cal.data;
          }).catch(() => {});
        }
      }

      if (['completed', 'partial_success', 'failed'].includes(status.status)) {
        if (status.status === 'failed') throw new Error(status.error || '抓取失败');
        refreshLabel.value = scope === 'future'
          ? (status.status === 'partial_success' ? '远期部分完成' : '远期完成')
          : (status.status === 'partial_success' ? '今日可用' : '完成');
        futureRefreshLabel.value = refreshLabel.value;
        refreshHint.value = buildFinalRefreshMessage(status, scope);
        refreshNotice.value = refreshHint.value;
        await loadAll();
        setTimeout(() => {
          refreshLabel.value = '立即刷新';
          futureRefreshLabel.value = '补抓远期';
        }, 2000);
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, 2000));
    }
    throw new Error('抓取超时');
  } catch {
    refreshLabel.value = '刷新失败';
    futureRefreshLabel.value = scope === 'future' ? '远期失败' : '补抓远期';
    refreshHint.value = '';
    refreshNotice.value = scope === 'future'
      ? '远期补抓失败：今日价格不受影响，可在任务明细查看原因'
      : '刷新失败：请在任务明细查看原因或稍后重试';
    setTimeout(() => {
      refreshLabel.value = '立即刷新';
      futureRefreshLabel.value = '补抓远期';
    }, 2200);
  } finally {
    isScraping.value = false;
    menuOpen.value = false;
  }
}

function refreshHotel(hotelId: number) {
  refreshPrices([hotelId], 'today');
}

async function refreshIfLatestBatchChanged() {
  if (loading.value || isScraping.value || !selectedGroupHotelIds.value.length) return;
  try {
    const latest = await api.fetchLatestScrape(selectedGroupHotelIds.value);
    const latestId = latest?.id || null;
    const previousId = lastScrapeBatchId.value;
    lastScrapeTime.value = latest?.finished_at || latest?.started_at || null;
    lastScrapeStatus.value = latest?.status || null;
    lastScrapeTriggerType.value = latest?.trigger_type || null;
    lastScrapeBatchId.value = latestId;
    if (latestId && previousId && latestId !== previousId) {
      await loadCalendarForCurrentGroup();
      const source = latest?.trigger_type === 'scheduled' ? '后台定时' : '手动';
      refreshNotice.value = `${source}抓取已更新 #${latestId}`;
    }
  } catch {
    // Keep the current view; the next poll or manual refresh can recover.
  }
}

function startLatestPolling() {
  if (latestPollTimer.value !== null) {
    window.clearInterval(latestPollTimer.value);
  }
  latestPollTimer.value = window.setInterval(() => {
    void refreshIfLatestBatchChanged();
  }, LATEST_SCRAPE_POLL_MS);
}

watch(selectedMineHotelId, () => {
  hotelFilter.value = null;
  lastScrapeBatchId.value = null;
  if (selectedMineHotelId.value) {
    window.localStorage.setItem(SELECTED_MINE_STORAGE_KEY, String(selectedMineHotelId.value));
  } else {
    window.localStorage.removeItem(SELECTED_MINE_STORAGE_KEY);
  }
  if (!loading.value) {
    void Promise.all([loadCalendarForCurrentGroup(), loadLatestForCurrentGroup()]).catch((err) => {
      error.value = err instanceof Error ? err.message : '加载价格失败';
    });
  }
});

onMounted(() => {
  void loadAll();
  startLatestPolling();
});

onUnmounted(() => {
  if (latestPollTimer.value !== null) {
    window.clearInterval(latestPollTimer.value);
    latestPollTimer.value = null;
  }
});
</script>

<template>
  <main class="app-shell">
    <header class="topbar">
      <div class="brand-title">
        <h1>酒店竞对价格监控</h1>
        <label class="top-mine-select">
          <select v-model.number="selectedMineHotelId">
            <option v-if="!myHotels.length" :value="null">未配置我方门店</option>
            <option v-for="hotel in myHotels" :key="hotel.id" :value="hotel.id">{{ hotel.name }}</option>
          </select>
        </label>
        <div class="action-menu-wrap">
          <button class="menu-trigger" @click="menuOpen = !menuOpen">操作</button>
          <div v-if="menuOpen" class="action-menu">
            <div class="menu-status" :class="{ failed: lastScrapeStatus === 'failed' }">{{ statusText }}</div>
            <button :class="{ active: viewMode === 'monitor' }" @click="switchView('monitor')">巡检页面</button>
            <button :class="{ active: viewMode === 'config' }" @click="switchView('config')">配置</button>
            <button :class="{ active: viewMode === 'insight' }" @click="switchView('insight')">运营判断</button>
            <button @click="copyReport">{{ reportLabel }}</button>
            <button :disabled="isScraping" @click="refreshPrices(selectedGroupHotelIds, 'today')">{{ refreshLabel }}</button>
            <button :disabled="isScraping" @click="refreshPrices(selectedGroupHotelIds, 'future')">{{ futureRefreshLabel }}</button>
            <span v-if="refreshHint" class="refresh-hint">{{ refreshHint }}</span>
          </div>
        </div>
      </div>
    </header>

    <HotelSelector
      v-if="viewMode === 'monitor'"
      v-model="hotelFilter"
      :hotels="hotels"
      :mine-hotel-id="selectedMineHotelId"
    />

    <div v-if="error" class="error-banner">{{ error }}</div>
    <div v-if="refreshNotice" class="refresh-notice">{{ refreshNotice }}</div>
    <textarea
      v-if="reportFallbackText"
      ref="reportFallbackRef"
      class="report-fallback"
      readonly
      :value="reportFallbackText"
      aria-label="日报文本"
    />

    <template v-if="viewMode === 'monitor'">
      <CalendarHeatmap
        :data="calendarData"
        :mine-hotel-id="selectedMineHotelId"
        :competitor-ids="selectedCompetitorIds"
        :hotel-filter="hotelFilter"
        :future-days="futureDays"
      />

      <ComparisonTable
        :data="calendarData"
        :mine-hotel-id="selectedMineHotelId"
        :competitor-ids="selectedCompetitorIds"
        :hotel-filter="hotelFilter"
        :refreshing="isScraping"
        @refresh-hotel="refreshHotel"
      />
    </template>

    <div v-else-if="viewMode === 'config'" class="config-view">
      <MappingConfigPanel
        :hotels="hotels"
        :date="today"
        :mine-hotel-id="selectedMineHotelId"
        @saved="loadAll"
        @select-mine="selectMineHotel"
      />
      <OperationsPanel :hotel-ids="selectedGroupHotelIds" />
    </div>

    <div v-else class="insight-view">
      <InsightPanel
        :data="calendarData"
        :mine-hotel-id="selectedMineHotelId"
        :competitor-ids="selectedCompetitorIds"
        :future-days="futureDays"
      />
    </div>
  </main>
</template>
