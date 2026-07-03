<script setup lang="ts">
import { computed } from 'vue';
import type { Hotel } from '../types';

const props = defineProps<{
  hotels: Hotel[];
  modelValue: number | null;
  mineHotelId: number | null;
}>();

const emit = defineEmits<{
  'update:modelValue': [value: number | null];
}>();

const myHotels = computed(() => props.hotels.filter((item) => item.is_mine));
const selectedMineHotel = computed(() => myHotels.value.find((item) => item.id === props.mineHotelId) || myHotels.value[0] || null);
const competitors = computed(() => {
  const mine = selectedMineHotel.value;
  if (!mine) return props.hotels.filter((item) => !item.is_mine);
  const linked = mine.competitor_ids || [];
  if (!linked.length) return props.hotels.filter((item) => !item.is_mine);
  return props.hotels.filter((item) => linked.includes(item.id));
});

</script>

<template>
  <div class="hotel-filter-row">
    <div class="tabs" role="tablist">
      <button :class="{ active: modelValue === null }" @click="emit('update:modelValue', null)">全部竞对</button>
      <button
        v-for="hotel in competitors"
        :key="hotel.id"
        :class="{ active: modelValue === hotel.id }"
        :title="hotel.name"
        @click="emit('update:modelValue', hotel.id)"
      >
        {{ hotel.name.replace(/^竞对/, '') }}
      </button>
    </div>
  </div>
</template>
