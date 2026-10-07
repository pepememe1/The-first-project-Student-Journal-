<script setup>
// TrackerList — задачи работы таблицей: номер, название, статус, исполнители, приоритет,
// срок. Сортируется нажатием на заголовок столбца. Тот же набор задач, что на доске
// (фильтр общий), просто другой взгляд: доска отвечает «что в каком состоянии», список —
// «что горит» и «что у кого».
import { ref, computed } from 'vue'
import { ArrowUpDown, CalendarClock } from '@lucide/vue'
import Avatar from '@/components/ui/Avatar.vue'
import { profilePlate } from '@/theme/palette'
import { sortTasks, deadlineState } from '@/utils/tracker'
import { useTrackerLabels, PRIORITY_STYLE, KIND_STYLE, COLUMN_STYLE } from '@/composables/useTrackerLabels'

const props = defineProps({
  columns: { type: Array, required: true },
  tasks: { type: Array, required: true },
  members: { type: Object, default: () => ({}) },
})
const emit = defineEmits(['open'])
const L = useTrackerLabels()

const sortKey = ref('key')
const sortDir = ref(1)
function sortBy(key) {
  if (sortKey.value === key) sortDir.value = -sortDir.value
  else { sortKey.value = key; sortDir.value = 1 }
}
const columnById = computed(() => Object.fromEntries(props.columns.map((c) => [c.id, c])))
const rows = computed(() => sortTasks(props.tasks, sortKey.value, sortDir.value, {
  columnOrder: Object.fromEntries(props.columns.map((c, i) => [c.id, i])),
  names: Object.fromEntries(Object.values(props.members).map((m) => [m.user_id, m.full_name])),
}))
const HEAD = computed(() => [
  ['key', L.t('tracker.col.key'), 'w-24'],
  ['title', L.t('tracker.col.title'), ''],
  ['status', L.t('tracker.col.status'), 'w-36 hidden sm:table-cell'],
  ['assignee', L.t('tracker.col.assignee'), 'w-40 hidden md:table-cell'],
  ['priority', L.t('tracker.col.priority'), 'w-32 hidden lg:table-cell'],
  ['deadline', L.t('tracker.col.deadline'), 'w-32'],
])
const dueText = (t) => ({ overdue: 'text-red font-semibold', today: 'text-orange font-semibold' }[deadlineState(t)] || 'text-text2')
</script>

<template>
  <!-- Прокрутка в обе стороны у ЭТОГО блока: узкий экран двигает таблицу, а не весь трекер.
       На телефоне столбцы «статус / исполнитель / приоритет» скрыты, статус уходит под
       название — вбок листать почти не приходится. -->
  <div class="h-full overflow-x-auto overflow-y-auto px-3 pb-3 sm:px-4">
    <table class="w-full min-w-[20rem] border-separate border-spacing-0 text-sm">
      <thead class="sticky top-0 z-10 bg-bg">
        <tr>
          <th v-for="[key, label, cls] in HEAD" :key="key" scope="col"
              class="border-b border-border px-2 py-2 text-left text-xs font-semibold text-text3" :class="cls">
            <button type="button" class="inline-flex items-center gap-1 hover:text-text" @click="sortBy(key)"
                    :aria-sort="sortKey === key ? (sortDir > 0 ? 'ascending' : 'descending') : 'none'">
              {{ label }}
              <ArrowUpDown class="size-3" :class="sortKey === key ? 'text-accent' : 'opacity-40'" />
            </button>
          </th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="t in rows" :key="t.id" class="cursor-pointer hover:bg-bg2" tabindex="0"
            @click="emit('open', t.id)" @keydown.enter="emit('open', t.id)">
          <td class="border-b border-border/60 px-2 py-2 align-top">
            <span class="inline-flex items-center gap-1.5 whitespace-nowrap text-xs tabular-nums text-text3"
                  :class="t.completed_at ? 'line-through' : ''">
              <component :is="(KIND_STYLE[t.kind] || KIND_STYLE.task).icon" class="size-3.5"
                         :style="{ color: (KIND_STYLE[t.kind] || KIND_STYLE.task).color }" />
              {{ t.key || L.t('tracker.newBadge') }}
            </span>
          </td>
          <td class="border-b border-border/60 px-2 py-2 align-top">
            <span class="break-words text-text" :class="t.completed_at ? 'text-text2' : ''">{{ t.title }}</span>
            <!-- На узком экране статус уезжает под название: отдельного столбца там нет. -->
            <span class="mt-0.5 block text-xs text-text3 sm:hidden">{{ columnById[t.column_id]?.title }}</span>
          </td>
          <td class="hidden border-b border-border/60 px-2 py-2 align-top sm:table-cell">
            <span class="inline-flex items-center gap-1.5 text-xs text-text2">
              <span class="size-2 rounded-full"
                    :style="{ background: (COLUMN_STYLE[columnById[t.column_id]?.kind] || COLUMN_STYLE.todo).color }" />
              {{ columnById[t.column_id]?.title }}
            </span>
          </td>
          <td class="hidden border-b border-border/60 px-2 py-2 align-top md:table-cell">
            <span v-if="(t.assignees || []).length" class="flex items-center gap-1.5">
              <Avatar v-if="members[t.assignees[0]]" :src="members[t.assignees[0]].avatar"
                      :name="members[t.assignees[0]].full_name" :role="members[t.assignees[0]].user_role"
                      :color="profilePlate(members[t.assignees[0]].profile_color)" :size="20" />
              <span class="min-w-0 truncate text-xs text-text2">{{ members[t.assignees[0]]?.full_name }}</span>
              <span v-if="t.assignees.length > 1" class="shrink-0 text-xs text-text3">+{{ t.assignees.length - 1 }}</span>
            </span>
            <span v-else class="text-xs text-text3">—</span>
          </td>
          <td class="hidden border-b border-border/60 px-2 py-2 align-top lg:table-cell">
            <span class="inline-flex items-center gap-1 text-xs text-text2">
              <component :is="(PRIORITY_STYLE[t.priority] || PRIORITY_STYLE.normal).icon" class="size-4"
                         :style="{ color: (PRIORITY_STYLE[t.priority] || PRIORITY_STYLE.normal).color }" />
              {{ L.priority.value[t.priority] }}
            </span>
          </td>
          <td class="border-b border-border/60 px-2 py-2 align-top">
            <span v-if="t.deadline" class="inline-flex items-center gap-1 whitespace-nowrap text-xs" :class="dueText(t)">
              <CalendarClock class="size-3.5" />{{ L.fmtDate(t.deadline) }}
            </span>
            <span v-else class="text-xs text-text3">—</span>
          </td>
        </tr>
      </tbody>
    </table>
    <p v-if="!rows.length" class="py-10 text-center text-sm text-text3">{{ L.t('tracker.noTasksHere') }}</p>
  </div>
</template>
