<script setup>
// UsageBar — «занято X из Y» полосой.
//
// Отдельный компонент, потому что таких полос на странице сервера четыре (диск, память,
// подкачка, вес каталогов), и у всех одна тонкость: ЦВЕТ ЗАВИСИТ ОТ ЗАПОЛНЕНИЯ. Ради
// этого она и заводилась — «73 %» текстом не тревожит никого, а красная полоса тревожит
// вовремя. Пороги 75/90 % выбраны по боевому VPS: там диск на 73 %, и это ровно то
// состояние, которое пора замечать, но ещё не авария.
import { computed } from 'vue'

const props = defineProps({
  label: { type: String, required: true },
  used: { type: Number, default: 0 },
  total: { type: Number, default: 0 },
  // Подпись справа. Пусто — соберём сами из байтов.
  note: { type: String, default: '' },
})

const percent = computed(() => {
  if (!props.total) return 0
  return Math.min(100, Math.round((props.used / props.total) * 100))
})

const tone = computed(() => {
  if (percent.value >= 90) return 'bg-red'
  if (percent.value >= 75) return 'bg-yellow'
  return 'bg-accent'
})

function human(n) {
  if (!n && n !== 0) return '—'
  const units = ['Б', 'КБ', 'МБ', 'ГБ', 'ТБ']
  let v = n
  let i = 0
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i += 1 }
  return `${v >= 10 || i === 0 ? Math.round(v) : v.toFixed(1)} ${units[i]}`
}

const right = computed(() => props.note || `${human(props.used)} из ${human(props.total)}`)
</script>

<template>
  <div>
    <div class="mb-1.5 flex items-baseline justify-between gap-3">
      <span class="text-sm font-medium text-text2">{{ label }}</span>
      <span class="text-xs text-text3">{{ right }}</span>
    </div>
    <div class="h-2 w-full overflow-hidden rounded-full bg-card2"
         role="progressbar" :aria-valuenow="percent" aria-valuemin="0" aria-valuemax="100"
         :aria-label="label">
      <div class="h-full rounded-full transition-all" :class="tone"
           :style="{ width: percent + '%' }" />
    </div>
    <p class="mt-1 text-tiny text-text3">{{ percent }}%</p>
  </div>
</template>
