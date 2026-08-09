<script setup>
// TeacherSubjectsOverlay — диаграммы преподавателя (§ вкладка «ИИ Помощник», 3.6.1).
// Прямая просьба: «по аналогии с отчётами» — визуальный язык и donut-приём буквально
// повторяют CuratorReportOverlay.vue (те же 4 категории/цвета/пороги, curator_report.
// categorize), но иерархия другая: у куратора одна ГРУППА со всеми её предметами, у
// преподавателя один ЕГО предмет может идти сразу в НЕСКОЛЬКИХ группах — поэтому здесь
// два уровня: 1) сводка по всем его предметам (агрегат по всем группам) — маленькие
// donut'ы-плитки + список предметов цветными полосками; 2) клик по предмету — то же
// самое, но ОДНА строка/donut НА КАЖДУЮ ЕГО ГРУППУ по этому предмету (сравнить группы
// между собой). Клик по группе — переход в его собственный журнал (просто открыть
// посмотреть, обычный /teacher/journal, никакого отдельного read-only режима не заводим).
import { ref, computed } from 'vue'
import { X, ChevronLeft, ExternalLink } from '@lucide/vue'
import { useRouter } from 'vue-router'
import { teacherApi } from '@/api/endpoints'
import { useThemeStore } from '@/stores/theme'
import { useLocaleStore } from '@/stores/locale'
import { categoricalPalette, categoricalColor } from '@/theme/dataviz'

const emit = defineEmits(['close'])
const theme = useThemeStore()
const locale = useLocaleStore()
const router = useRouter()

const loading = ref(true)
const failed = ref(false)
const overview = ref(null)          // {overall, subjects}

const subject = ref(null)           // null — сводка; иначе строка — drill-down по группам
const groupsLoading = ref(false)
const groupsData = ref(null)        // {subject, groups}

async function load() {
  loading.value = true
  failed.value = false
  try {
    const { data } = await teacherApi.subjectsOverview()
    overview.value = data
  } catch { failed.value = true }
  finally { loading.value = false }
}
load()

// Метки/цвета категорий — ТЕ ЖЕ 4 слота и ТОТ ЖЕ порядок, что в CuratorReportOverlay
// (первые четыре слота dataviz.js закреплены под них специально, см. её докстринг).
const CATS = computed(() => {
  const p = categoricalPalette(theme.isDark)
  return [
    ['excellent', locale.t('curatorReport.cat.excellent', 'Отличники'), p[0]],
    ['good', locale.t('curatorReport.cat.good', 'Хорошисты'), p[1]],
    ['passing', locale.t('curatorReport.cat.passing', 'Успевающие'), p[2]],
    ['failing', locale.t('curatorReport.cat.failing', 'Неуспевающие'), p[3]],
  ]
})
function legendOf(categories) {
  if (!categories || !categories.total) return []
  return CATS.value.map(([key, label, color]) => {
    const count = categories.counts[key] || 0
    return { key, label, color, count, pct: Math.round((count / categories.total) * 100) }
  })
}
// conic-gradient сегментами подряд, встык — тот же приём, что у CuratorReportOverlay
// (границу секторов даёт легенда с цифрами, а не зазор в градусах, см. её докстринг).
function donutStyle(categories) {
  const legend = legendOf(categories)
  const total = categories?.total || 0
  if (!legend.length || !total) return {}
  let acc = 0
  const stops = []
  for (const c of legend) {
    if (!c.count) continue
    const span = (c.count / total) * 360
    stops.push(`${c.color} ${acc}deg ${acc + span}deg`)
    acc += span
  }
  return { background: `conic-gradient(${stops.join(', ')})` }
}

async function openSubject(s) {
  subject.value = s
  groupsLoading.value = true
  groupsData.value = null
  try {
    const { data } = await teacherApi.subjectsOverviewGroups(s)
    groupsData.value = data
  } catch { groupsData.value = null }
  finally { groupsLoading.value = false }
}
function backToOverview() { subject.value = null; groupsData.value = null }

function openJournal(group) {
  router.push({ path: '/teacher/journal', query: { group, subject: subject.value } })
  emit('close')
}

function pct(avg) { return Math.max(2, Math.min(100, ((Number(avg) || 0) / 5) * 100)) }
</script>

