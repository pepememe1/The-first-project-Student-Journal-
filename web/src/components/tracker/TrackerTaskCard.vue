<script setup>
// TrackerTaskCard — карточка задачи на доске. Только показ: что делать по нажатию и как
// тащить, решает доска.
import { computed } from 'vue'
import { MessageSquare, ListChecks, CornerDownRight, CalendarClock } from '@lucide/vue'
import Avatar from '@/components/ui/Avatar.vue'
import { profilePlate } from '@/theme/palette'
import { checklistProgress, deadlineState } from '@/utils/tracker'
import { useTrackerLabels, PRIORITY_STYLE, KIND_STYLE, labelColor } from '@/composables/useTrackerLabels'

const props = defineProps({
  task: { type: Object, required: true },
  labels: { type: Array, default: () => [] },        // метки работы [{id,title,color}]
  members: { type: Object, default: () => ({}) },    // id → участник
  parentKey: { type: String, default: '' },
})
const L = useTrackerLabels()

const due = computed(() => deadlineState(props.task))
const check = computed(() => checklistProgress(props.task))
const taskLabels = computed(() => {
  const by = Object.fromEntries(props.labels.map((l) => [l.id, l]))
  return (props.task.labels || []).map((id) => by[id]).filter(Boolean)
})
const people = computed(() => (props.task.assignees || []).map((id) => props.members[id]).filter(Boolean))
const prio = computed(() => PRIORITY_STYLE[props.task.priority] || PRIORITY_STYLE.normal)
const kind = computed(() => KIND_STYLE[props.task.kind] || KIND_STYLE.task)
// Срок красим только когда он о чём-то сообщает: просрочено, сегодня, скоро.
const dueClass = computed(() => ({
  overdue: 'border-red/40 bg-red/10 text-red',
  today: 'border-orange/40 bg-orange/10 text-orange',
  soon: 'border-yellow/40 bg-yellow/10 text-text2',
}[due.value] || 'border-transparent text-text3'))
</script>

<template>
  <div class="rounded-lg border border-border2 bg-card p-2.5 shadow-sm transition-shadow hover:shadow-card"
       :class="task.completed_at ? 'opacity-75' : ''">
    <div class="mb-1 flex items-center gap-1.5 text-[11px] text-text3">
      <component :is="kind.icon" class="size-3.5 shrink-0" :style="{ color: kind.color }"
                 :aria-label="L.kind.value[task.kind]" />
      <!-- Несохранённая задача номера ещё не получила — его выдаёт сервер. -->
      <span class="font-semibold tabular-nums" :class="task.completed_at ? 'line-through' : ''">
        {{ task.key || L.t('tracker.newBadge') }}
      </span>
      <span v-if="parentKey" class="flex min-w-0 items-center gap-0.5 truncate"
            :title="L.t('tracker.subtaskOf', { key: parentKey })">
        <CornerDownRight class="size-3 shrink-0" />{{ parentKey }}
      </span>
      <component :is="prio.icon" class="ml-auto size-4 shrink-0" :style="{ color: prio.color }"
                 :aria-label="L.priority.value[task.priority]" :title="L.priority.value[task.priority]" />
    </div>

    <p class="break-words text-sm leading-snug text-text" :class="task.completed_at ? 'text-text2' : ''">
      {{ task.title }}
    </p>

    <div v-if="taskLabels.length" class="mt-1.5 flex min-w-0 flex-wrap gap-1">
      <span v-for="l in taskLabels" :key="l.id"
            class="min-w-0 max-w-full truncate rounded-full px-1.5 py-px text-[10.5px] font-semibold text-white"
            :style="{ background: labelColor(l.color) }">{{ l.title }}</span>
    </div>

    <div v-if="task.deadline || check.total || task.comment_count || people.length"
         class="mt-2 flex items-center gap-2 text-[11px] text-text3">
      <span v-if="task.deadline" class="flex items-center gap-1 rounded border px-1 py-px" :class="dueClass"
            :title="L.deadline.value[due] || ''">
        <CalendarClock class="size-3" />{{ L.fmtDate(task.deadline) }}
      </span>
      <span v-if="check.total" class="flex items-center gap-0.5"
            :class="check.done === check.total ? 'text-accent' : ''">
        <ListChecks class="size-3.5" />{{ check.done }}/{{ check.total }}
      </span>
      <span v-if="task.comment_count" class="flex items-center gap-0.5">
        <MessageSquare class="size-3.5" />{{ task.comment_count }}
      </span>
      <span class="ml-auto flex -space-x-1.5">
        <Avatar v-for="p in people.slice(0, 3)" :key="p.user_id" :src="p.avatar" :name="p.full_name"
                :role="p.user_role" :color="profilePlate(p.profile_color)" :size="22"
                class="rounded-full ring-2 ring-card" :title="p.full_name" />
        <span v-if="people.length > 3"
              class="grid size-[22px] place-items-center rounded-full bg-bg2 text-[10px] font-semibold text-text2 ring-2 ring-card">
          +{{ people.length - 3 }}
        </span>
      </span>
    </div>
  </div>
</template>
