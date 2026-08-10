<script setup>
// StudentStats — статистика студента (порт ui/dashboards.py, страница "stats"):
// общий средний, средние по предметам (полоски), пропуски и задолженности.
import { ref, computed, onMounted } from 'vue'
import { studentApi } from '@/api/endpoints'
import Card from '@/components/ui/Card.vue'
import StatCard from '@/components/ui/StatCard.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import Gauge from '@/components/ui/Gauge.vue'
import { TrendingUp } from '@lucide/vue'
import { useLocaleStore } from '@/stores/locale'

const locale = useLocaleStore()

const loading = ref(true)
const data = ref(null)

onMounted(async () => {
  try { data.value = (await studentApi.stats()).data } catch { data.value = null } finally { loading.value = false }
})

const perSubject = computed(() => data.value?.per_subject || [])
// Цвет полосы/кольца по уровню оценки (как в десктопе: 5 → акцент … <3 → красный).
function barColor(v) {
  const n = Number(v) || 0
  if (n >= 4.5) return 'var(--gb-accent)'
  if (n >= 3.5) return '#3b82f6'
  if (n >= 3) return '#f59e0b'
  if (n > 0) return '#ef4444'
  return 'var(--gb-border2)'
}
</script>

<template>
  <!-- ⚠️ flex+gap, а НЕ space-y-6. `space-y-*` в Tailwind 4 разворачивается в правило с
       нулевой специфичностью (`:where(& > :not(:last-child))`) и добавляет отступ КАЖДОМУ
       ребёнку, кроме последнего, — такой промежуток проигрывает любому другому правилу с
       margin и исчезает, не оставив следа в разметке (именно так пропал интервал между
       рядами карточек). `gap` живёт на контейнере: перебить его нечем, и он не зависит от
       того, сколько детей отрисовалось. -->
  <div class="flex flex-col gap-6">
    <p v-if="loading" class="text-sm text-text3">{{ locale.t('common.loading') }}</p>

    <template v-else-if="data">
      <div class="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <StatCard :label="locale.t('studentStats.average', 'Средний балл')" :value="data.average ?? '—'" :icon="TrendingUp" accent />
        <StatCard :label="locale.t('studentStats.absencesHours', 'Пропусков (часов)')" :value="data.absences?.всего ?? 0" />
        <StatCard :label="locale.t('studentStats.debts', 'Задолженности')" :value="data.debts?.length ?? 0" />
      </div>

      <Card :title="locale.t('studentStats.subjectPerfTitle', 'Успеваемость по предметам')">
        <EmptyState v-if="!perSubject.length" :title="locale.t('studentStats.noData', 'Нет данных')" />
        <!-- grid-cols-1 на телефоне: без явной колонки неявная дорожка `auto` тянется под
             самое длинное название предмета и уводит карточку за край экрана -->
        <div v-else class="grid grid-cols-1 gap-5 sm:grid-cols-[auto_1fr] sm:items-center">
          <div class="flex flex-col items-center justify-center">
            <Gauge :value="Number(data.average) || 0" :size="132" />
            <p class="mt-1 text-xs text-text3">{{ locale.t('studentStats.averageCaption', 'средний балл') }}</p>
          </div>
          <ul class="flex min-w-0 flex-col gap-3">
            <li v-for="p in perSubject" :key="p.subject" class="min-w-0">
              <div class="mb-1 flex items-center justify-between gap-2 text-sm">
                <span class="min-w-0 break-words text-text">{{ p.subject }}</span>
                <span class="shrink-0 font-title font-bold" :style="{ color: barColor(p.average) }">{{ p.average || '—' }}</span>
              </div>
              <div class="h-2 overflow-hidden rounded-full bg-bg2">
                <div class="h-full rounded-full transition-all"
                     :style="{ width: ((Number(p.average) / 5) * 100 || 0) + '%', background: barColor(p.average) }" />
              </div>
            </li>
          </ul>
        </div>
      </Card>

      <div class="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card :title="locale.t('studentStats.absencesTitle', 'Пропуски')">
          <div class="grid grid-cols-3 gap-3 text-center">
            <div class="rounded-md bg-card2 p-3">
              <p class="font-title text-2xl font-extrabold text-text">{{ data.absences?.Н ?? 0 }}</p>
              <p class="text-xs text-text3">{{ locale.t('studentStats.absN', 'Н (неув.)') }}</p>
            </div>
            <div class="rounded-md bg-card2 p-3">
              <p class="font-title text-2xl font-extrabold text-text">{{ data.absences?.Б ?? 0 }}</p>
              <p class="text-xs text-text3">{{ locale.t('studentStats.absB', 'Б (болезнь)') }}</p>
            </div>
            <div class="rounded-md bg-card2 p-3">
              <p class="font-title text-2xl font-extrabold text-text">{{ data.absences?.О ?? 0 }}</p>
              <p class="text-xs text-text3">{{ locale.t('studentStats.absO', 'О (уваж.)') }}</p>
            </div>
          </div>
        </Card>

        <Card :title="locale.t('studentStats.debts', 'Задолженности')">
          <EmptyState v-if="!data.debts?.length" :title="locale.t('studentStats.noDebtsTitle', 'Долгов нет')" :message="locale.t('studentStats.noDebtsMessage', 'Так держать!')" />
          <ul v-else class="space-y-2">
            <li v-for="(d, i) in data.debts" :key="i" class="flex items-start gap-2 text-sm text-text">
              <span class="mt-1.5 size-1.5 shrink-0 rounded-full bg-red" />
              <span>{{ d }}</span>
            </li>
          </ul>
        </Card>
      </div>
    </template>

    <EmptyState v-else :title="locale.t('studentStats.noData', 'Нет данных')" />
  </div>
</template>
