<script setup lang="ts">
import { computed } from 'vue';
import type { CalendarPriceItem } from '../types';

const props = defineProps<{
  data: CalendarPriceItem[];
  mineHotelId: number | null;
  competitorIds: number[];
  futureDays: number;
}>();

const filteredData = computed(() => {
  if (!props.mineHotelId) return props.data;
  return props.data.filter((item) => {
    if (item.hotel_id === props.mineHotelId) return true;
    if (item.is_mine) return false;
    return props.competitorIds.length ? props.competitorIds.includes(item.hotel_id) : true;
  });
});

const dates = computed(() => Array.from(new Set(filteredData.value.map((item) => item.check_in_date))).sort());
const todayRows = computed(() => {
  const firstDate = dates.value[0];
  return firstDate ? filteredData.value.filter((item) => item.check_in_date === firstDate) : [];
});
const todayFallbackCount = computed(() => todayRows.value.filter((item) => item.is_fallback).length);
const todayMissingCount = computed(() => todayRows.value.filter((item) => item.cheapest_price === null).length);

const dailyRisks = computed(() =>
  dates.value.map((date) => {
    const rows = filteredData.value.filter((item) => item.check_in_date === date);
    const mineRows = rows.filter((item) => isCurrentMine(item) && item.cheapest_price !== null);
    const myLowest = mineRows.length ? Math.min(...mineRows.map((item) => item.cheapest_price as number)) : null;
    const competitors = rows.filter((item) => !isCurrentMine(item) && item.cheapest_price !== null);
    const lowestCompetitor = competitors
      .map((item) => ({
        hotelId: item.hotel_id,
        hotelName: item.hotel_name,
        room: item.cheapest_room,
        price: item.cheapest_price as number,
        diff: myLowest === null ? null : (item.cheapest_price as number) - myLowest
      }))
      .sort((a, b) => a.price - b.price)[0] || null;
    const lowerCompetitors = myLowest === null
      ? 0
      : new Set(competitors.filter((item) => (item.cheapest_price as number) < myLowest).map((item) => item.hotel_id)).size;
    const gap = lowestCompetitor && myLowest !== null ? myLowest - lowestCompetitor.price : null;
    let level: 'high' | 'medium' | 'low' = 'low';
    if (gap !== null && gap >= 50) level = 'high';
    else if (gap !== null && gap > 0) level = 'medium';
    return {
      date,
      myLowest,
      lowestCompetitor,
      lowerCompetitors,
      gap,
      level
    };
  })
);

const todayRisk = computed(() => dailyRisks.value[0] || null);
const futureRisks = computed(() => dailyRisks.value.slice(1));
const highRiskDays = computed(() => futureRisks.value.filter((item) => item.level === 'high'));
const mediumRiskDays = computed(() => futureRisks.value.filter((item) => item.level === 'medium'));

const riskLabel = computed(() => {
  if (!todayRisk.value || todayRisk.value.myLowest === null) return '暂无价格';
  if (todayFallbackCount.value || todayMissingCount.value) return '需复核';
  if (todayRisk.value.level === 'high') return '高风险';
  if (todayRisk.value.level === 'medium') return '需关注';
  return '稳定';
});

const advice = computed(() => {
  const risk = todayRisk.value;
  if (!risk || risk.myLowest === null) return '当前门店暂无可比价格，建议先完成抓取或检查平台链接。';
  if (!risk.lowestCompetitor) return '当前没有竞对价格可比，建议先配置当前门店的竞对酒店。';
  if (risk.gap !== null && risk.gap >= 50) {
    return `最低竞对比我方低 ¥${Math.round(risk.gap)}，建议重点检查库存、早餐/取消政策和房型权益，再决定是否跟价。`;
  }
  if (risk.gap !== null && risk.gap > 0) {
    return `有 ${risk.lowerCompetitors} 家竞对低于我方，差价不大，可先观察转化；需要抢量时可小幅下探。`;
  }
  return '今日我方起价不高于竞对最低价，建议维持当前价格，重点观察未来高风险日期。';
});

const futureText = computed(() => {
  if (highRiskDays.value.length) {
    return highRiskDays.value
      .slice(0, 3)
      .map((item) => `${formatDate(item.date)} 低 ¥${Math.round(item.gap || 0)}`)
      .join('，');
  }
  if (mediumRiskDays.value.length) {
    return mediumRiskDays.value
      .slice(0, 3)
      .map((item) => `${formatDate(item.date)} 有低价竞对`)
      .join('，');
  }
  return `未来 ${props.futureDays} 天暂未发现明显低价风险。`;
});

const qualityText = computed(() => {
  if (!todayRows.value.length) return '当前门店组暂无今日价格数据。';
  const notes = [];
  if (todayMissingCount.value) notes.push(`${todayMissingCount.value} 项缺价`);
  if (todayFallbackCount.value) notes.push(`${todayFallbackCount.value} 项使用最近有效价`);
  if (!notes.length) return '今日数据均来自当前最新批次，可直接用于巡检判断。';
  return `${notes.join('，')}，建议先查看任务明细或重新抓取后再做调价判断。`;
});

function isCurrentMine(item: CalendarPriceItem) {
  return props.mineHotelId ? item.hotel_id === props.mineHotelId : item.is_mine;
}

function formatDate(value: string) {
  return value.slice(5).replace('-', '/');
}

function money(value: number | null) {
  return value === null ? '-' : `¥${Math.round(value)}`;
}
</script>

<template>
  <section class="insight-section">
    <div class="section-title">
      <span>运营判断 <em class="title-meta">{{ riskLabel }}</em></span>
    </div>
    <div class="insight-grid">
      <div class="insight-card">
        <span>谁比我便宜</span>
        <strong v-if="todayRisk?.lowestCompetitor && todayRisk.gap !== null && todayRisk.gap > 0">
          {{ todayRisk.lowestCompetitor.hotelName }} 低 {{ money(todayRisk.gap) }}
        </strong>
        <strong v-else>今日暂无低价竞对</strong>
      </div>
      <div class="insight-card">
        <span>我该不该调价</span>
        <strong>{{ advice }}</strong>
      </div>
      <div class="insight-card">
        <span>未来 {{ props.futureDays }} 天异常</span>
        <strong>{{ futureText }}</strong>
      </div>
      <div class="insight-card">
        <span>数据可信度</span>
        <strong>{{ qualityText }}</strong>
      </div>
    </div>
  </section>
</template>
