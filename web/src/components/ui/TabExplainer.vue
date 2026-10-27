<script setup>
// TabExplainer — пояснение к разделу с непривычным понятием (ЗЕТ, риск отчисления).
//
// Одна строка видна всегда: что здесь и зачем. Как считается — под «Как это
// считается»: тому, кто уже знает, она не мешает читать таблицу, а тому, кто видит
// вкладку впервые, не нужно гадать по названию (живой прогон 23.10.2026: «ЗЕТ ·
// Перевод на курс» и «Риск отчисления» без единого слова о том, что там). Подсказка
// «наведите на плашку» здесь не годится: на телефоне наводить нечем.
// Раскрытие — родной `<details>`: работает с клавиатуры и экранным диктором без кода.
import { Info } from '@lucide/vue'

defineProps({
  lead: { type: String, required: true },
  more: { type: String, default: '' },
  moreLabel: { type: String, default: '' },
})
</script>

<template>
  <div class="flex gap-2.5 rounded-lg border border-border bg-card px-3 py-2.5 shadow-card">
    <Info class="mt-0.5 size-4 shrink-0 text-accent" aria-hidden="true" />
    <div class="min-w-0 text-sm leading-snug text-text2">
      <p>{{ lead }}</p>
      <details v-if="more" class="mt-1">
        <summary class="cursor-pointer font-semibold text-accent select-none pointer-coarse:py-2">{{ moreLabel }}</summary>
        <p class="mt-1 whitespace-pre-line">{{ more }}</p>
      </details>
    </div>
  </div>
</template>
