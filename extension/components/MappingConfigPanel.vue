<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useApi } from '../composables/useApi';
import type { Hotel, Platform } from '../types';

const props = defineProps<{
  hotels: Hotel[];
  date: string;
  mineHotelId: number | null;
}>();

const emit = defineEmits<{
  saved: [];
}>();

const api = useApi();
const platforms: Platform[] = ['ctrip'];
const platformLabels: Record<Platform, string> = {
  ctrip: '携程'
};

const hotelId = ref<number | null>(null);
const platform = ref<Platform>('ctrip');
const hotelName = ref('');
const hotelIsMine = ref(false);
const newHotelName = ref('');
const newHotelIsMine = ref(false);
const selectedCompetitorIds = ref<number[]>([]);
const hotelUrl = ref('');
const roomName = ref('');
const probeMode = ref<'mock' | 'real'>('mock');
const savingHotel = ref(false);
const creatingHotel = ref(false);
const deletingHotel = ref(false);
const savingCompetitors = ref(false);
const saving = ref(false);
const probing = ref(false);
const autoMatching = ref(false);
const groupAutoMatching = ref(false);
const message = ref('');

const selectedHotel = computed(() => props.hotels.find((hotel) => hotel.id === hotelId.value) || null);
const selectedMapping = computed(() => selectedHotel.value?.platform_mappings.find((item) => item.platform === platform.value) || null);
const myHotels = computed(() => props.hotels.filter((hotel) => hotel.is_mine));
const competitorHotels = computed(() => props.hotels.filter((hotel) => !hotel.is_mine));
const selectedMineForCompetitors = computed(() => myHotels.value.find((hotel) => hotel.id === props.mineHotelId) || myHotels.value[0] || null);
const currentConfigHotels = computed(() => {
  const mine = selectedMineForCompetitors.value;
  if (!mine) return props.hotels;
  const ids = new Set([mine.id, ...(mine.competitor_ids || [])]);
  return props.hotels.filter((hotel) => ids.has(hotel.id));
});
const currentGroupMappingStatus = computed(() => currentConfigHotels.value.map((hotel) => {
  const mapping = hotel.platform_mappings.find((item) => item.platform === platform.value);
  return {
    hotel,
    hasUrl: Boolean(mapping?.hotel_url),
    label: hotel.is_mine ? '我方' : '竞对'
  };
}));
const missingUrlHotels = computed(() => currentConfigHotels.value.filter((hotel) => {
  const mapping = hotel.platform_mappings.find((item) => item.platform === platform.value);
  return !mapping?.hotel_url;
}));

watch(
  () => [props.hotels, props.mineHotelId] as const,
  () => {
    if (!currentConfigHotels.value.some((hotel) => hotel.id === hotelId.value)) {
      hotelId.value = selectedMineForCompetitors.value?.id || currentConfigHotels.value[0]?.id || null;
    }
    syncHotelFields();
    syncMappingFields();
    syncCompetitorFields();
  },
  { immediate: true }
);

watch([hotelId, platform], () => {
  syncHotelFields();
  syncMappingFields();
  message.value = '';
});

function syncHotelFields() {
  hotelName.value = selectedHotel.value?.name || '';
  hotelIsMine.value = selectedHotel.value?.is_mine || false;
}

function syncMappingFields() {
  hotelUrl.value = selectedMapping.value?.hotel_url || '';
  roomName.value = selectedMapping.value?.default_room_name || '';
}

function syncCompetitorFields() {
  selectedCompetitorIds.value = [...(selectedMineForCompetitors.value?.competitor_ids || [])];
}

async function saveHotel() {
  if (!hotelId.value || !hotelName.value.trim()) return;
  savingHotel.value = true;
  message.value = '';
  try {
    await api.updateHotel(hotelId.value, {
      name: hotelName.value.trim(),
      is_mine: hotelIsMine.value
    });
    message.value = '酒店已保存';
    emit('saved');
  } catch (error) {
    message.value = error instanceof Error ? error.message : '保存失败';
  } finally {
    savingHotel.value = false;
  }
}

async function createHotel() {
  if (!newHotelName.value.trim()) return;
  creatingHotel.value = true;
  message.value = '';
  try {
    const hotel = await api.createHotel({
      name: newHotelName.value.trim(),
      is_mine: newHotelIsMine.value
    });
    hotelId.value = hotel.id;
    newHotelName.value = '';
    newHotelIsMine.value = false;
    message.value = '酒店已新增';
    emit('saved');
  } catch (error) {
    message.value = error instanceof Error ? error.message : '新增失败';
  } finally {
    creatingHotel.value = false;
  }
}

