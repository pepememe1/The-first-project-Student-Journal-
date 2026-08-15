<script setup>
// ActivityCard — карточка-кнопка активности в ленте (PLAN-ACTIVITIES §10).
//
// Механизм готовый: ровно так уже устроена кнопка «Отчёт №N» куратора — в теле сообщения
// лежит только id, а объект подмешивает сервер (`_attach_rich_meta`). Статус активности
// меняется ПОСЛЕ отправки (идёт → завершена), поэтому кнопка гаснет по `status`, а не по
// содержимому сообщения: переотправлять его ради этого незачем.
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'
import { Presentation, ListChecks, Trophy, BarChart3, Gauge, Timer } from '@lucide/vue'
import { useLocaleStore } from '@/stores/locale'
import { useActivityStore } from '@/stores/activity'

const props = defineProps({
  activity: { type: Object, required: true },
  createdAt: { type: String, default: '' },
})
const locale = useLocaleStore()
const act = useActivityStore()

const ICONS = {
  board: Presentation, quiz: ListChecks, contest: Trophy,
  poll: BarChart3, pulse: Gauge, timer: Timer,
}
const icon = computed(() => ICONS[props.activity.kind] || ListChecks)
const running = computed(() => props.activity.status === 'running')
const kindLabel = computed(() =>
  locale.t(`activity.kind.${props.activity.kind}`, props.activity.kind))

// Таймер «идёт N мин» — от начала активности. Тикаем локально: слать секунды по сокету
// всем участникам ради подписи на кнопке — самая дорогая реализация самой дешёвой вещи.
const now = ref(Date.now())
let tick = null
onMounted(() => { tick = setInterval(() => { now.value = Date.now() }, 1000) })
onBeforeUnmount(() => { if (tick) clearInterval(tick) })

const elapsed = computed(() => {
  const started = Date.parse(props.activity.started_at || '')
  if (!Number.isFinite(started)) return ''
  const end = running.value ? now.value : Date.parse(props.activity.finished_at || '') || now.value
  const secs = Math.max(0, Math.floor((end - started) / 1000))
  const mm = String(Math.floor(secs / 60)).padStart(2, '0')
  const ss = String(secs % 60).padStart(2, '0')
  return `${mm}:${ss}`
})
</script>

<template>
  <div class="my-1 flex justify-start">
    <button type="button" :disabled="!running" @click="act.open(activity.id)"
            class="flex min-w-0 items-center gap-2 rounded-2xl border border-border2 bg-card px-4 py-2 text-left text-sm shadow-sm transition-colors"
            :class="running ? 'font-semibold text-accent hover:bg-bg2' : 'cursor-default text-text3'">
      <component :is="icon" class="size-4 shrink-0" />
      <span class="flex min-w-0 flex-col leading-tight">
        <span class="truncate">
          {{ activity.title || kindLabel }}
          <span v-if="activity.title" class="font-medium text-text2">· {{ kindLabel }}</span>
        </span>
        <span class="text-[11px] font-medium text-text3">
          {{ running ? locale.t('activity.card.running', 'идёт') : locale.t('activity.card.finished', 'завершена') }}
          · {{ elapsed }}
        </span>
      </span>
    </button>
  </div>
</template>
