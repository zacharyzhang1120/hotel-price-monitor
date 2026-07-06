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
  saved: [selectMineHotelId?: number];
  selectMine: [hotelId: number];
}>();

const api = useApi();
const platforms: Platform[] = ['ctrip'];
const platformLabels: Record<Platform, string> = {
  ctrip: '携程'
};

const hotelId = ref<number | null>(null);
const platform = ref<Platform>('ctrip');
const mineHotelName = ref('');
const newMineHotelName = ref('');
const newCompetitorName = ref('');
const promoteHotelId = ref<number | null>(null);
const selectedCompetitorIds = ref<number[]>([]);
const hotelUrl = ref('');
const roomName = ref('');
const probeMode = ref<'mock' | 'real'>('mock');
const savingMineHotel = ref(false);
const creatingMineHotel = ref(false);
const creatingCompetitor = ref(false);
const promotingHotel = ref(false);
const savingCompetitors = ref(false);
const saving = ref(false);
const probing = ref(false);
const autoMatching = ref(false);
const groupAutoMatching = ref(false);
const deletingHotel = ref(false);
const message = ref('');

const myHotels = computed(() => props.hotels.filter((hotel) => hotel.is_mine));
const competitorHotels = computed(() => props.hotels.filter((hotel) => !hotel.is_mine));
const selectedMineHotel = computed(() => (
  myHotels.value.find((hotel) => hotel.id === props.mineHotelId) || myHotels.value[0] || null
));
const currentGroupHotels = computed(() => {
  const mine = selectedMineHotel.value;
  if (!mine) return [];
  const ids = new Set([mine.id, ...(mine.competitor_ids || [])]);
  return props.hotels.filter((hotel) => ids.has(hotel.id));
});
const currentGroupCompetitors = computed(() => {
  const ids = new Set(selectedCompetitorIds.value);
  return competitorHotels.value.filter((hotel) => ids.has(hotel.id));
});
const selectedHotel = computed(() => (
  currentGroupHotels.value.find((hotel) => hotel.id === hotelId.value) || selectedMineHotel.value
));
const selectedMapping = computed(() => (
  selectedHotel.value?.platform_mappings.find((item) => item.platform === platform.value) || null
));
const currentGroupMappingStatus = computed(() => currentGroupHotels.value.map((hotel) => {
  const mapping = hotel.platform_mappings.find((item) => item.platform === platform.value);
  return {
    hotel,
    hasUrl: Boolean(mapping?.hotel_url),
    label: hotel.is_mine ? '我方' : '竞对'
  };
}));
const missingUrlHotels = computed(() => currentGroupHotels.value.filter((hotel) => {
  const mapping = hotel.platform_mappings.find((item) => item.platform === platform.value);
  return !mapping?.hotel_url;
}));
const canAddCompetitor = computed(() => Boolean(selectedMineHotel.value) && selectedCompetitorIds.value.length < 5);

watch(
  () => [props.hotels, props.mineHotelId] as const,
  () => {
    if (selectedMineHotel.value) {
      mineHotelName.value = selectedMineHotel.value.name;
    } else {
      mineHotelName.value = '';
    }
    syncCompetitorFields();
    if (!currentGroupHotels.value.some((hotel) => hotel.id === hotelId.value)) {
      hotelId.value = selectedMineHotel.value?.id || currentGroupHotels.value[0]?.id || null;
    }
    syncMappingFields();
  },
  { immediate: true }
);

watch([hotelId, platform], () => {
  syncMappingFields();
  message.value = '';
});

function syncCompetitorFields() {
  selectedCompetitorIds.value = [...(selectedMineHotel.value?.competitor_ids || [])];
}

function syncMappingFields() {
  hotelUrl.value = selectedMapping.value?.hotel_url || '';
  roomName.value = selectedMapping.value?.default_room_name || '';
}

function selectMineGroup(hotelId: number) {
  emit('selectMine', hotelId);
  message.value = '';
}

function isCompetitorChecked(competitorId: number) {
  return selectedCompetitorIds.value.includes(competitorId);
}

function toggleCompetitor(competitorId: number, checked: boolean) {
  if (checked) {
    if (!canAddCompetitor.value || selectedCompetitorIds.value.includes(competitorId)) return;
    selectedCompetitorIds.value = [...selectedCompetitorIds.value, competitorId];
    return;
  }
  selectedCompetitorIds.value = selectedCompetitorIds.value.filter((item) => item !== competitorId);
}

function handleCompetitorChange(event: Event, competitorId: number) {
  toggleCompetitor(competitorId, Boolean((event.target as HTMLInputElement).checked));
}

async function saveMineHotel() {
  const mine = selectedMineHotel.value;
  if (!mine || !mineHotelName.value.trim()) return;
  savingMineHotel.value = true;
  message.value = '';
  try {
    await api.updateHotel(mine.id, {
      name: mineHotelName.value.trim(),
      is_mine: true
    });
    message.value = '我方门店已保存';
    emit('saved');
  } catch (error) {
    message.value = error instanceof Error ? error.message : '保存失败';
  } finally {
    savingMineHotel.value = false;
  }
}

