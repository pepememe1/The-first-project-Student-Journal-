<script setup>
// Badge — пилюля-бейдж (порт QLabel#badge_* из styles.py).
import { computed } from 'vue'
const props = defineProps({ variant: { type: String, default: 'green' } }) // green | blue | red | muted
const VARIANTS = {
  green: 'bg-accent-glow text-accent border-accent',
  blue: 'bg-blue/10 text-blue border-blue',
  red: 'bg-red/10 text-red border-red',
  muted: 'bg-bg2 text-text2 border-border2',
}
const cls = computed(
  () => `inline-flex items-center rounded-full border px-3 py-1 text-tiny font-medium ${VARIANTS[props.variant] || VARIANTS.green}`,
)
</script>

<template>
  <span :class="cls"><slot /></span>
</template>