<template>
  <div class="fixed inset-0 z-50 grid place-items-center p-4" style="background: var(--gb-overlay)"
       @click.self="emit('close')">
    <div class="flex max-h-[85vh] w-full max-w-3xl flex-col rounded-xl border border-border2 bg-card shadow-card">
      <div class="flex items-center gap-2 border-b border-border p-4">
        <button v-if="subject" type="button" @click="backToOverview" :aria-label="locale.t('curatorReport.back', 'Назад')"
                class="grid size-8 shrink-0 place-items-center rounded-md text-text3 hover:bg-bg2 hover:text-text">
          <ChevronLeft class="size-5" />
        </button>
        <h3 class="min-w-0 flex-1 truncate font-title text-base font-bold text-text">
          {{ subject ? subject : locale.t('teacherOverview.chartsTitle', 'Статистика по предметам') }}
        </h3>
        <button type="button" @click="emit('close')" :aria-label="locale.t('common.close')"
                class="grid size-8 shrink-0 place-items-center rounded-md text-text3 hover:bg-bg2 hover:text-text">
          <X class="size-5" />
        </button>
      </div>

      <div class="min-h-0 flex-1 overflow-y-auto p-4">
        <p v-if="loading" class="py-10 text-center text-sm text-text3">{{ locale.t('common.loading', 'Загрузка…') }}</p>
        <p v-else-if="failed" class="py-10 text-center text-sm text-text3">{{ locale.t('teacherOverview.failed', 'Не удалось получить сводку.') }}</p>

        <!-- ── Сводка: общая круговая + плитки предметов + список полосками ────────── -->
        <template v-else-if="!subject && overview">
          <div v-if="!overview.overall.categories.total" class="py-6 text-center text-sm text-text3">
            {{ locale.t('curatorReport.noGrades', 'У студентов группы пока нет ни одной оценки.') }}
          </div>
          <template v-else>
            <!-- Общая круговая — по ВСЕЙ нагрузке преподавателя сразу. -->
            <div class="flex flex-col items-center gap-4 sm:flex-row sm:items-start sm:gap-6">
              <div class="relative size-40 shrink-0 rounded-full" :style="donutStyle(overview.overall.categories)">
                <div class="absolute inset-3 grid place-items-center rounded-full bg-card text-center">
                  <div>
                    <div class="font-title text-2xl font-extrabold text-text">{{ overview.overall.avg || '—' }}</div>
                    <div class="text-[11px] text-text3">{{ locale.t('teacherOverview.avgAllGroups', 'средний по всем группам') }}</div>
                  </div>
                </div>
              </div>
              <ul class="w-full space-y-1.5 text-sm">
                <li v-for="c in legendOf(overview.overall.categories)" :key="c.key" class="flex items-center gap-2">
                  <span class="size-2.5 shrink-0 rounded-full" :style="{ background: c.color }" />
                  <span class="flex-1 text-text">{{ c.label }}</span>
                  <span class="text-text3">{{ c.count }} · {{ c.pct }}%</span>
                </li>
              </ul>
            </div>

            <!-- Плитки-donut'ы по КАЖДОМУ предмету — клик открывает разбивку по группам. -->
            <p class="mb-2 mt-6 text-[11px] uppercase tracking-wide text-text3">
              {{ locale.t('teacherOverview.perSubjectCharts', 'По предметам') }}
            </p>
            <div class="grid grid-cols-2 gap-3 sm:grid-cols-3">
              <button v-for="s in overview.subjects" :key="s.subject" type="button" @click="openSubject(s.subject)"
                      class="flex flex-col items-center gap-2 rounded-lg border border-border2 bg-card2 p-3 text-center transition-colors hover:border-accent">
                <div class="relative size-20 shrink-0 rounded-full" :style="donutStyle(s.categories)">
                  <div class="absolute inset-2 grid place-items-center rounded-full bg-card2">
                    <span class="font-title text-sm font-extrabold text-text">{{ s.avg || '—' }}</span>
                  </div>
                </div>
                <span class="w-full truncate text-xs font-semibold text-text" :title="s.subject">{{ s.subject }}</span>
                <span class="text-[11px] text-text3">{{ locale.t('teacherOverview.studentsCount', { n: s.students }) }}</span>
              </button>
            </div>

            <!-- Тот же список — полосками заполнения (заказчик просил и такой вид тоже). -->
            <p class="mb-2 mt-6 text-[11px] uppercase tracking-wide text-text3">
              {{ locale.t('teacherOverview.avgBySubject', 'Средний по предметам') }}
            </p>
            <div class="space-y-2.5">
              <button v-for="s in overview.subjects" :key="'bar-' + s.subject" type="button" @click="openSubject(s.subject)"
                      class="block w-full rounded-md text-left transition-opacity hover:opacity-80">
                <div class="mb-1 flex items-center justify-between text-xs">
                  <span class="font-medium text-text">{{ s.subject }}</span>
                  <span class="text-text3">{{ s.avg.toFixed(2) }}</span>
                </div>
                <div class="h-2 overflow-hidden rounded-full bg-card2">
                  <div class="h-2 rounded-full bg-accent" :style="{ width: pct(s.avg) + '%' }" />
                </div>
              </button>
            </div>
          </template>
        </template>

        <!-- ── Drill-down по предмету: donut + полоска НА КАЖДУЮ ГРУППУ ─────────────── -->
        <template v-else-if="subject">
          <p v-if="groupsLoading" class="py-10 text-center text-sm text-text3">{{ locale.t('common.loading', 'Загрузка…') }}</p>
          <template v-else-if="groupsData?.groups?.length">
            <div class="grid grid-cols-2 gap-3 sm:grid-cols-3">
              <button v-for="g in groupsData.groups" :key="g.group" type="button" @click="openJournal(g.group)"
                      class="flex flex-col items-center gap-2 rounded-lg border border-border2 bg-card2 p-3 text-center transition-colors hover:border-accent"
                      :title="locale.t('teacherOverview.openJournal', 'Открыть журнал')">
                <div class="relative size-20 shrink-0 rounded-full" :style="donutStyle(g.categories)">
                  <div class="absolute inset-2 grid place-items-center rounded-full bg-card2">
                    <span class="font-title text-sm font-extrabold text-text">{{ g.avg || '—' }}</span>
                  </div>
                </div>
                <span class="w-full truncate text-xs font-semibold text-text">{{ g.group }}</span>
                <span class="text-[11px] text-text3">{{ locale.t('teacherOverview.studentsCount', { n: g.students }) }}</span>
                <ul class="w-full space-y-0.5 text-left">
                  <li v-for="c in legendOf(g.categories)" :key="c.key" class="flex items-center gap-1 text-[10px]">
                    <span class="size-1.5 shrink-0 rounded-full" :style="{ background: c.color }" />
                    <span class="min-w-0 flex-1 truncate text-text3">{{ c.label }}</span>
                    <span class="text-text3">{{ c.pct }}%</span>
                  </li>
                </ul>
              </button>
            </div>

            <!-- Полоски — по группе, РАЗНЫЙ цвет на каждую (заказчик: «разных цветов для
                 каждой группы») — категориальная палитра, а не статусный цвет: здесь
                 сравниваются РАЗНЫЕ сущности (группы) рядом, а не одна величина. -->
            <p class="mb-2 mt-6 text-[11px] uppercase tracking-wide text-text3">
              {{ locale.t('teacherOverview.byGroup', 'По группам') }}
            </p>
            <div class="space-y-2.5">
              <button v-for="(g, i) in groupsData.groups" :key="'bar-' + g.group" type="button" @click="openJournal(g.group)"
                      class="flex w-full items-center gap-2 rounded-md text-left transition-opacity hover:opacity-80">
                <span class="w-24 shrink-0 truncate text-xs font-medium text-text">{{ g.group }}</span>
                <div class="h-2 flex-1 overflow-hidden rounded-full bg-card2">
                  <div class="h-2 rounded-full" :style="{ width: pct(g.avg) + '%', background: categoricalColor(i, theme.isDark) }" />
                </div>
                <span class="w-10 shrink-0 text-right text-xs text-text3">{{ g.avg.toFixed(2) }}</span>
                <ExternalLink class="size-3.5 shrink-0 text-text3" />
              </button>
            </div>
          </template>
          <p v-else class="py-10 text-center text-sm text-text3">{{ locale.t('teacherOverview.empty', 'Вам ещё не назначены группы и предметы.') }}</p>
        </template>
      </div>
    </div>
  </div>
</template>
