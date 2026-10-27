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
import { computed, ref } from 'vue'
import { useLocaleStore } from '@/stores/locale'
import GbIcon from '@/components/ui/GbIcon.vue'

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
// На телефоне наводить нечем, и причины были не видны вовсе (23.10.2026): полная плашка
// раскрывает их касанием прямо в строке. В потоке, а не всплывающим окном — ячейку
// таблицы с прокруткой по ширине всплывающее окно обрезало бы. Компактной плашке это не
// нужно: там, где она стоит (карточка куратора), причины и так выписаны под фамилией.
const canOpen = computed(() => !props.compact && !!props.risk?.factors?.length)
const open = ref(false)
</script>

<template>
  <span v-if="risk" class="inline-flex max-w-full flex-col items-start gap-1">
    <component :is="canOpen ? 'button' : 'span'" :type="canOpen ? 'button' : null"
               class="inline-flex max-w-full items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs font-semibold"
               :class="[cls, canOpen ? 'cursor-pointer pointer-coarse:min-h-9' : '']" :title="title"
               :aria-expanded="canOpen ? open : null" @click="canOpen && (open = !open)">
      <GbIcon name="risk" class="size-3.5 shrink-0" />
      <span class="shrink-0">{{ levelText }}</span>
      <span v-if="!compact && subjects" class="min-w-0 truncate font-normal opacity-80">· {{ subjects }}</span>
    </component>
    <ul v-if="canOpen && open" class="flex max-w-xs flex-col gap-0.5 text-left text-xs whitespace-normal text-text2">
      <li v-for="f in risk.factors" :key="f.code"><span class="font-semibold text-text">{{ f.label }}.</span> {{ f.detail }}</li>
    </ul>
  </span>
</template>
