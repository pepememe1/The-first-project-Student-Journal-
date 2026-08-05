<script setup>
// TeacherOverview — сводка преподавателя на вкладке «ИИ Помощник» (3.6).
//
// Что здесь: КАЖДАЯ его группа и внутри неё КАЖДЫЙ его предмет со средним баллом
// группы по этому предмету. Прямое пожелание: «список предметов и общая успеваемость
// каждой его группы по его предметам». Плюс сколько студентов группы в зоне риска
// отчисления — то, ради чего преподаватель на эту цифру вообще смотрит.
//
// Всё приезжает ОДНИМ запросом (`/web/teacher/summary`): перебор `/teacher/stats` по
// каждой паре (группа, предмет) означал бы полтора десятка запросов на открытие
// страницы, каждый со своим походом за одними и теми же занятиями.
//
// ЦВЕТ. Средний по предмету — величина одной природы, поэтому СТАТУСНЫЙ цвет (те же
// пороги ≥4 / 3–4 / <3, что и везде в продукте), а не «каждому предмету свой»: у
// преподавателя предметов мало, а вопрос у него один — «где просело». Число стоит
// рядом всегда, цвет ничего не сообщает в одиночку.
import { ref, computed, onMounted } from 'vue'
import { RotateCw, PieChart } from '@lucide/vue'
import { teacherApi } from '@/api/endpoints'
import { useLocaleStore } from '@/stores/locale'
import TeacherSubjectsOverlay from '@/components/vector/TeacherSubjectsOverlay.vue'

const locale = useLocaleStore()
const MAX_SCORE = 5

const loading = ref(true)
const failed = ref(false)
const groups = ref([])
// Курируемые группы (§role — teacher с непустым curated_groups) — СО ВСЕМИ предметами
// группы, не только своими (3.6.1): куратор смотрит группу целиком, это его работа.
// Живой отзыв: раньше панель не показывала их вовсе.
const curatorGroups = ref([])
const showCharts = ref(false)

const STATUS = {
  accent: { text: 'text-accent', bg: 'bg-accent' },
  yellow: { text: 'text-yellow', bg: 'bg-yellow' },
  red: { text: 'text-red', bg: 'bg-red' },
}
function statusOf(avg) {
  const v = Number(avg) || 0
  if (v >= 4) return 'accent'
  if (v >= 3) return 'yellow'
  return 'red'
}
function width(avg) {
  return `${Math.max(2, Math.min(100, ((Number(avg) || 0) / MAX_SCORE) * 100))}%`
}

async function load() {
  loading.value = true
  failed.value = false
  try {
    const { data } = await teacherApi.summary()
    groups.value = data.groups || []
    curatorGroups.value = data.curator_groups || []
  } catch {
    failed.value = true
    groups.value = []
    curatorGroups.value = []
  } finally { loading.value = false }
}
onMounted(load)

const hasData = computed(() => groups.value.length > 0 || curatorGroups.value.length > 0)
</script>

