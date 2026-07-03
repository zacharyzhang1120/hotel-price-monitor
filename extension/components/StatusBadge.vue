<script setup lang="ts">
defineProps<{
  lastUpdated: string | null;
  status: string | null;
  loading: boolean;
}>();

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
</script>

<template>
  <div class="status-badge" :class="{ loading, failed: status === 'failed' }">
    <span class="dot"></span>
    <span>{{ loading ? '加载中' : `最近抓取 ${formatTime(lastUpdated)}` }}</span>
  </div>
</template>
