<script setup>
// Gauge — кольцевой индикатор среднего балла (0..max) на чистом SVG, без библиотек.
// Цвет кольца — по уровню оценки (5 → акцент, 4 → синий, 3 → оранж, <3 → красный).
import { computed } from 'vue'
const props = defineProps({
  value: { type: Number, default: 0 },
  max: { type: Number, default: 5 },
  size: { type: Number, default: 128 },
})
const R = 52
const CIRC = 2 * Math.PI * R
const pct = computed(() => Math.max(0, Math.min(1, (props.value || 0) / props.max)))
const dash = computed(() => `${CIRC * pct.value} ${CIRC}`)
const color = computed(() => {
  const v = props.value || 0
  if (v >= 4.5) return 'var(--gb-accent)'
  if (v >= 3.5) return '#3b82f6'
  if (v >= 3) return '#f59e0b'
  if (v > 0) return '#ef4444'
  return 'var(--gb-border2)'
})
</script>

<template>
  <svg :width="size" :height="size" viewBox="0 0 120 120">
    <g transform="rotate(-90 60 60)">
      <circle cx="60" cy="60" :r="R" fill="none" stroke="var(--gb-bg2)" stroke-width="10" />
      <circle cx="60" cy="60" :r="R" fill="none" :stroke="color" stroke-width="10" stroke-linecap="round"
              :stroke-dasharray="dash" style="transition: stroke-dasharray 0.7s ease, stroke 0.3s ease" />
    </g>
    <text x="60" y="60" text-anchor="middle" dominant-baseline="central"
          fill="var(--gb-text)" style="font-size: 27px; font-weight: 800">{{ (value || 0).toFixed(1) }}</text>
  </svg>
</template>