<template>
  <section class="flex h-full min-h-0 flex-col rounded-lg border border-border bg-card shadow-card">
    <div class="flex shrink-0 items-center justify-between gap-2 border-b border-border px-4 py-3">
      <h3 class="font-title text-sm font-bold text-text">
        {{ locale.t('teacherOverview.title', 'Мои группы') }}
      </h3>
      <div class="flex shrink-0 items-center gap-1">
        <button type="button" @click="showCharts = true"
                class="grid size-7 place-items-center rounded-md text-text3 transition-colors hover:bg-bg2 hover:text-accent"
                :title="locale.t('teacherOverview.chartsTitle', 'Статистика по предметам')"
                :aria-label="locale.t('teacherOverview.chartsTitle', 'Статистика по предметам')">
          <PieChart class="size-3.5" />
        </button>
        <button type="button" @click="load" :disabled="loading"
                class="grid size-7 place-items-center rounded-md text-text3 transition-colors hover:bg-bg2 hover:text-accent disabled:opacity-50"
                :title="locale.t('common.refresh', 'Обновить')"
                :aria-label="locale.t('common.refresh', 'Обновить')">
          <RotateCw class="size-3.5" />
        </button>
      </div>
    </div>

    <div class="min-h-0 flex-1 overflow-y-auto p-4">
      <p v-if="loading" class="text-sm text-text3">{{ locale.t('common.loading', 'Загрузка…') }}</p>
      <p v-else-if="failed" class="text-sm text-text3">
        {{ locale.t('teacherOverview.failed', 'Не удалось получить сводку.') }}
      </p>
      <p v-else-if="!hasData" class="text-sm text-text3">
        {{ locale.t('teacherOverview.empty', 'Вам ещё не назначены группы и предметы.') }}
      </p>

      <div v-else class="flex flex-col gap-5">
        <template v-if="groups.length">
          <p v-if="curatorGroups.length" class="text-[11px] font-semibold uppercase tracking-wide text-text3">
            {{ locale.t('teacherOverview.myAssignments', 'Мои назначения') }}
          </p>
          <div v-for="g in groups" :key="'own-' + g.group">
            <!-- Шапка группы: имя, общий средний по ВСЕМ моим предметам, сколько студентов. -->
            <div class="flex items-baseline justify-between gap-2">
              <span class="min-w-0 truncate font-title text-sm font-bold text-text">{{ g.group }}</span>
              <span class="shrink-0 font-title text-sm font-extrabold" :class="STATUS[statusOf(g.average)].text">
                {{ g.average ? Number(g.average).toFixed(2) : '—' }}
              </span>
            </div>
            <p class="mt-0.5 text-[11px] text-text3">
              {{ locale.t('teacherOverview.studentsCount', { n: g.students }) }}
            </p>
            <!-- Зона риска: плашка появляется, ТОЛЬКО если такие студенты есть. «В зоне
                 риска: 0» — строка, которая ничего не сообщает, но занимает место. -->
            <p v-if="g.at_risk" class="mt-1.5 rounded-md border border-red/30 bg-red/10 px-2 py-1 text-[11px] font-semibold text-red">
              🎓 {{ locale.t('teacherOverview.atRisk', { n: g.at_risk }) }}
            </p>

            <ul class="mt-2 flex flex-col gap-2.5">
              <li v-for="s in g.subjects" :key="s.subject">
                <div class="flex items-baseline justify-between gap-2">
                  <span class="min-w-0 truncate text-xs text-text2" :title="s.subject">{{ s.subject }}</span>
                  <span class="shrink-0 text-xs font-bold" :class="STATUS[statusOf(s.average)].text">
                    {{ s.average ? Number(s.average).toFixed(2) : '—' }}
                  </span>
                </div>
                <div class="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-bg2">
                  <div class="h-full rounded-full transition-all" :class="STATUS[statusOf(s.average)].bg"
                       :style="{ width: width(s.average) }" />
                </div>
                <!-- По скольким студентам посчитан средний: по трём из двадцати пяти и по
                     всем двадцати пяти он выглядит одинаково, а значит совсем разное. -->
                <p class="mt-0.5 text-[11px] text-text3">
                  {{ locale.t('teacherOverview.gradedStudents', { n: s.graded_students, total: g.students }) }}
                </p>
              </li>
            </ul>
          </div>
        </template>

        <!-- Курируемые группы — СО ВСЕМИ предметами (не только своими): куратор смотрит
             группу целиком, это отдельная от преподавания роль (§role). -->
        <template v-if="curatorGroups.length">
          <p class="text-[11px] font-semibold uppercase tracking-wide text-text3">
            {{ locale.t('teacherOverview.curatedGroups', 'Курируемые группы') }}
          </p>
          <div v-for="g in curatorGroups" :key="'curator-' + g.group">
            <div class="flex items-baseline justify-between gap-2">
              <span class="min-w-0 truncate font-title text-sm font-bold text-text">{{ g.group }}</span>
              <span class="shrink-0 font-title text-sm font-extrabold" :class="STATUS[statusOf(g.average)].text">
                {{ g.average ? Number(g.average).toFixed(2) : '—' }}
              </span>
            </div>
            <p class="mt-0.5 text-[11px] text-text3">
              {{ locale.t('teacherOverview.studentsCount', { n: g.students }) }}
            </p>
            <p v-if="g.at_risk" class="mt-1.5 rounded-md border border-red/30 bg-red/10 px-2 py-1 text-[11px] font-semibold text-red">
              🎓 {{ locale.t('teacherOverview.atRisk', { n: g.at_risk }) }}
            </p>
            <ul class="mt-2 flex flex-col gap-2.5">
              <li v-for="s in g.subjects" :key="s.subject">
                <div class="flex items-baseline justify-between gap-2">
                  <span class="min-w-0 truncate text-xs text-text2" :title="s.subject">{{ s.subject }}</span>
                  <span class="shrink-0 text-xs font-bold" :class="STATUS[statusOf(s.average)].text">
                    {{ s.average ? Number(s.average).toFixed(2) : '—' }}
                  </span>
                </div>
                <div class="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-bg2">
                  <div class="h-full rounded-full transition-all" :class="STATUS[statusOf(s.average)].bg"
                       :style="{ width: width(s.average) }" />
                </div>
                <p class="mt-0.5 text-[11px] text-text3">
                  {{ locale.t('teacherOverview.gradedStudents', { n: s.graded_students, total: g.students }) }}
                </p>
              </li>
            </ul>
          </div>
        </template>
      </div>
    </div>

    <TeacherSubjectsOverlay v-if="showCharts" @close="showCharts = false" />
  </section>
</template>
