<script setup>
// CuratorReportOverlay — §12 плана: оверлей кнопки «Отчёт №N» в канале «Отчёты · Группа».
// Круговая диаграмма — доля отличников/хорошистов/успевающих/неуспевающих (по общему
// среднему баллу, пороги 4.5/3.5/2.5 — ТЕ ЖЕ, что уже красят дашборды преподавателя и
// куратора, см. curator_report.categorize). Ниже — плоские диаграммы (проценты) по
// предметам группы; клик по предмету открывает журнал-дрилл-даун (оценки + пропуски).
//
// Цвета категорий — НЕ токены --gb-accent/--gb-blue приложения: donut показывает все 4
// категории ОДНОВРЕМЕННО рядом друг с другом (а не по одной, как на дашборде), и именно
// в этом «рядом» accent/blue проваливают проверку на различимость (skill dataviz:
// validate_palette.js — ΔE 13.0 при нормальном зрении, порог 15). Взяты 4 слота из
// категориальной палитры скилла (blue/orange/aqua/yellow), провалидированные ИМЕННО В
// ЭТОМ порядке (включая переход последний→первый — сектора донута образуют круг) для
// обоих режимов темы — см. references/palette.md той же skill.
import { ref, computed, watch } from 'vue'
import { X, ChevronLeft } from '@lucide/vue'
import { messengerApi } from '@/api/endpoints'
import { useThemeStore } from '@/stores/theme'

const props = defineProps({ reportId: { type: String, required: true } })
const emit = defineEmits(['close'])
const theme = useThemeStore()

const overview = ref(null)
const loading = ref(true)
const failed = ref(false)
const subject = ref(null)          // null — общий вид; иначе строка — дрилл-даун
const subjectData = ref(null)
const subjectLoading = ref(false)

async function loadOverview() {
  loading.value = true
  failed.value = false
  try {
    const { data } = await messengerApi.reportOverview(props.reportId)
    overview.value = data
  } catch { failed.value = true }
  finally { loading.value = false }
}
loadOverview()

// Фиксированный порядок и цвет категории — НИКОГДА не переставляются местами и не
// перекрашиваются в зависимости от того, какая категория сейчас больше (см. dataviz:
// «цвет закреплён за сущностью, а не за рангом»). light/dark — разные шаги ТЕХ ЖЕ хью
// (не автоматический инверт), см. заголовок файла.
const CATS = computed(() => (theme.isDark
  ? [
      ['excellent', 'Отличники', '#3987e5'],
      ['good', 'Хорошисты', '#d95926'],
      ['passing', 'Успевающие', '#199e70'],
      ['failing', 'Неуспевающие', '#c98500'],
    ]
  : [
      ['excellent', 'Отличники', '#2a78d6'],
      ['good', 'Хорошисты', '#eb6834'],
      ['passing', 'Успевающие', '#1baf7a'],
      ['failing', 'Неуспевающие', '#eda100'],
    ]))
const categories = computed(() => {
  const c = overview.value?.categories
  if (!c || !c.total) return []
  return CATS.value.map(([key, label, color]) => {
    const count = c.counts[key] || 0
    return { key, label, color, count, pct: Math.round((count / c.total) * 100) }
  })
})
// conic-gradient по сегментам ПОДРЯД, встык (без промежутков): conic-gradient
// интерполирует ЦВЕТ между несмежными стопами, а не заливает зазор фоном, поэтому
// «зазор в градусах» на практике дал бы смазанный переход, а не чистую границу —
// разделение секторов даёт легенда с цифрами (см. dataviz: подписи вместо зазора).
const donutStyle = computed(() => {
  const cats = categories.value
  const total = overview.value?.categories?.total || 0
  if (!cats.length || !total) return {}
  let acc = 0
  const stops = []
  for (const c of cats) {
    if (!c.count) continue
    const span = (c.count / total) * 360
    stops.push(`${c.color} ${acc}deg ${acc + span}deg`)
    acc += span
  }
  return { background: `conic-gradient(${stops.join(', ')})` }
})

async function openSubject(s) {
  subject.value = s
  subjectLoading.value = true
  subjectData.value = null
  try {
    const { data } = await messengerApi.reportSubject(props.reportId, s)
    subjectData.value = data
  } catch { subjectData.value = null }
  finally { subjectLoading.value = false }
}
function backToOverview() { subject.value = null; subjectData.value = null }

function fmtGrade(v) {
  return v || '—'
}
</script>

