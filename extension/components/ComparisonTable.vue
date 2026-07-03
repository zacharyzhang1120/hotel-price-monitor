<script setup lang="ts">
import { computed } from 'vue';
import type { CalendarPriceItem } from '../types';
import { writeClipboardText } from '../utils/clipboard';

const props = defineProps<{
  data: CalendarPriceItem[];
  mineHotelId: number | null;
  competitorIds: number[];
  hotelFilter: number | null;
  refreshing: boolean;
}>();

const emit = defineEmits<{
  refreshHotel: [hotelId: number];
}>();

const platformLabels: Record<string, string> = {
  ctrip: '携程'
};

const todayData = computed(() => {
  const firstDate = [...new Set(props.data.map((item) => item.check_in_date))].sort()[0];
  const rows = props.data.filter((item) => item.check_in_date === firstDate);
  const base = props.mineHotelId
    ? rows.filter((item) => {
        if (item.hotel_id === props.mineHotelId) return true;
        if (item.is_mine) return false;
        return props.competitorIds.length ? props.competitorIds.includes(item.hotel_id) : true;
      })
    : rows;
  return props.hotelFilter ? base.filter((item) => item.hotel_id === props.hotelFilter || item.hotel_id === props.mineHotelId) : base;
});

const myPriceByPlatform = computed(() => {
  const map = new Map<string, number>();
  for (const item of todayData.value) {
    const isSelectedMine = props.mineHotelId ? item.hotel_id === props.mineHotelId : item.is_mine;
    if (isSelectedMine && item.cheapest_price !== null) map.set(item.platform, item.cheapest_price);
  }
  return map;
});

const myLowest = computed(() => {
  const mine = todayData.value.filter((item) => {
    const isSelectedMine = props.mineHotelId ? item.hotel_id === props.mineHotelId : item.is_mine;
    return isSelectedMine && item.cheapest_price !== null;
  });
  return mine.length ? Math.min(...mine.map((item) => item.cheapest_price as number)) : null;
});

const rows = computed(() =>
  [...todayData.value]
    .map((item) => {
      const myPlatformPrice = myPriceByPlatform.value.get(item.platform);
      return {
        ...item,
        diff: item.cheapest_price !== null && myPlatformPrice !== undefined ? item.cheapest_price - myPlatformPrice : null
      };
    })
    .sort((a, b) => (a.cheapest_price ?? Number.MAX_SAFE_INTEGER) - (b.cheapest_price ?? Number.MAX_SAFE_INTEGER))
);

const threatCount = computed(() => {
  if (myLowest.value === null) return 0;
  const lowestByHotel = new Map<number, number>();
  for (const item of todayData.value) {
    const isSelectedMine = props.mineHotelId ? item.hotel_id === props.mineHotelId : item.is_mine;
    if (isSelectedMine || item.cheapest_price === null) continue;
    const current = lowestByHotel.get(item.hotel_id);
    if (current === undefined || item.cheapest_price < current) lowestByHotel.set(item.hotel_id, item.cheapest_price);
  }
  return [...lowestByHotel.values()].filter((price) => price < (myLowest.value as number)).length;
});

const currentBatchCount = computed(() => todayData.value.filter((item) => item.is_current_batch).length);
const fallbackCount = computed(() => todayData.value.filter((item) => item.is_fallback).length);
const missingCount = computed(() => todayData.value.filter((item) => item.cheapest_price === null).length);
const totalCount = computed(() => todayData.value.length);

const freshnessText = computed(() => {
  const parts = [`本轮 ${currentBatchCount.value}/${totalCount.value}`];
  if (fallbackCount.value) parts.push(`兜底 ${fallbackCount.value}`);
  if (missingCount.value) parts.push(`缺价 ${missingCount.value}`);
  return parts.join(' · ');
});

function diffText(value: number | null) {
  if (value === null) return '-';
  if (value > 0) return `+¥${Math.round(value)}`;
  if (value < 0) return `-¥${Math.abs(Math.round(value))}`;
  return '¥0';
}

function priceText(value: number | null) {
  return value === null ? '-' : `¥${Math.round(value)}`;
}

function priceWithSource(item: CalendarPriceItem) {
  const suffix = item.is_fallback ? '（最近有效）' : '';
  return `${priceText(item.cheapest_price)}${suffix}`;
}

function taskReasonText(item: CalendarPriceItem) {
  const message = item.task_error_message || '';
  if (/timeout|超时/i.test(message)) return '抓取超时';
  if (/login|passport|登录|session/i.test(message)) return '登录失效';
  if (/URL|映射|mapping/i.test(message)) return '缺少URL';
  if (item.task_status === 'failed' || item.task_status === 'retry_failed') return '抓取失败';
  return '';
}

async function copyRows() {
  const text = [
    '酒店\t平台\t房型\t起价\tVS我方\t状态',
    ...rows.value.map((item) =>
      [
        item.hotel_name,
        platformLabels[item.platform],
        item.cheapest_room || '',
        priceWithSource(item),
        item.is_mine ? '-' : diffText(item.diff),
        taskReasonText(item)
      ].join('\t')
    )
  ].join('\n');
  await writeClipboardText(text);
}
</script>

<template>
  <section class="table-section">
    <div class="section-title">
      <span>今日价格对比 <em class="title-meta">低于我方 {{ threatCount }} 家 · {{ freshnessText }}</em></span>
      <button class="ghost-button" @click="copyRows">复制</button>
    </div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>酒店</th>
            <th>平台</th>
            <th>房型</th>
            <th>起价</th>
            <th>VS我方</th>
            <th>状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in rows" :key="`${item.hotel_id}-${item.platform}`" :class="{ mine: item.is_mine }">
            <td>{{ item.hotel_name }}</td>
            <td>{{ platformLabels[item.platform] }}</td>
            <td>{{ item.cheapest_room || '-' }}</td>
            <td>
              <span>{{ priceText(item.cheapest_price) }}</span>
              <span v-if="item.is_fallback" class="stale-price-tag">最近有效</span>
            </td>
            <td :class="{ lower: item.diff !== null && item.diff < 0, higher: item.diff !== null && item.diff > 0 }">
              {{ item.is_mine ? '-' : diffText(item.diff) }}
            </td>
            <td>
              <span v-if="taskReasonText(item)" class="stale-price-tag" :title="item.task_error_message || ''">
                {{ taskReasonText(item) }}
              </span>
              <span v-else>-</span>
            </td>
            <td>
              <button
                class="mini-action-button"
                :disabled="props.refreshing"
                @click="emit('refreshHotel', item.hotel_id)"
              >
                刷新
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>