async function deleteSelectedHotel() {
  if (!hotelId.value || !selectedHotel.value) return;
  const confirmed = window.confirm(`确认删除「${selectedHotel.value.name}」？已有价格记录的酒店不会被删除。`);
  if (!confirmed) return;
  deletingHotel.value = true;
  message.value = '';
  try {
    await api.deleteHotel(hotelId.value);
    hotelId.value = props.hotels.find((hotel) => hotel.id !== hotelId.value)?.id || null;
    message.value = '酒店已删除';
    emit('saved');
  } catch (error) {
    message.value = error instanceof Error ? error.message : '删除失败';
  } finally {
    deletingHotel.value = false;
  }
}

function isCompetitorChecked(competitorId: number) {
  return selectedCompetitorIds.value.includes(competitorId);
}

function toggleCompetitor(competitorId: number, checked: boolean) {
  if (checked) {
    if (selectedCompetitorIds.value.length >= 5 || selectedCompetitorIds.value.includes(competitorId)) return;
    selectedCompetitorIds.value = [...selectedCompetitorIds.value, competitorId];
    return;
  }
  selectedCompetitorIds.value = selectedCompetitorIds.value.filter((item) => item !== competitorId);
}

function handleCompetitorChange(event: Event, competitorId: number) {
  toggleCompetitor(competitorId, Boolean((event.target as HTMLInputElement).checked));
}

async function saveCompetitors() {
  const mineHotelId = selectedMineForCompetitors.value?.id;
  if (!mineHotelId) return;
  savingCompetitors.value = true;
  message.value = '';
  try {
    await api.updateHotelCompetitors(mineHotelId, selectedCompetitorIds.value);
    message.value = '门店竞对已保存';
    emit('saved');
  } catch (error) {
    message.value = error instanceof Error ? error.message : '保存失败';
  } finally {
    savingCompetitors.value = false;
  }
}

async function saveMapping() {
  if (!hotelId.value || !hotelUrl.value.trim()) return;
  saving.value = true;
  message.value = '';
  try {
    await api.updatePlatformMapping(hotelId.value, platform.value, {
      hotel_url: hotelUrl.value.trim(),
      default_room_name: roomName.value.trim() || null
    });
    message.value = '已保存';
    emit('saved');
  } catch (error) {
    message.value = error instanceof Error ? error.message : '保存失败';
  } finally {
    saving.value = false;
  }
}

async function probe() {
  if (!hotelUrl.value.trim()) return;
  probing.value = true;
  message.value = '';
  try {
    const result = await api.probeScraper({
      platform: platform.value,
      hotel_url: hotelUrl.value.trim(),
      check_in_date: props.date,
      room_name: roomName.value.trim() || null,
      mode: probeMode.value
    });
    if (!result.success) {
      message.value = result.error || '探测失败';
      return;
    }
    const point = result.points[0];
    if (!point) {
      message.value = '探测成功';
      return;
    }
    const priceText = point.cheapest_price === null ? '价格未解析' : `¥${Math.round(point.cheapest_price)}`;
    message.value = `探测成功 ${point.cheapest_room || '-'} ${priceText}`;
  } catch (error) {
    message.value = error instanceof Error ? error.message : '探测失败';
  } finally {
    probing.value = false;
  }
}

async function autoMatchCtrip() {
  if (!hotelId.value) return;
  autoMatching.value = true;
  message.value = '';
  try {
    const result = await api.autoMatchCtripMapping(hotelId.value);
    if (!result.matched || !result.mapping) {
      const candidateText = result.candidates.length
        ? `候选：${result.candidates.slice(0, 3).map((item) => item.name).join('、')}`
        : '';
      message.value = `${result.message}${candidateText ? `；${candidateText}` : ''}`;
      return;
    }
    hotelUrl.value = result.mapping.hotel_url || '';
    roomName.value = result.mapping.default_room_name || '';
    message.value = result.message;
    emit('saved');
  } catch (error) {
    message.value = error instanceof Error ? error.message : '自动匹配失败';
  } finally {
    autoMatching.value = false;
  }
}

async function autoMatchCurrentGroup() {
  const mineHotelId = selectedMineForCompetitors.value?.id;
  if (!mineHotelId) return;
  groupAutoMatching.value = true;
  message.value = '';
  try {
    const result = await api.autoMatchCtripGroup(mineHotelId);
    message.value = `当前组匹配完成：新增 ${result.matched}，已存在 ${result.skipped}，失败 ${result.failed}`;
    emit('saved');
  } catch (error) {
    message.value = error instanceof Error ? error.message : '当前组匹配失败';
  } finally {
    groupAutoMatching.value = false;
  }
}
</script>