<template>
  <div class="fixed inset-0 z-50 grid place-items-center p-4" style="background: var(--gb-overlay)"
       @click.self="emit('close')">
    <div class="flex max-h-[85vh] w-full max-w-2xl flex-col rounded-xl border border-border2 bg-card shadow-card">
      <div class="flex items-center gap-2 border-b border-border p-4">
        <button v-if="subject" type="button" @click="backToOverview" aria-label="Назад"
                class="grid size-8 shrink-0 place-items-center rounded-md text-text3 hover:bg-bg2 hover:text-text">
          <ChevronLeft class="size-5" />
        </button>
        <div class="min-w-0 flex-1">
          <h3 class="truncate font-title text-base font-bold text-text">
            {{ subject ? subject : `Отчёт №${overview?.seq ?? ''} · ${overview?.group ?? ''}` }}
          </h3>
          <p v-if="!subject && overview" class="text-xs text-text3">
            {{ overview.year }} · {{ overview.semester === 1 ? 'осенний' : 'весенний' }} семестр ·
            на {{ overview.cutoff_date }}
            <span v-if="overview.archived" class="ml-1 rounded-full bg-bg2 px-1.5 py-0.5 text-[10px] font-semibold text-text3">Архив</span>
          </p>
        </div>
        <button type="button" @click="emit('close')" aria-label="Закрыть"
                class="grid size-8 shrink-0 place-items-center rounded-md text-text3 hover:bg-bg2 hover:text-text">
          <X class="size-5" />
        </button>
      </div>

      <div class="min-h-0 flex-1 overflow-y-auto p-4">
        <p v-if="loading" class="py-10 text-center text-sm text-text3">Считаем…</p>
        <p v-else-if="failed" class="py-10 text-center text-sm text-text3">Не удалось получить отчёт.</p>

        <!-- ── Общий вид: круговая + плоские диаграммы ─────────────────────────────── -->
        <template v-else-if="!subject && overview">
          <div v-if="!categories.length" class="py-6 text-center text-sm text-text3">
            У студентов группы пока нет ни одной оценки.
          </div>
          <div v-else class="flex flex-col items-center gap-4 sm:flex-row sm:items-start sm:gap-6">
            <!-- Круговая: доля категорий. Центр — общее число студентов (заголовок цифрой). -->
            <div class="relative size-40 shrink-0 rounded-full" :style="donutStyle">
              <div class="absolute inset-3 grid place-items-center rounded-full bg-card text-center">
                <div>
                  <div class="font-title text-2xl font-extrabold text-text">{{ overview.students }}</div>
                  <div class="text-[11px] text-text3">студентов</div>
                </div>
              </div>
            </div>
            <!-- Легенда — обязательна для ≥2 категорий; подписи цифрой, а не только цветом. -->
            <ul class="w-full space-y-1.5 text-sm">
              <li v-for="c in categories" :key="c.key" class="flex items-center gap-2">
                <span class="size-2.5 shrink-0 rounded-full" :style="{ background: c.color }" />
                <span class="flex-1 text-text">{{ c.label }}</span>
                <span class="text-text3">{{ c.count }} · {{ c.pct }}%</span>
              </li>
              <li v-if="overview.categories.no_data" class="pt-1 text-xs text-text3">
                Без оценок: {{ overview.categories.no_data }}
              </li>
            </ul>
          </div>

          <div v-if="overview.subjects.length" class="mt-6">
            <p class="mb-2 text-[11px] uppercase tracking-wide text-text3">Средний по предметам · % от 5</p>
            <div class="space-y-2.5">
              <button v-for="s in overview.subjects" :key="s.subject" type="button" @click="openSubject(s.subject)"
                      class="block w-full rounded-md text-left transition-opacity hover:opacity-80">
                <div class="mb-1 flex items-center justify-between text-xs">
                  <span class="font-medium text-text">{{ s.subject }}</span>
                  <span class="text-text3">{{ s.avg.toFixed(2) }} · {{ s.percent }}%</span>
                </div>
                <div class="h-2 overflow-hidden rounded-full bg-card2">
                  <div class="h-2 rounded-full bg-accent" :style="{ width: s.percent + '%' }" />
                </div>
              </button>
            </div>
          </div>
        </template>

        <!-- ── Дрилл-даун по предмету: журнал группы ────────────────────────────────── -->
        <template v-else-if="subject">
          <p v-if="subjectLoading" class="py-10 text-center text-sm text-text3">Загружаем журнал…</p>
          <div v-else-if="subjectData" class="overflow-x-auto">
            <table class="w-full min-w-[480px] border-collapse text-sm">
              <thead>
                <tr class="border-b border-border text-left text-[11px] uppercase tracking-wide text-text3">
                  <th class="py-1.5 pr-2">Студент</th>
                  <th v-for="l in subjectData.lessons" :key="l.id" class="px-1.5 py-1.5 text-center font-normal">
                    №{{ l.number }}
                  </th>
                  <th class="px-2 py-1.5 text-center">Ср.балл</th>
                  <th class="px-2 py-1.5 text-center">Пропущено</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in subjectData.rows" :key="row.student" class="border-b border-border/50">
                  <td class="py-1.5 pr-2 text-text">{{ row.student }}</td>
                  <td v-for="g in row.grades" :key="g.lesson_id" class="px-1.5 py-1.5 text-center text-text2">
                    {{ fmtGrade(g.value) }}
                  </td>
                  <td class="px-2 py-1.5 text-center font-semibold text-text">{{ row.average ? row.average.toFixed(2) : '—' }}</td>
                  <td class="px-2 py-1.5 text-center text-text2">
                    {{ row.missed_hours }} ч. <span class="text-text3">({{ row.missed_count }})</span>
                  </td>
                </tr>
              </tbody>
            </table>
            <p v-if="!subjectData.rows.length" class="py-6 text-center text-sm text-text3">В группе нет студентов.</p>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>
