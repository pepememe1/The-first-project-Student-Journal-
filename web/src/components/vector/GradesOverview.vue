<script setup>
// GradesOverview — сводка успеваемости на вкладке «ИИ Помощник» для СТУДЕНТА и РОДИТЕЛЯ.
//
// Раскладка (прямое пожелание 3.6): сверху колонкой — общий средний балл, ниже вниз
// колонкой прокручивается список предметов, у каждого своя полоса, средний балл и
// КОЛИЧЕСТВО ОЦЕНОК. Счётчик здесь не украшение: «5.00» по одной работе и «5.00» по
// двенадцати выглядят одинаково, а означают разное — без него сводка вводит в
// заблуждение ровно в ту сторону, в какую человеку приятнее ошибиться.
//
// ФОРМА:
//   • общий средний — ОДНА величина, поэтому кольцо-прогресс с числом в центре, а не
//     «пирог по предметам»: доли в пироге означали бы, что предметы складываются в
//     целое, а средний балл так не устроен;
//   • по предметам — горизонтальные полосы: сравнение величин, длина полосы читается
//     точнее угла сектора.
//
// ЦВЕТ. Кольцо общего среднего — СТАТУСНОЕ (хорошо/средне/слабо), пороги ТЕ ЖЕ, что уже
// красят продукт (≥4 / 3–4 / <3). Полосы предметов — КАТЕГОРИАЛЬНЫЕ (свой цвет на
// предмет, @/theme/dataviz): предметы — разные сущности, и по просьбе они должны
// различаться визуально. Чтобы это не стало враньём, рядом с каждой полосой ВСЕГДА
// стоит само число и подпись «оценок N»: значение не передаётся цветом ни разу,
// поэтому сводка читается и в ч/б, и при дальтонизме.
//
// Кольцо рисуем conic-gradient'ом — тем же приёмом, что и donut в отчёте куратора:
// графических библиотек в проекте нет и заводить их ради двух фигур не нужно.
import { ref, computed, onMounted } from 'vue'
import { RotateCw } from '@lucide/vue'
import { studentApi, parentApi } from '@/api/endpoints'
import { useAuthStore } from '@/stores/auth'
import { useThemeStore } from '@/stores/theme'
import { useLocaleStore } from '@/stores/locale'
import { categoricalColor } from '@/theme/dataviz'

const locale = useLocaleStore()
const auth = useAuthStore()
const theme = useThemeStore()
const MAX_SCORE = 5          //шкала journal'а всегда приводится к 5-балльной (grading.py)

const loading = ref(true)
const failed = ref(false)
const average = ref(0)
const perSubject = ref([])
const risk = ref(null)

// Классы статуса — ПОЛНЫМИ литеральными строками (не `bg-${x}`): Tailwind JIT видит
// только буквальные вхождения при сборке — тот же приём, что в ZetProgress.vue.
const STATUS = {
  accent: { text: 'text-accent', css: 'var(--gb-accent)' },
  yellow: { text: 'text-yellow', css: 'var(--gb-yellow)' },
  red: { text: 'text-red', css: 'var(--gb-red)' },
}
function statusOf(avg) {
  const v = Number(avg) || 0
  if (v >= 4) return 'accent'
  if (v >= 3) return 'yellow'
  return 'red'
}

// Уровень риска отчисления → цвет плашки. Никогда не «зелёный»: сама плашка появляется,
// только когда риск есть, и успокаивающий цвет тут был бы противоречием.
const RISK_STYLE = {
  low: 'border-yellow/30 bg-yellow/10 text-yellow',
  medium: 'border-orange/30 bg-orange/10 text-orange',
  high: 'border-red/30 bg-red/10 text-red',
  critical: 'border-red/40 bg-red/15 text-red',
}

async function load() {
  loading.value = true
  failed.value = false
  try {
    // Родитель смотрит журнал ребёнка — ответ /web/parent/stats намеренно повторяет
    // формат /web/student/stats, поэтому дальше код общий (см. parent.py::parent_stats).
    const { data } = auth.role === 'parent' ? await parentApi.stats() : await studentApi.stats()
    average.value = Number(data.average) || 0
    //Предметы без единой оценки в сводку не берём: полоса нулевой длины читается как
    //«двойка по предмету», хотя оценок там просто ещё нет.
    perSubject.value = (data.per_subject || []).filter((p) => Number(p.average) > 0)
    risk.value = data.risk || null
  } catch {
    failed.value = true
    average.value = 0
    perSubject.value = []
    risk.value = null
  } finally { loading.value = false }
}
onMounted(load)

const pct = computed(() => Math.max(0, Math.min(100, (average.value / MAX_SCORE) * 100)))
const avgStatus = computed(() => statusOf(average.value))
// Кольцо: заполненная дуга статусным цветом, остаток — фон карточки-подложки.
const ringStyle = computed(() => ({
  background: `conic-gradient(${STATUS[avgStatus.value].css} ${pct.value * 3.6}deg, var(--gb-bg2) 0)`,
}))
const hasData = computed(() => average.value > 0 || perSubject.value.length > 0)
const totalGrades = computed(() =>
  perSubject.value.reduce((n, s) => n + (Number(s.grades) || 0), 0))

