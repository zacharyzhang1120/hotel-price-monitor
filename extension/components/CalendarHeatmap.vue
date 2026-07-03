<script setup lang="ts">
import { computed } from 'vue';
import VChart from 'vue-echarts';
import { use } from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';
import { HeatmapChart } from 'echarts/charts';
import { GridComponent, TooltipComponent, VisualMapComponent } from 'echarts/components';
import type { CalendarPriceItem } from '../types';

use([CanvasRenderer, HeatmapChart, GridComponent, TooltipComponent, VisualMapComponent]);

const props = defineProps<{
  data: CalendarPriceItem[];
  mineHotelId: number | null;
  competitorIds: number[];
  hotelFilter: number | null;
  futureDays: number;
}>();

const platformLabels: Record<string, string> = {
  ctrip: '携程'
};

const filteredData = computed(() => {
  const base = props.mineHotelId
    ? props.data.filter((item) => {
        if (item.hotel_id === props.mineHotelId) return true;
        if (item.is_mine) return false;
        return props.competitorIds.length ? props.competitorIds.includes(item.hotel_id) : true;
      })
    : props.data;
  if (!props.hotelFilter) return base;
  return base.filter((item) => item.hotel_id === props.hotelFilter || item.hotel_id === props.mineHotelId);
});

const dates = computed(() => Array.from(new Set(filteredData.value.map((item) => item.check_in_date))).sort());
const firstDate = computed(() => dates.value[0] || '');
const futureMissingCount = computed(() =>
  filteredData.value.filter((item) => item.check_in_date !== firstDate.value && item.cheapest_price === null).length
);
const fallbackCount = computed(() => filteredData.value.filter((item) => item.is_fallback).length);

const rowKeys = computed(() => {
  const rows = filteredData.value.map((item) => `${item.hotel_id}|${item.platform}`);
  return Array.from(new Set(rows));
});

const rowLabels = computed(() =>
  rowKeys.value.map((key) => {
    const [hotelId, platform] = key.split('|');
    const item = filteredData.value.find((entry) => entry.hotel_id === Number(hotelId) && entry.platform === platform);
    return `${item?.hotel_name || '酒店'}-${platformLabels[platform] || platform}`;
  })
);

const myPriceByPlatformDate = computed(() => {
  const map = new Map<string, number>();
  for (const item of props.data) {
    const isSelectedMine = props.mineHotelId ? item.hotel_id === props.mineHotelId : item.is_mine;
    if (isSelectedMine && item.cheapest_price !== null) {
      map.set(`${item.platform}|${item.check_in_date}`, item.cheapest_price);
    }
  }
  return map;
});

const chartItems = computed(() =>
  filteredData.value.map((item) => {
    const rowIndex = rowKeys.value.indexOf(`${item.hotel_id}|${item.platform}`);
    const colIndex = dates.value.indexOf(item.check_in_date);
    const myPrice = myPriceByPlatformDate.value.get(`${item.platform}|${item.check_in_date}`);
    const diff = item.is_mine || item.cheapest_price === null || myPrice === undefined ? 0 : item.cheapest_price - myPrice;
    return {
      value: [colIndex, rowIndex, diff],
      item
    };
  })
);

const option = computed(() => ({
  tooltip: {
    formatter(params: any) {
      const item = params.data.item as CalendarPriceItem;
      const price = item.cheapest_price === null ? '-' : `¥${Math.round(item.cheapest_price)}`;
      const source = item.is_fallback ? '<br/>最近有效价格，非本轮新抓取' : '';
      const reason = taskReasonText(item);
      const reasonText = reason ? `<br/>状态：${reason}` : '';
      return `${item.hotel_name}<br/>${platformLabels[item.platform]} ${item.check_in_date}<br/>${item.cheapest_room || ''} ${price}${source}${reasonText}`;
    }
  },
  grid: { top: 16, left: 120, right: 24, bottom: 42 },
  xAxis: {
    type: 'category',
    data: dates.value.map((item) => item.slice(5)),
    axisTick: { show: false }
  },
  yAxis: {
    type: 'category',
    data: rowLabels.value,
    axisTick: { show: false },
    axisLabel: { width: 110, overflow: 'truncate' }
  },
  visualMap: {
    min: -120,
    max: 120,
    show: false,
    inRange: {
      color: ['#d94841', '#f1d77a', '#49a078']
    }
  },
  series: [
    {
      type: 'heatmap',
      data: chartItems.value,
      label: {
        show: true,
        formatter(params: any) {
          const item = params.data.item as CalendarPriceItem;
          return item.cheapest_price === null ? '-' : String(Math.round(item.cheapest_price));
        },
        color: '#1f2933',
        fontSize: 11
      },
      emphasis: {
        itemStyle: {
          borderColor: '#1f2933',
          borderWidth: 1
        }
      }
    }
  ]
}));

function taskReasonText(item: CalendarPriceItem) {
  const message = item.task_error_message || '';
  if (/timeout|超时/i.test(message)) return '抓取超时';
  if (/login|passport|登录|session/i.test(message)) return '登录失效';
  if (/URL|映射|mapping/i.test(message)) return '缺少URL';
  if (item.task_status === 'failed' || item.task_status === 'retry_failed') return '抓取失败';
  return '';
}

</script>

<template>
  <section class="chart-panel">
    <div class="section-title">
      <span>
        未来价格
        <em class="title-meta">
          今日 + 未来 {{ props.futureDays }} 天
          <template v-if="futureMissingCount"> · 远期缺 {{ futureMissingCount }} 项</template>
          <template v-if="fallbackCount"> · 最近有效 {{ fallbackCount }} 项</template>
        </em>
      </span>
    </div>
    <v-chart class="heatmap" :option="option" autoresize />
  </section>
</template>
