<script setup>
// ZetProgress — переиспользуемый прогресс ЗЕТ (docs/PLAN-ZET.md §7.5): дашборд студента,
// отчёт куратора, кабинет родителя. Пусто (total=0) — компонент НЕ рендерит себя вовсе,
// вызывающая сторона должна сама не монтировать его, пока ни один предмет не имеет ЗЕТ
// (см. docs/PLAN-ZET.md §10 — «не показывать строку ЗЕТ, если поле NULL»).
import { useLocaleStore } from '@/stores/locale'
const locale = useLocaleStore()
defineProps({
  earned: { type: Number, required: true },
  total: { type: Number, required: true },
  minZet: { type: Number, default: null },
  subjects: { type: Array, default: () => [] },   // [{subject, zet, earned, passed}]
  showDetails: { type: Boolean, default: false },
})

// Цвет — по СТАТУСУ (набрано/почти/мало), не категориальный: accent (в этой палитре
// он и есть «хорошо», отдельного зелёного токена в теме нет), yellow — 80–99% от порога,
// red — ниже 80%. Без порога — всегда accent (пока не с чем сравнивать).
// Классы — ПОЛНЫМИ литеральными строками (не шаблонной интерполяцией `bg-${x}`): Tailwind
// JIT видит только буквальные вхождения при сборке, динамически склеенное имя класса
// рискует не попасть в итоговый CSS.
const STATUS_CLASSES = {
  accent: { text: 'text-accent', bg: 'bg-accent' },
  yellow: { text: 'text-yellow', bg: 'bg-yellow' },
  red: { text: 'text-red', bg: 'bg-red' },
}

function status(earned, total, minZet) {
  if (minZet == null || earned >= minZet) return 'accent'
  const pct = minZet > 0 ? (earned / minZet) * 100 : 100
  return pct >= 80 ? 'yellow' : 'red'
}
</script>

<template>
  <div>
    <div class="flex items-baseline justify-between gap-2">
      <span class="text-sm font-medium text-text2">{{ locale.t('zetProgress.title', 'ЗЕТ за семестр') }}</span>
      <span class="font-title text-base font-bold"
            :class="STATUS_CLASSES[status(earned, total, minZet)].text">{{ earned }} / {{ total }}</span>
    </div>
    <div class="mt-1.5 h-2 w-full overflow-hidden rounded-full bg-bg2">
      <div class="h-full rounded-full transition-all"
           :class="STATUS_CLASSES[status(earned, total, minZet)].bg"
           :style="{ width: `${total ? Math.min(100, (earned / total) * 100) : 0}%` }" />
    </div>
    <p v-if="minZet != null" class="mt-1 text-xs text-text3">
      <template v-if="earned >= minZet">{{ locale.t('zetProgress.thresholdMet', { min: minZet }) }}</template>
      <template v-else>{{ locale.t('zetProgress.thresholdMissing', { min: minZet, missing: Math.round((minZet - earned) * 10) / 10 }) }}</template>
    </p>

    <ul v-if="showDetails && subjects.length" class="mt-3 space-y-1">
      <li v-for="s in subjects" :key="s.subject" class="flex items-center justify-between text-xs">
        <span class="min-w-0 truncate text-text2" :title="s.subject">{{ s.subject }}</span>
        <span class="shrink-0" :class="s.passed ? 'text-accent' : 'text-red'">
          {{ locale.t('zetProgress.zetCount', { n: s.zet }) }} {{ s.passed ? locale.t('zetProgress.passed', '✅ засчитаны') : locale.t('zetProgress.notPassed', '❌ не сдан') }}
        </span>
      </li>
    </ul>
  </div>
</template>
