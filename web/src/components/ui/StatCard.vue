<script setup>
// StatCard — карточка-метрика (порт stat_card из widgets.py): крупное число + подпись.
defineProps({
  label: { type: String, required: true },
  value: { type: [String, Number], default: '—' },
  hint: { type: String, default: '' },
  icon: { type: [Object, Function], default: null },
  accent: { type: Boolean, default: false },
})
</script>

<template>
  <div class="rounded-lg border border-border bg-card p-5 shadow-card">
    <div class="flex items-start justify-between">
      <p class="text-[10px] font-medium uppercase tracking-wide text-text2">{{ label }}</p>
      <component :is="icon" v-if="icon" class="size-5" :class="accent ? 'text-accent' : 'text-text2'" />
    </div>
    <p class="mt-2 font-title text-[28px] font-extrabold leading-none" :class="accent ? 'text-accent' : 'text-text'">
      {{ value }}
    </p>
    <p v-if="hint" class="mt-1.5 text-xs text-text3">{{ hint }}</p>
  </div>
</template>
