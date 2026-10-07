<script setup>
// TrackerSummary — сводка по работе: сколько сделано, что просрочено, кто чем занят.
//
// Все числа считает `utils/tracker.js::summarize` (под тестом) — по ТОЙ ЖЕ рабочей копии,
// что рисует доска. Второго расчёта «для красоты» здесь нет: две цифры про одно и то же
// на двух экранах расходятся молча.
import { computed } from 'vue'
import Avatar from '@/components/ui/Avatar.vue'
import { profilePlate } from '@/theme/palette'
import { summarize, fmtHours, PRIORITIES } from '@/utils/tracker'
import { useTrackerLabels, COLUMN_STYLE, PRIORITY_STYLE } from '@/composables/useTrackerLabels'

const props = defineProps({
  state: { type: Object, required: true },
  projectId: { type: String, default: '' },
  members: { type: Object, default: () => ({}) },
})
const emit = defineEmits(['filter'])
const L = useTrackerLabels()

const sum = computed(() => summarize(props.state, props.projectId))
const kinds = computed(() => ['todo', 'doing', 'review', 'done'].map((k) => ({
  k, n: sum.value.byKind[k], pct: sum.value.total ? (sum.value.byKind[k] / sum.value.total) * 100 : 0,
})))
const people = computed(() => Object.entries(sum.value.byAssignee)
  .map(([id, row]) => ({ id, ...row, member: props.members[id] }))
  .filter((r) => r.member)
  .sort((a, b) => (b.total - b.done) - (a.total - a.done)))
const prios = computed(() => PRIORITIES.map((p) => ({ p, n: sum.value.byPriority[p] || 0 })).filter((x) => x.n))
</script>

<template>
  <div class="h-full overflow-y-auto px-3 pb-4 sm:px-4">
    <div class="mx-auto grid max-w-5xl grid-cols-1 gap-3 md:grid-cols-2">
      <!-- Главное число — доля сделанного. -->
      <section class="rounded-xl border border-border bg-card p-4 md:col-span-2">
        <div class="flex flex-wrap items-end justify-between gap-3">
          <div>
            <p class="text-xs uppercase tracking-wide text-text3">{{ L.t('tracker.summary.progress') }}</p>
            <p class="font-title text-3xl font-extrabold text-text">{{ sum.percent }}%</p>
            <p class="text-sm text-text2">{{ L.t('tracker.summary.doneOf', { done: sum.done, total: sum.total }) }}</p>
          </div>
          <div class="flex flex-wrap gap-2 text-sm">
            <button type="button" @click="emit('filter', { status: 'overdue' })"
                    class="rounded-lg border px-3 py-1.5"
                    :class="sum.overdue ? 'border-red/40 bg-red/10 text-red' : 'border-border text-text3'">
              {{ L.t('tracker.summary.overdue') }}: <b>{{ sum.overdue }}</b>
            </button>
            <button type="button" @click="emit('filter', { assignee: 'none' })"
                    class="rounded-lg border border-border px-3 py-1.5 text-text2 hover:border-accent">
              {{ L.t('tracker.summary.unassigned') }}: <b>{{ sum.unassigned }}</b>
            </button>
          </div>
        </div>
        <!-- Полоса по состояниям: длина отрезка — доля задач. Подписи — рядом, а не
             только цветом: цвет различает не каждый. -->
        <div class="mt-3 flex h-3 overflow-hidden rounded-full bg-bg2">
          <span v-for="x in kinds" :key="x.k" :style="{ width: x.pct + '%', background: COLUMN_STYLE[x.k].color }"
                :title="`${L.columnKind.value[x.k]}: ${x.n}`" />
        </div>
        <div class="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-text2">
          <span v-for="x in kinds" :key="x.k" class="flex items-center gap-1.5">
            <span class="size-2 rounded-full" :style="{ background: COLUMN_STYLE[x.k].color }" />
            {{ L.columnKind.value[x.k] }} — {{ x.n }}
          </span>
        </div>
      </section>

      <section class="rounded-xl border border-border bg-card p-4">
        <h3 class="mb-2 text-sm font-semibold text-text">{{ L.t('tracker.summary.byPerson') }}</h3>
        <p v-if="!people.length" class="text-sm text-text3">{{ L.t('tracker.summary.nobody') }}</p>
        <ul v-else class="space-y-2">
          <li v-for="r in people" :key="r.id">
            <button type="button" class="flex w-full items-center gap-2.5 rounded-lg px-1 py-1 text-left hover:bg-bg2"
                    @click="emit('filter', { assignee: r.id })">
              <Avatar :src="r.member.avatar" :name="r.member.full_name" :role="r.member.user_role"
                      :color="profilePlate(r.member.profile_color)" :size="28" />
              <span class="min-w-0 flex-1">
                <span class="block truncate text-sm text-text">{{ r.member.full_name }}</span>
                <span class="mt-1 block h-1.5 overflow-hidden rounded-full bg-bg2">
                  <span class="block h-full rounded-full bg-accent" :style="{ width: (r.total ? r.done / r.total * 100 : 0) + '%' }" />
                </span>
              </span>
              <span class="shrink-0 text-right text-xs tabular-nums text-text2">
                {{ r.done }}/{{ r.total }}
                <span v-if="r.overdue" class="block text-red">{{ L.t('tracker.summary.overdueShort', { n: r.overdue }) }}</span>
              </span>
            </button>
          </li>
        </ul>
      </section>

      <section class="rounded-xl border border-border bg-card p-4">
        <h3 class="mb-2 text-sm font-semibold text-text">{{ L.t('tracker.summary.byPriority') }}</h3>
        <p v-if="!prios.length" class="text-sm text-text3">{{ L.t('tracker.noTasksHere') }}</p>
        <ul v-else class="space-y-1.5">
          <li v-for="x in prios" :key="x.p">
            <button type="button" class="flex w-full items-center gap-2 rounded-lg px-1 py-1 text-left text-sm hover:bg-bg2"
                    @click="emit('filter', { priority: x.p })">
              <component :is="PRIORITY_STYLE[x.p].icon" class="size-4" :style="{ color: PRIORITY_STYLE[x.p].color }" />
              <span class="flex-1 text-text2">{{ L.priority.value[x.p] }}</span>
              <b class="tabular-nums text-text">{{ x.n }}</b>
            </button>
          </li>
        </ul>
        <!-- Учёт времени: оценка против затраченного — только когда хоть что-то вписано. -->
        <div v-if="sum.estimate || sum.spent" class="mt-4 border-t border-border pt-3 text-sm text-text2">
          <p class="mb-1 text-xs uppercase tracking-wide text-text3">{{ L.t('tracker.summary.time') }}</p>
          <p>{{ L.t('tracker.field.estimate') }}: <b class="text-text">{{ fmtHours(sum.estimate, L.hoursUnit.value) || '—' }}</b></p>
          <p>{{ L.t('tracker.field.spent') }}: <b class="text-text">{{ fmtHours(sum.spent, L.hoursUnit.value) || '—' }}</b></p>
        </div>
      </section>
    </div>
  </div>
</template>
