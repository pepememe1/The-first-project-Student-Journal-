<script setup>
// RiskBadge — плашка «риск отчисления» (3.6). Один вид во всех местах, где он бывает:
// список студентов преподавателя, вкладка «Курирование», сводки.
//
// ⚠️ Компонент НИЧЕГО не решает сам: показывать ли риск и какой у него уровень —
// определяет сервер (общий корневой `dropout_risk.py`, порог MIN_VISIBLE). Если бы
// клиент имел свой порог, у преподавателя и куратора мгновенно разъехалось бы «кто в
// зоне риска», причём молча. Нет риска — `risk` приходит null, и здесь не рисуется
// ничего (пустая ячейка честнее, чем «нет риска» в каждой строке таблицы).
//
// Цвет усиливается с уровнем и НИКОГДА не бывает успокаивающим: плашка появляется
// только когда есть о чём говорить. Рядом всегда стоит подпись уровня словом —
// значение не передаётся цветом одним.
import { computed } from 'vue'
import { useLocaleStore } from '@/stores/locale'

const props = defineProps({
  risk: { type: Object, default: null },
  // compact — только точка с уровнем (для плотных таблиц), без списка причин.
  compact: { type: Boolean, default: false },
})
const locale = useLocaleStore()

// Полными литеральными классами: Tailwind JIT не видит склеенное `border-${x}`.
const STYLES = {
  low: 'border-yellow/30 bg-yellow/10 text-yellow',
  medium: 'border-orange/30 bg-orange/10 text-orange',
  high: 'border-red/30 bg-red/10 text-red',
  critical: 'border-red/50 bg-red/20 text-red',
}
const cls = computed(() => STYLES[props.risk?.level] || STYLES.low)
// Уровень словом — переводим по КОДУ, а не берём русский level_label с сервера:
// иначе в английском интерфейсе плашка осталась бы русской.
const levelText = computed(() => locale.t(
  `risk.level.${props.risk?.level}`, props.risk?.level_label || ''))
const subjects = computed(() =>
  (props.risk?.subjects || []).map((s) => s.subject).join(', '))
// Подсказка при наведении — причины по убыванию веса: почему именно этот уровень.
const title = computed(() => (props.risk?.factors || [])
  .map((f) => `${f.label}: ${f.detail}`).join('\n'))
</script>

<template>
  <span v-if="risk" class="inline-flex max-w-full items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs font-semibold"
        :class="cls" :title="title">
    <span aria-hidden="true">🎓</span>
    <span class="shrink-0">{{ levelText }}</span>
    <span v-if="!compact && subjects" class="min-w-0 truncate font-normal opacity-80">· {{ subjects }}</span>
  </span>
</template>
