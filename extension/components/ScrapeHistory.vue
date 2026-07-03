<script setup lang="ts">
import { computed } from 'vue';
import type { ScrapeRun, ScrapeTaskResult } from '../types';

const props = defineProps<{
  runs: ScrapeRun[];
  taskResults: ScrapeTaskResult[];
}>();

const statusLabels: Record<string, string> = {
  success: '成功',
  partial_success: '部分成功',
  failed: '失败',
  running: '进行中'
};

function formatTime(value: string | null) {
  if (!value) return '--:--';
  const date = parseBackendDate(value);
  if (Number.isNaN(date.getTime())) return '--:--';
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
}

function parseBackendDate(value: string) {
  const hasTimezone = /(?:Z|[+-]\d{2}:?\d{2})$/.test(value);
  return new Date(hasTimezone ? value : `${value}Z`);
}

const failedTasks = computed(() => props.taskResults.filter((item) => item.status !== 'success'));

const detailText = computed(() => {
  if (!props.taskResults.length) return '暂无任务明细';
  if (!failedTasks.value.length) return `最近批次全部成功：${props.taskResults.length}/${props.taskResults.length}`;
  return failedTasks.value
    .slice(0, 2)
    .map((item) => `${item.hotel_name}-${item.platform}`)
    .join('、');
});
</script>

<template>
  <section class="runs-section">
    <div class="section-title compact-title">
      <span>最近批次</span>
    </div>
    <div v-if="!runs.length" class="runs-empty">暂无抓取记录</div>
    <div v-else class="runs-list">
      <div v-for="run in runs" :key="run.id" class="run-item" :class="run.status">
        <span class="run-status">{{ statusLabels[run.status] || run.status }}</span>
        <span>#{{ run.id }}</span>
        <span>{{ run.success_tasks }}/{{ run.total_tasks }}</span>
        <span>{{ formatTime(run.finished_at || run.started_at) }}</span>
      </div>
    </div>
    <div class="run-detail" :class="{ failed: failedTasks.length }">
      <span>{{ failedTasks.length ? `失败明细：${detailText}` : detailText }}</span>
    </div>
  </section>
</template>
