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
  <div class="space-y-6">
    <p v-if="loading" class="text-sm text-text3">Загрузка…</p>

    <template v-else-if="data">
      <div class="grid gap-4 sm:grid-cols-3">
        <StatCard label="Средний балл" :value="data.average ?? '—'" :icon="TrendingUp" accent />
        <StatCard label="Пропусков (часов)" :value="data.absences?.всего ?? 0" />
        <StatCard label="Задолженности" :value="data.debts?.length ?? 0" />
      </div>

      <Card title="Успеваемость по предметам">
        <EmptyState v-if="!perSubject.length" title="Нет данных" />
        <div v-else class="grid gap-5 sm:grid-cols-[auto_1fr] sm:items-center">
          <div class="flex flex-col items-center justify-center">
            <Gauge :value="Number(data.average) || 0" :size="132" />
            <p class="mt-1 text-xs text-text3">средний балл</p>
          </div>
          <ul class="space-y-3">
            <li v-for="p in perSubject" :key="p.subject">
              <div class="mb-1 flex items-center justify-between text-sm">
                <span class="text-text">{{ p.subject }}</span>
                <span class="font-title font-bold" :style="{ color: barColor(p.average) }">{{ p.average || '—' }}</span>
              </div>
              <div class="h-2 overflow-hidden rounded-full bg-bg2">
                <div class="h-full rounded-full transition-all"
                     :style="{ width: ((Number(p.average) / 5) * 100 || 0) + '%', background: barColor(p.average) }" />
              </div>
            </li>
          </ul>
        </div>
      </Card>

      <div class="grid gap-6 lg:grid-cols-2">
        <Card title="Пропуски">
          <div class="grid grid-cols-3 gap-3 text-center">
            <div class="rounded-md bg-card2 p-3">
              <p class="font-title text-2xl font-extrabold text-text">{{ data.absences?.Н ?? 0 }}</p>
              <p class="text-xs text-text3">Н (неув.)</p>
            </div>
            <div class="rounded-md bg-card2 p-3">
              <p class="font-title text-2xl font-extrabold text-text">{{ data.absences?.Б ?? 0 }}</p>
              <p class="text-xs text-text3">Б (болезнь)</p>
            </div>
            <div class="rounded-md bg-card2 p-3">
              <p class="font-title text-2xl font-extrabold text-text">{{ data.absences?.О ?? 0 }}</p>
              <p class="text-xs text-text3">О (уваж.)</p>
            </div>
          </div>
        </Card>

        <Card title="Задолженности">
          <EmptyState v-if="!data.debts?.length" title="Долгов нет" message="Так держать!" />
          <ul v-else class="space-y-2">
            <li v-for="(d, i) in data.debts" :key="i" class="flex items-start gap-2 text-sm text-text">
              <span class="mt-1.5 size-1.5 shrink-0 rounded-full bg-red" />
              <span>{{ d }}</span>
            </li>
          </ul>
        </Card>
      </div>
    </template>

    <EmptyState v-else title="Нет данных" />
  </div>
</template>
