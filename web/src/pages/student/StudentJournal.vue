<script setup>
// StudentJournal — журнал студента (порт ui/dashboards.py, страница "journal").
// Занятия сгруппированы по предметам, у каждого — своя оценка и средний по предмету.
import { ref, onMounted } from 'vue'
import { studentApi } from '@/api/endpoints'
import Card from '@/components/ui/Card.vue'
import Badge from '@/components/ui/Badge.vue'
import EmptyState from '@/components/ui/EmptyState.vue'

const loading = ref(true)
const data = ref(null)

onMounted(async () => {
  try { data.value = (await studentApi.journal()).data } catch { data.value = null } finally { loading.value = false }
})

// Оценка-«плашка» как в журнале десктопа (_load_journal): у числовых оценок —
// пастельный фон (5→зелёный, 4→синий, 3→жёлтый, 2→красный) поверх тёмного текста;
// «Н» — красным, «✓» — акцентом; пусто — приглушённый прочерк.
const GRADE_BG = { 5: '#DBF0E4', 4: '#DCEFF2', 3: '#FBEFD6', 2: '#FAE0DE' }
function gradeChip(g) {
  const v = (g || '').trim()
  const head = v.split(' ')[0]
  if (GRADE_BG[head]) return { background: GRADE_BG[head], color: '#0F1B22' }
  if (v === 'Н') return { color: 'var(--gb-red)' }
  if (v === '✓') return { color: 'var(--gb-accent)' }
  return { color: 'var(--gb-text2)' }
}
const isNumericGrade = (g) => !!GRADE_BG[(g || '').trim().split(' ')[0]]
</script>

<template>
  <div class="space-y-5">
    <p v-if="loading" class="text-sm text-text3">Загрузка…</p>
    <EmptyState v-else-if="!data?.subjects?.length" title="Занятий пока нет"
                message="Когда появятся предметы и оценки, они отобразятся здесь." />

    <template v-else>
      <Card v-for="s in data.subjects" :key="s.subject" :title="s.subject" pad>
        <template #header>
          <Badge variant="green">Средний {{ s.average || '—' }}</Badge>
        </template>
        <div class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead>
              <tr class="border-b border-border2 text-left text-tiny uppercase tracking-wide text-text2">
                <th class="py-2 pr-3 font-semibold">Тип</th>
                <th class="py-2 pr-3 font-semibold">Тема</th>
                <th class="py-2 pr-3 font-semibold">Дата</th>
                <th class="py-2 text-right font-semibold">Оценка</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="l in s.lessons" :key="l.id" class="border-b border-border last:border-0">
                <td class="py-2.5 pr-3 text-text3 whitespace-nowrap">{{ l.type }} №{{ l.number }}</td>
                <td class="py-2.5 pr-3 text-text">{{ l.topic || '—' }}</td>
                <td class="py-2.5 pr-3 text-text3 whitespace-nowrap">{{ l.date || '—' }}</td>
                <td class="py-2.5 text-right">
                  <span class="inline-block min-w-[2.2rem] rounded-md text-center font-title text-base font-bold"
                        :class="isNumericGrade(l.grade) ? 'px-2 py-0.5' : ''"
                        :style="gradeChip(l.grade)">{{ l.grade || '—' }}</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </Card>

      <p v-if="data.methodology" class="px-1 text-xs text-text3">{{ data.methodology }}</p>
    </template>
  </div>
</template>
