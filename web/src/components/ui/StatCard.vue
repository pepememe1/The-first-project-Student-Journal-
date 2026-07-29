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
    <!-- ⚠️ Цифра — ОСНОВНЫМ шрифтом (DM Sans), не заголовочным. У Syne декоративные
         цифры: «3», «6», «7» с изломами, а «1» и «4» обычные — в ряду карточек одна
         метрика выглядела нарисованной, соседняя набранной, и читалось это как сбой
         шрифта. tabular-nums держит одинаковую ширину знаков, чтобы числа не «прыгали»
         при обновлении данных. -->
    <p class="mt-2 text-[28px] font-extrabold leading-none tabular-nums" :class="accent ? 'text-accent' : 'text-text'">
      {{ value }}
    </p>
    <p v-if="hint" class="mt-1.5 text-xs text-text3">{{ hint }}</p>
  </div>
</template>
