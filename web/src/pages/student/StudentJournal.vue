<script setup>
// StudentJournal — журнал студента (порт ui/dashboards.py, страница "journal").
// Занятия сгруппированы по предметам, у каждого — своя оценка и средний по предмету.
import { ref, onMounted } from 'vue'
import { studentApi } from '@/api/endpoints'
import Card from '@/components/ui/Card.vue'
import Badge from '@/components/ui/Badge.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import SubjectLessons from '@/components/journal/SubjectLessons.vue'
import { useLocaleStore } from '@/stores/locale'

const locale = useLocaleStore()

const loading = ref(true)
const data = ref(null)

// Архивный просмотр прошлых семестров убран (не работал корректно) — журнал всегда
// показывает ТЕКУЩИЙ термин, который сервер вычисляет по дате (тот же принцип, что
// уже применён к журналу преподавателя).
async function load() {
  loading.value = true
  try { data.value = (await studentApi.journal()).data } catch { data.value = null } finally { loading.value = false }
}
onMounted(load)

// Сами занятия рисует общий SubjectLessons — он же стоит в журнале родителя, чтобы две
// страницы, обязанные показывать одно и то же, не разъезжались (раньше вёрстка была
// скопирована в оба файла и уже начала расходиться, см. докстринг компонента).
</script>

<template>
  <div class="space-y-5">
    <p v-if="loading" class="text-sm text-text3">{{ locale.t('common.loading') }}</p>
    <EmptyState v-else-if="!data?.subjects?.length" :title="locale.t('studentJournal.noLessonsTitle', 'Занятий пока нет')"
                :message="locale.t('studentJournal.noLessonsMessage', 'Когда появятся предметы и оценки, они отобразятся здесь.')" />

    <template v-else>
      <Card v-for="s in data.subjects" :key="s.subject" :title="s.subject" pad>
        <template #header>
          <!-- Часы показываем, только если админ задал план: «24 из 0» выглядело бы поломкой -->
          <Badge v-if="s.hours?.total" variant="blue">
            {{ locale.t('studentJournal.hoursProgress', { done: s.hours.done, total: s.hours.total }) }}
          </Badge>
          <Badge variant="green">{{ locale.t('studentJournal.averageBadge', { avg: s.average || '—' }) }}</Badge>
        </template>
        <SubjectLessons :lessons="s.lessons" />
      </Card>

      <p v-if="data.methodology" class="px-1 text-xs text-text3">{{ data.methodology }}</p>
    </template>
  </div>
</template>
