<script setup>
// TeacherStats — сводка по группе за предмет: карточки, Вектор (эмоция по среднему
// группы) и проактивные инсайты (должники, зона риска, пропуски).
import { ref, computed, watch, onMounted } from 'vue'
import { teacherApi } from '@/api/endpoints'
import StatCard from '@/components/ui/StatCard.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import InsightCards from '@/components/InsightCards.vue'
import Mascot from '@/components/Mascot.vue'
import { dashboardEmote } from '@/config/mascot'
import { TrendingUp, Users, BookOpen } from '@lucide/vue'
import { useLocaleStore } from '@/stores/locale'

const locale = useLocaleStore()

const groups = ref([])
const assignments = ref([])   // [{group, subject}] — назначения ЭТОГО преподавателя
const group = ref('')
const subject = ref('')
const data = ref(null)
const insights = ref([])

// ⚠️ Предметы — ТОЛЬКО назначенные в ВЫБРАННОЙ группе (3.6). Раньше список был плоским
// («все мои предметы вообще»), из-за чего он одновременно показывал лишнее (предмет,
// который ведётся в другой группе) и выглядел неполным при переключении групп, а выбор
// чужой для группы пары давал 403 от сервера. Пары (группа, предмет) сервер уже отдаёт
// в overview — второго запроса не нужно.
const subjects = computed(() =>
  [...new Set(assignments.value.filter((a) => a.group === group.value).map((a) => a.subject))].sort())

onMounted(async () => {
  try {
    const o = (await teacherApi.overview()).data
    groups.value = o.groups || []
    assignments.value = o.assignments || []
    group.value = groups.value[0] || ''
  } catch { /* */ }
})
// Сменили группу — предмет мог стать для неё недействительным; берём первый доступный.
watch(subjects, (list) => {
  if (!list.includes(subject.value)) subject.value = list[0] || ''
}, { immediate: true })
async function load() {
  if (!group.value || !subject.value) return
  try { data.value = (await teacherApi.stats(group.value, subject.value)).data } catch { data.value = null }
  try { insights.value = (await teacherApi.insights(group.value)).data.cards || [] } catch { insights.value = [] }
}
watch([group, subject], load)

// Эмоция Вектора — по среднему баллу группы (как на «Главной» студента).
const sprite = computed(() => dashboardEmote({ average: Number(data.value?.group_average || 0) }))
</script>

<template>
  <div class="space-y-4">
    <div class="flex flex-wrap gap-3">
      <select v-model="group" class="h-10 rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent">
        <option v-for="g in groups" :key="g" :value="g">{{ g }}</option>
      </select>
      <select v-model="subject" :title="subject"
              class="h-10 min-w-52 max-w-md rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent">
        <option v-for="s in subjects" :key="s" :value="s">{{ s }}</option>
      </select>
    </div>
    <EmptyState v-if="!groups.length || !subjects.length" :title="locale.t('teacherStats.noWorkload', 'Нет нагрузки')" />
    <template v-else>
      <!-- grid-cols-1 до lg: неявная дорожка `auto` растянулась бы под самое длинное
           название предмета и утащила бы за край экрана всю страницу -->
      <div class="grid grid-cols-1 gap-5 lg:grid-cols-[1fr_auto] lg:items-center">
        <div class="space-y-4">
          <div class="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <StatCard :label="locale.t('teacherStats.groupAverage', 'Средний по группе')" :value="data?.group_average || '—'" :icon="TrendingUp" accent />
            <StatCard :label="locale.t('teacherStats.students', 'Студентов')" :value="data?.students ?? '—'" :icon="Users" />
            <StatCard :label="locale.t('teacherStats.lessons', 'Занятий')" :value="data?.lessons ?? '—'" :icon="BookOpen" />
          </div>
          <InsightCards :cards="insights" />
        </div>
        <!-- Вектор реагирует на средний балл группы -->
        <div class="hidden shrink-0 items-start justify-center lg:flex">
          <Mascot :sprite="sprite" class="h-60 w-48" />
        </div>
      </div>
    </template>
  </div>
</template>
