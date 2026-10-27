<script setup>
// GbMedal — медаль за 1–3 место вместо эмодзи: одинаковая на всех платформах, лента в
// цветах текущей темы. Номер места подписан и для диктора (aria-label).
import { computed } from 'vue'

const props = defineProps({ place: { type: Number, required: true } })

// Металл: светлая грань и тёмная обводка с цифрой.
const METAL = {
  1: ['#F7D872', '#B8860B'],
  2: ['#E6EBF0', '#8A97A5'],
  3: ['#EDB27F', '#9C5F2C'],
}
const metal = computed(() => METAL[props.place] || METAL[3])
</script>

<template>
  <svg viewBox="0 0 24 24" width="24" height="24" role="img" :aria-label="String(place)">
    <path d="M6.5 1.5h4.2l2.3 6.3H8.8Z" fill="var(--gb-accent)" />
    <path d="M17.5 1.5h-4.2L11 7.8h4.2Z" fill="var(--gb-accent2)" />
    <circle cx="12" cy="15" r="7" :fill="metal[0]" :stroke="metal[1]" stroke-width="1.5" />
    <text x="12" y="15.6" text-anchor="middle" dominant-baseline="central" font-size="9"
          font-weight="800" font-family="'DM Sans','Segoe UI',sans-serif" :fill="metal[1]">{{ place }}</text>
  </svg>
</template>
