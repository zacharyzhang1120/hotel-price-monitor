<script setup lang="ts">
import { ref } from 'vue';
import { useApi } from '../composables/useApi';
import { writeClipboardText } from '../utils/clipboard';

const props = defineProps<{
  date: string;
  mineHotelId: number | null;
}>();

const api = useApi();
const label = ref('复制日报');
const loading = ref(false);

async function copyReport() {
  if (loading.value) return;
  loading.value = true;
  try {
    const text = await api.fetchWechatReport(props.date, props.mineHotelId);
    await writeClipboardText(text);
    label.value = '已复制';
  } catch (error) {
    label.value = '复制失败';
  } finally {
    setTimeout(() => {
      label.value = '复制日报';
      loading.value = false;
    }, 1400);
  }
}
</script>

<template>
  <button class="ghost-button top-action-button" :disabled="loading" @click="copyReport">
    {{ label }}
  </button>
</template>