function barStyle(s, i) {
  return {
    width: `${Math.max(2, Math.min(100, (Number(s.average) / MAX_SCORE) * 100))}%`,
    background: categoricalColor(i, theme.isDark),
  }
}
</script>

<template>
  <section class="flex h-full min-h-0 flex-col rounded-lg border border-border bg-card shadow-card">
    <!-- Шапка не прокручивается вместе со списком: у неё кнопка обновления. -->
    <div class="flex shrink-0 items-center justify-between gap-2 border-b border-border px-4 py-3">
      <h3 class="font-title text-sm font-bold text-text">
        {{ locale.t('gradesOverview.title', 'Успеваемость') }}
      </h3>
      <button type="button" @click="load" :disabled="loading"
              class="grid size-7 place-items-center rounded-md text-text3 transition-colors hover:bg-bg2 hover:text-accent disabled:opacity-50"
              :title="locale.t('common.refresh', 'Обновить')"
              :aria-label="locale.t('common.refresh', 'Обновить')">
        <RotateCw class="size-3.5" />
      </button>
    </div>

    <!-- ⚠️ Прокручивается ТОЛЬКО эта часть (min-h-0 обязателен: без него flex-ребёнок
         не даёт себя сжать, и вместо внутренней прокрутки уезжает вся страница). -->
    <div class="min-h-0 flex-1 overflow-y-auto p-4">
      <p v-if="loading" class="text-sm text-text3">{{ locale.t('common.loading', 'Загрузка…') }}</p>
      <p v-else-if="failed" class="text-sm text-text3">
        {{ locale.t('gradesOverview.failed', 'Не удалось получить статистику.') }}
      </p>
      <p v-else-if="!hasData" class="text-sm text-text3">
        {{ locale.t('gradesOverview.empty', 'Оценок пока нет — как появятся, покажу сводку.') }}
      </p>

      <template v-else>
        <!-- Общий средний — колонкой сверху: кольцо и подпись друг под другом, по центру. -->
        <div class="flex flex-col items-center gap-2 pb-4">
          <!-- Размеры подобраны под САМОЕ ДЛИННОЕ значение («4.00»): при меньшем круге
               цифры вылезали за белую середину — поймано скриншотом, не рассуждением. -->
          <div class="relative grid size-28 shrink-0 place-items-center rounded-full" :style="ringStyle">
            <div class="grid size-[88px] place-items-center rounded-full bg-card">
              <span class="font-title text-lg font-extrabold leading-none" :class="STATUS[avgStatus].text">
                {{ average ? average.toFixed(2) : '—' }}
              </span>
            </div>
          </div>
          <p class="text-sm font-semibold text-text">{{ locale.t('gradesOverview.averageLabel', 'Средний балл') }}</p>
          <p class="text-xs text-text3">
            {{ locale.t('gradesOverview.subjectsCounted', { n: perSubject.length }) }} ·
            {{ locale.t('gradesOverview.gradesCounted', { n: totalGrades }) }}
          </p>
        </div>

        <!-- Риск отчисления — ТОЛЬКО когда он реально есть (порог dropout_risk.MIN_VISIBLE
             проверяет сервер и отдаёт null ниже него). Здесь короткая плашка; подробный
             разбор с причинами и советом человек видит в «Умном совете» на главной. -->
        <div v-if="risk" class="mb-4 rounded-lg border p-3" :class="RISK_STYLE[risk.level] || RISK_STYLE.low">
          <p class="text-xs font-bold">🎓 {{ locale.t('gradesOverview.riskTitle', { level: risk.level_label }) }}</p>
          <p v-if="risk.subjects?.length" class="mt-1 text-xs text-text2">
            {{ risk.subjects.map((s) => s.subject).join(', ') }}
          </p>
        </div>

        <!-- Предметы: полоса своего цвета + САМО ЧИСЛО + сколько оценок. -->
        <ul class="flex flex-col gap-3">
          <li v-for="(s, i) in perSubject" :key="s.subject">
            <div class="flex items-baseline justify-between gap-2">
              <span class="min-w-0 truncate text-xs font-medium text-text" :title="s.subject">{{ s.subject }}</span>
              <span class="shrink-0 font-title text-sm font-extrabold" :class="STATUS[statusOf(s.average)].text">
                {{ Number(s.average).toFixed(2) }}
              </span>
            </div>
            <div class="mt-1 h-2 w-full overflow-hidden rounded-full bg-bg2">
              <div class="h-full rounded-full transition-all" :style="barStyle(s, i)" />
            </div>
            <p class="mt-0.5 text-[11px] text-text3">
              {{ locale.t('gradesOverview.gradesCounted', { n: s.grades ?? 0 }) }}
            </p>
          </li>
        </ul>
      </template>
    </div>
  </section>
</template>