<template>
  <section class="mapping-section">
    <div class="section-title">
      <span>当前门店组 <em class="title-meta">{{ selectedMineForCompetitors?.name || '未配置我方门店' }}</em></span>
      <span class="config-message">{{ message }}</span>
    </div>
    <div class="config-help">
      一个门店组包含 1 个我方酒店和最多 5 个竞对酒店。酒店名称用于展示和分组；真实抓取仍需要每家酒店保存携程 URL。
      <span v-if="missingUrlHotels.length">当前组还有 {{ missingUrlHotels.length }} 家未配置 URL。</span>
      <button class="inline-link-button" :disabled="groupAutoMatching || !selectedMineForCompetitors" @click="autoMatchCurrentGroup">
        {{ groupAutoMatching ? '匹配中' : '一键匹配当前组' }}
      </button>
    </div>

    <div v-if="currentGroupMappingStatus.length" class="group-url-status">
      <button
        v-for="item in currentGroupMappingStatus"
        :key="item.hotel.id"
        class="group-url-pill"
        :class="{ missing: !item.hasUrl, selected: item.hotel.id === hotelId }"
        :title="item.hotel.name"
        @click="hotelId = item.hotel.id"
      >
        <strong>{{ item.label }}</strong>
        <span>{{ item.hotel.name }}</span>
        <em>{{ item.hasUrl ? '已配置' : '缺 URL' }}</em>
      </button>
    </div>

    <div class="mapping-grid">
      <label>
        <span>酒店</span>
        <select v-model.number="hotelId">
          <option v-for="hotel in currentConfigHotels" :key="hotel.id" :value="hotel.id">
            {{ hotel.is_mine ? '我方 | ' : '竞对 | ' }}{{ hotel.name }}
          </option>
        </select>
      </label>

      <label>
        <span>身份</span>
        <select v-model="hotelIsMine">
          <option :value="true">我方</option>
          <option :value="false">竞对</option>
        </select>
      </label>

      <label>
        <span>名称</span>
        <input v-model="hotelName" type="text" placeholder="酒店名称" />
      </label>
    </div>

    <div class="mapping-actions">
      <button class="primary-button" :disabled="savingHotel || !hotelName.trim()" @click="saveHotel">
        {{ savingHotel ? '保存中' : '保存酒店' }}
      </button>
      <button class="ghost-button top-action-button danger-button" :disabled="deletingHotel || !hotelId" @click="deleteSelectedHotel">
        {{ deletingHotel ? '删除中' : '删除酒店' }}
      </button>
    </div>

    <div class="mapping-divider">新增酒店</div>

    <div class="mapping-grid compact-grid">
      <label>
        <span>名称</span>
        <input v-model="newHotelName" type="text" placeholder="新竞对酒店" />
      </label>

      <label>
        <span>身份</span>
        <select v-model="newHotelIsMine">
          <option :value="false">竞对</option>
          <option :value="true">我方</option>
        </select>
      </label>
    </div>

    <div class="mapping-actions">
      <button class="ghost-button top-action-button" :disabled="creatingHotel || !newHotelName.trim()" @click="createHotel">
        {{ creatingHotel ? '新增中' : '新增酒店' }}
      </button>
    </div>

    <div class="mapping-divider">门店组竞对</div>

    <div class="competitor-config">
      <div class="competitor-count">已选 {{ selectedCompetitorIds.length }}/5</div>

      <div class="competitor-list">
        <label v-for="hotel in competitorHotels" :key="hotel.id" class="competitor-option">
          <input
            type="checkbox"
            :checked="isCompetitorChecked(hotel.id)"
            :disabled="!isCompetitorChecked(hotel.id) && selectedCompetitorIds.length >= 5"
            @change="handleCompetitorChange($event, hotel.id)"
          />
          <span>{{ hotel.name }}</span>
        </label>
        <div v-if="!competitorHotels.length" class="competitor-empty">暂无竞对酒店</div>
      </div>
    </div>

    <div class="mapping-actions">
      <button class="primary-button" :disabled="savingCompetitors || !selectedMineForCompetitors" @click="saveCompetitors">
        {{ savingCompetitors ? '保存中' : '保存竞对' }}
      </button>
    </div>

    <div class="mapping-divider">平台映射</div>

    <div class="mapping-grid">
      <label>
        <span>平台</span>
        <select v-model="platform">
          <option v-for="item in platforms" :key="item" :value="item">{{ platformLabels[item] }}</option>
        </select>
      </label>

      <label class="wide-field">
        <span>URL</span>
        <input v-model="hotelUrl" type="url" placeholder="https://..." />
      </label>

      <label>
        <span>房型</span>
        <input v-model="roomName" type="text" placeholder="起价房型" />
      </label>

      <label>
        <span>探测</span>
        <select v-model="probeMode">
          <option value="mock">Mock</option>
          <option value="real">真实</option>
        </select>
      </label>
    </div>

    <div class="mapping-actions">
      <button class="ghost-button top-action-button" :disabled="autoMatching || !hotelId" @click="autoMatchCtrip">
        {{ autoMatching ? '匹配中' : '自动匹配携程' }}
      </button>
      <button class="primary-button" :disabled="saving || !hotelUrl.trim()" @click="saveMapping">
        {{ saving ? '保存中' : '保存' }}
      </button>
      <button class="ghost-button top-action-button" :disabled="probing || !hotelUrl.trim()" @click="probe">
        {{ probing ? '探测中' : '探测' }}
      </button>
    </div>
  </section>
</template>