async function createMineGroup() {
  if (!newMineHotelName.value.trim()) return;
  creatingMineHotel.value = true;
  message.value = '';
  try {
    const hotel = await api.createHotel({
      name: newMineHotelName.value.trim(),
      is_mine: true
    });
    newMineHotelName.value = '';
    hotelId.value = hotel.id;
    message.value = '门店组已新增';
    emit('selectMine', hotel.id);
    emit('saved', hotel.id);
  } catch (error) {
    message.value = error instanceof Error ? error.message : '新增失败';
  } finally {
    creatingMineHotel.value = false;
  }
}

async function promoteExistingHotelToMine() {
  if (!promoteHotelId.value) return;
  const targetId = promoteHotelId.value;
  promotingHotel.value = true;
  message.value = '';
  try {
    await api.updateHotel(targetId, { is_mine: true });
    await Promise.all(
      myHotels.value
        .filter((hotel) => hotel.competitor_ids.includes(targetId))
        .map((hotel) => api.updateHotelCompetitors(
          hotel.id,
          hotel.competitor_ids.filter((competitorId) => competitorId !== targetId)
        ))
    );
    promoteHotelId.value = null;
    hotelId.value = targetId;
    message.value = '已设为我方门店组';
    emit('selectMine', targetId);
    emit('saved', targetId);
  } catch (error) {
    message.value = error instanceof Error ? error.message : '设置失败';
  } finally {
    promotingHotel.value = false;
  }
}

async function createCompetitorForGroup() {
  const mine = selectedMineHotel.value;
  if (!mine || !newCompetitorName.value.trim() || !canAddCompetitor.value) return;
  creatingCompetitor.value = true;
  message.value = '';
  try {
    const hotel = await api.createHotel({
      name: newCompetitorName.value.trim(),
      is_mine: false
    });
    const competitorIds = [...selectedCompetitorIds.value, hotel.id];
    await api.updateHotelCompetitors(mine.id, competitorIds);
    selectedCompetitorIds.value = competitorIds;
    hotelId.value = hotel.id;
    newCompetitorName.value = '';
    message.value = '竞对门店已新增';
    emit('saved');
  } catch (error) {
    message.value = error instanceof Error ? error.message : '新增失败';
  } finally {
    creatingCompetitor.value = false;
  }
}

async function saveCompetitors() {
  const mine = selectedMineHotel.value;
  if (!mine) return;
  savingCompetitors.value = true;
  message.value = '';
  try {
    await api.updateHotelCompetitors(mine.id, selectedCompetitorIds.value);
    message.value = '竞对关系已保存';
    emit('saved');
  } catch (error) {
    message.value = error instanceof Error ? error.message : '保存失败';
  } finally {
    savingCompetitors.value = false;
  }
}

async function deleteSelectedHotel() {
  const hotel = selectedHotel.value;
  if (!hotel) return;
  const confirmed = window.confirm(`确认删除「${hotel.name}」？已有价格记录的酒店不会被删除。`);
  if (!confirmed) return;
  deletingHotel.value = true;
  message.value = '';
  try {
    await api.deleteHotel(hotel.id);
    if (hotel.id === selectedMineHotel.value?.id) {
      const nextMine = myHotels.value.find((item) => item.id !== hotel.id);
      if (nextMine) emit('selectMine', nextMine.id);
    }
    hotelId.value = selectedMineHotel.value?.id || null;
    message.value = '酒店已删除';
    emit('saved');
  } catch (error) {
    message.value = error instanceof Error ? error.message : '删除失败';
  } finally {
    deletingHotel.value = false;
  }
}

