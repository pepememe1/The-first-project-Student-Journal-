<script setup>
// TrackerTimeline — шкала сроков (диаграмма Ганта): задача = отрезок от даты начала до
// срока. Отвечает на вопрос, которого не видно ни на доске, ни в списке: «что идёт
// одновременно и что упирается друг в друга».
//
// Раскладка считается в `utils/tracker.js::timeline` (под тестом): здесь только отрисовка.
// Задача без единой даты на шкале не появляется — рисовать её негде; сколько таких,
// сказано внизу, чтобы «пустая шкала» не читалась как «задач нет».
import { computed } from 'vue'
import { timeline, deadlineState } from '@/utils/tracker'
import { useTrackerLabels, KIND_STYLE } from '@/composables/useTrackerLabels'
import { useLocaleStore } from '@/stores/locale'

const props = defineProps({
  tasks: { type: Array, required: true },
})
const emit = defineEmits(['open'])
const L = useTrackerLabels()
const locale = useLocaleStore()

const DAY = 34                    // ширина дня, px
const tl = computed(() => timeline(props.tasks))
const undated = computed(() => props.tasks.length - tl.value.rows.length)

const BCP47 = { ru: 'ru-RU', en: 'en-US', zh: 'zh-CN' }
const days = computed(() => {
  const tag = BCP47[locale.active] || 'ru-RU'
  const out = []
  for (let i = 0; i < tl.value.days; i++) {
    const d = new Date(tl.value.start.getTime() + i * 86400000)
    out.push({
      n: d.getDate(), weekend: d.getDay() === 0 || d.getDay() === 6,
      //Месяц подписываем на первом дне шкалы и на первых числах — иначе по одним числам
      //не понять, октябрь это или ноябрь.
      month: (i === 0 || d.getDate() === 1) ? d.toLocaleDateString(tag, { month: 'short' }) : '',
    })
  }
  return out
})
const barClass = (t) => {
  if (t.completed_at) return 'bg-accent/45'
  return { overdue: 'bg-red', today: 'bg-orange', soon: 'bg-yellow' }[deadlineState(t)] || 'bg-blue'
}
</script>

<template>
  <div class="flex h-full min-h-0 flex-col px-3 pb-3 sm:px-4">
    <div v-if="tl.rows.length" class="min-h-0 flex-1 overflow-auto rounded-xl border border-border bg-card">
      <div class="relative" :style="{ width: 224 + tl.days * DAY + 'px' }">
        <!-- Шапка с днями. Липнет к верху при прокрутке вниз. -->
        <div class="sticky top-0 z-20 flex border-b border-border bg-card">
          <div class="sticky left-0 z-10 w-56 shrink-0 border-r border-border bg-card px-3 py-2 text-xs font-semibold text-text3">
            {{ L.t('tracker.col.title') }}
          </div>
          <div v-for="(d, i) in days" :key="i" class="shrink-0 py-1 text-center text-[10.5px] leading-tight"
               :class="[d.weekend ? 'bg-bg2 text-text3' : 'text-text2', i === tl.today ? 'font-bold text-accent' : '']"
               :style="{ width: DAY + 'px' }">
            <span class="block h-3 text-text3">{{ d.month }}</span>{{ d.n }}
          </div>
        </div>
        <!-- Сегодня — вертикальной линией через все строки. -->
        <div class="pointer-events-none absolute bottom-0 top-0 z-10 w-px bg-accent"
             :style="{ left: 224 + tl.today * DAY + DAY / 2 + 'px' }" />
        <div v-for="row in tl.rows" :key="row.task.id" class="flex border-b border-border/60 hover:bg-bg2/60">
          <button type="button" @click="emit('open', row.task.id)"
                  class="sticky left-0 z-10 flex w-56 shrink-0 items-center gap-1.5 border-r border-border bg-card px-3 py-1.5 text-left">
            <component :is="(KIND_STYLE[row.task.kind] || KIND_STYLE.task).icon" class="size-3.5 shrink-0"
                       :style="{ color: (KIND_STYLE[row.task.kind] || KIND_STYLE.task).color }" />
            <span class="shrink-0 text-[11px] tabular-nums text-text3">{{ row.task.key || L.t('tracker.newBadge') }}</span>
            <span class="min-w-0 truncate text-sm text-text">{{ row.task.title }}</span>
          </button>
          <div class="relative h-9 shrink-0" :style="{ width: tl.days * DAY + 'px' }">
            <button type="button" @click="emit('open', row.task.id)"
                    class="absolute top-1.5 h-6 rounded-md px-2 text-left text-[11px] font-semibold text-white"
                    :class="[barClass(row.task), row.open ? 'rounded-r-none border-r-2 border-dashed border-white/70' : '']"
                    :style="{ left: row.from * DAY + 2 + 'px', width: Math.max(row.len * DAY - 4, 10) + 'px' }"
                    :title="`${row.task.title} · ${L.fmtDate(row.task.start_date) || '…'} — ${L.fmtDate(row.task.deadline) || L.t('tracker.noDeadline')}`">
              <span class="block truncate">{{ row.len > 2 ? row.task.title : '' }}</span>
            </button>
          </div>
        </div>
      </div>
    </div>
    <p v-else class="py-10 text-center text-sm text-text3">{{ L.t('tracker.timelineEmpty') }}</p>
    <p v-if="undated && tl.rows.length" class="mt-2 shrink-0 text-xs text-text3">
      {{ L.t('tracker.timelineUndated', { n: undated }) }}
    </p>
  </div>
</template>
