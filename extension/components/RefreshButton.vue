<script setup lang="ts">
import { ref } from 'vue';
import { useApi } from '../composables/useApi';

const emit = defineEmits<{
  done: [];
  partial: [];
}>();

const api = useApi();
const isScraping = ref(false);
const label = ref('立即刷新');
const statusHint = ref('');

let lastCompletedTasks = 0;

function progressHint(successTasks: number, failedTasks: number, remainingTasks: number) {
  if (successTasks > 0 && failedTasks > 0) {
    return `今日价格已可用，${failedTasks} 项暂用最近有效价格，剩余 ${remainingTasks} 项`;
  }
  if (successTasks > 0) {
    return remainingTasks > 0 ? `今日价格已可用，剩余 ${remainingTasks} 项` : '今日价格已可用';
  }
  if (failedTasks > 0) {
    return `${failedTasks} 项暂用最近有效价格，剩余 ${remainingTasks} 项`;
  }
  return '';
}

async function refresh() {
  if (isScraping.value) return;
  isScraping.value = true;
  label.value = '启动中';
  statusHint.value = '';
  lastCompletedTasks = 0;
  try {
    const trigger = await api.triggerScrape();
    for (let i = 0; i < 120; i += 1) {
      const status = await api.getScrapeStatus(trigger.task_id);
      const successTasks = status.success_tasks || 0;
      const failedTasks = status.failed_tasks || 0;
      const completedTasks = status.completed_tasks || successTasks + failedTasks;
      const totalTasks = status.total_tasks || 0;
      const remainingTasks = Math.max(totalTasks - completedTasks, 0);

      // Show progress with detail
      if (status.progress && status.progress.includes('/')) {
        label.value = status.progress;
      } else {
        label.value = status.progress || '抓取中';
      }

      // Reload after each task ends; failed tasks keep using the latest valid fallback price.
      if (completedTasks > lastCompletedTasks) {
        lastCompletedTasks = completedTasks;
        statusHint.value = progressHint(successTasks, failedTasks, remainingTasks);
        emit('partial');
      }

      if (['completed', 'partial_success', 'failed'].includes(status.status)) {
        if (status.status === 'failed') throw new Error(status.error || '抓取失败');
        const batch = status.batch_id ? ` #${status.batch_id}` : '';
        label.value = status.status === 'partial_success' ? `今日可用${batch}` : `完成${batch}`;
        statusHint.value = status.status === 'partial_success'
          ? `${status.failed_tasks} 项未完成，已保留最近有效价格`
          : '今日价格已更新';
        emit('done');
        setTimeout(() => {
          label.value = '立即刷新';
        }, 2000);
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
    throw new Error('抓取超时');
  } catch (error) {
    label.value = '刷新失败';
    statusHint.value = '';
    setTimeout(() => {
      label.value = '立即刷新';
    }, 2200);
  } finally {
    isScraping.value = false;
  }
}
</script>

<template>
  <div class="refresh-group">
    <button class="primary-button" :disabled="isScraping" @click="refresh">
      {{ label }}
    </button>
    <span v-if="statusHint" class="status-hint">{{ statusHint }}</span>
  </div>
</template>