async function saveMapping() {
  const hotel = selectedHotel.value;
  if (!hotel || !hotelUrl.value.trim()) return;
  saving.value = true;
  message.value = '';
  try {
    await api.updatePlatformMapping(hotel.id, platform.value, {
      hotel_url: hotelUrl.value.trim(),
      default_room_name: roomName.value.trim() || null
    });
    message.value = '携程 URL 已保存';
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
  const hotel = selectedHotel.value;
  if (!hotel) return;
  autoMatching.value = true;
  message.value = '';
  try {
    const result = await api.autoMatchCtripMapping(hotel.id);
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
  const mine = selectedMineHotel.value;
  if (!mine) return;
  groupAutoMatching.value = true;
  message.value = '';
  try {
    const result = await api.autoMatchCtripGroup(mine.id);
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
      <span>门店组配置 <em class="title-meta">{{ selectedMineHotel?.name || '未配置我方门店' }}</em></span>
      <span class="config-message">{{ message }}</span>
    </div>

    <div class="group-editor-layout">
      <div class="group-sidebar">
        <div class="group-sidebar-title">门店组</div>
        <button
          v-for="hotel in myHotels"
          :key="hotel.id"
          class="group-list-item"
          :class="{ active: hotel.id === selectedMineHotel?.id }"
          :title="hotel.name"
          @click="selectMineGroup(hotel.id)"
        >
          <span>{{ hotel.name }}</span>
          <em>{{ hotel.competitor_ids.length }}/5</em>
        </button>
        <div v-if="!myHotels.length" class="group-empty">暂无门店组</div>
        <div class="group-create-row">
          <input v-model="newMineHotelName" type="text" placeholder="新我方门店" />
          <button
            class="ghost-button top-action-button"
            :disabled="creatingMineHotel || !newMineHotelName.trim()"
            @click="createMineGroup"
          >
            {{ creatingMineHotel ? '新增中' : '新增组' }}
          </button>
        </div>
        <div class="group-create-row">
          <select v-model.number="promoteHotelId">
            <option :value="null">已有酒店</option>
            <option v-for="hotel in competitorHotels" :key="hotel.id" :value="hotel.id">{{ hotel.name }}</option>
          </select>
          <button
            class="ghost-button top-action-button"
            :disabled="promotingHotel || !promoteHotelId"
            @click="promoteExistingHotelToMine"
          >
            {{ promotingHotel ? '设置中' : '设为我方' }}
          </button>
        </div>
      </div>

      <div class="group-main">
        <template v-if="selectedMineHotel">
          <div class="mapping-divider">我方门店</div>
          <div class="mapping-grid mine-grid">
            <label class="wide-field">
              <span>名称</span>
              <input v-model="mineHotelName" type="text" placeholder="我方门店名称" />
            </label>
          </div>
          <div class="mapping-actions">
            <button class="primary-button" :disabled="savingMineHotel || !mineHotelName.trim()" @click="saveMineHotel">
              {{ savingMineHotel ? '保存中' : '保存我方门店' }}
            </button>
          </div>

          <div class="mapping-divider">竞对门店</div>
          <div class="competitor-config">
            <div class="competitor-count">已选 {{ selectedCompetitorIds.length }}/5</div>
            <div v-if="currentGroupCompetitors.length" class="selected-competitor-row">
              <button
                v-for="hotel in currentGroupCompetitors"
                :key="hotel.id"
                class="selected-competitor-pill"
                :class="{ active: hotel.id === hotelId }"
                :title="hotel.name"
                @click="hotelId = hotel.id"
              >
                {{ hotel.name }}
              </button>
            </div>
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
            <div class="group-create-row">
              <input v-model="newCompetitorName" type="text" placeholder="新竞对门店" />
              <button
                class="ghost-button top-action-button"
                :disabled="creatingCompetitor || !newCompetitorName.trim() || !canAddCompetitor"
                @click="createCompetitorForGroup"
              >
                {{ creatingCompetitor ? '新增中' : '新增竞对' }}
              </button>
            </div>
          </div>
          <div class="mapping-actions">
            <button class="primary-button" :disabled="savingCompetitors" @click="saveCompetitors">
              {{ savingCompetitors ? '保存中' : '保存竞对关系' }}
            </button>
          </div>

          <div class="mapping-divider">携程 URL</div>
          <div class="config-help">
            <span v-if="missingUrlHotels.length">当前组还有 {{ missingUrlHotels.length }} 家缺 URL。</span>
            <span v-else>当前组 URL 已配置。</span>
            <button class="inline-link-button" :disabled="groupAutoMatching" @click="autoMatchCurrentGroup">
              {{ groupAutoMatching ? '匹配中' : '一键匹配当前组' }}
            </button>
          </div>

          <div v-if="currentGroupMappingStatus.length" class="group-url-status">
            <button
              v-for="item in currentGroupMappingStatus"
              :key="item.hotel.id"
              class="group-url-pill"
              :class="{ missing: !item.hasUrl, selected: item.hotel.id === selectedHotel?.id }"
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
              <span>平台</span>
              <select v-model="platform">
                <option v-for="item in platforms" :key="item" :value="item">{{ platformLabels[item] }}</option>
              </select>
            </label>

            <label>
              <span>当前酒店</span>
              <select v-model.number="hotelId">
                <option v-for="hotel in currentGroupHotels" :key="hotel.id" :value="hotel.id">
                  {{ hotel.is_mine ? '我方 | ' : '竞对 | ' }}{{ hotel.name }}
                </option>
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
            <button class="ghost-button top-action-button" :disabled="autoMatching || !selectedHotel" @click="autoMatchCtrip">
              {{ autoMatching ? '匹配中' : '自动匹配携程' }}
            </button>
            <button class="primary-button" :disabled="saving || !hotelUrl.trim()" @click="saveMapping">
              {{ saving ? '保存中' : '保存 URL' }}
            </button>
            <button class="ghost-button top-action-button" :disabled="probing || !hotelUrl.trim()" @click="probe">
              {{ probing ? '探测中' : '探测' }}
            </button>
            <button class="ghost-button top-action-button danger-button" :disabled="deletingHotel || !selectedHotel" @click="deleteSelectedHotel">
              {{ deletingHotel ? '删除中' : '删除当前酒店' }}
            </button>
          </div>
        </template>

        <div v-else class="config-empty-state">
          先新增一个我方门店组
        </div>
      </div>
    </div>
  </section>
</template>
