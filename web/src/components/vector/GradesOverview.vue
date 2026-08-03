<script setup>
// GradesOverview — сводка успеваемости на вкладке «ИИ Помощник» (3.5.6).
//
// Зачем: вкладка занимала весь экран, а несла только переписку и крупного маскота —
// половина площади пустовала (живой отзыв: «отдельная вкладка с ИИ занимает много
// места, но она пуста»). Здесь то, за чем студент и заходит: общий средний балл
// кольцом и каждый предмет отдельной полосой.
//
// ФОРМА (почему именно так):
//   • общий средний — ОДНА величина, поэтому кольцо-прогресс с числом в центре, а не
//     «пирог по предметам»: доли в пироге означали бы, что предметы складываются в
//     целое, а средний балл так не устроен;
//   • по предметам — горизонтальные полосы одной серии: сравнение величин, длина
//     полосы читается точнее угла сектора.
// ЦВЕТ — СТАТУСНЫЙ (хорошо/средне/слабо), не категориальный: у одной серии
// разноцветность означала бы принадлежность к разным сущностям, которой здесь нет.
// Пороги и токены — ТЕ ЖЕ, что уже красят продукт (ZetProgress, эмоция маскота на
// главной): ≥4 хорошо, 3–4 средне, <3 слабо. Второго набора порогов не заводим.
// Рядом с каждой полосой стоит САМО ЧИСЛО — значение никогда не передаётся цветом
// одним, поэтому сводка читается и в ч/б, и при дальтонизме.
//
// Кольцо рисуем conic-gradient'ом — тем же приёмом, что и donut в отчёте куратора
// (CuratorReportOverlay.vue): графических библиотек в проекте нет и заводить их ради
// двух фигур не нужно.
import { ref, computed, onMounted } from 'vue'
import { RotateCw } from '@lucide/vue'
import { studentApi } from '@/api/endpoints'
import { useLocaleStore } from '@/stores/locale'

const locale = useLocaleStore()
const MAX_SCORE = 5          //шкала journal'а всегда приводится к 5-балльной (grading.py)

const loading = ref(true)
const failed = ref(false)
const average = ref(0)
const perSubject = ref([])

// Классы — ПОЛНЫМИ литеральными строками (не `bg-${x}`): Tailwind JIT видит только
// буквальные вхождения при сборке — тот же приём, что в ZetProgress.vue.
const STATUS = {
  accent: { text: 'text-accent', bg: 'bg-accent', css: 'var(--gb-accent)' },
  yellow: { text: 'text-yellow', bg: 'bg-yellow', css: 'var(--gb-yellow)' },
  red: { text: 'text-red', bg: 'bg-red', css: 'var(--gb-red)' },
}
function statusOf(avg) {
  const v = Number(avg) || 0
  if (v >= 4) return 'accent'
  if (v >= 3) return 'yellow'
  return 'red'
}

async function load() {
  loading.value = true
  failed.value = false
  try {
    const { data } = await studentApi.stats()
    average.value = Number(data.average) || 0
    //Предметы без единой оценки в сводку не берём: полоса нулевой длины читается как
    //«двойка по предмету», хотя оценок там просто ещё нет.
    perSubject.value = (data.per_subject || []).filter((p) => Number(p.average) > 0)
  } catch {
    failed.value = true
    average.value = 0
    perSubject.value = []
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
</script>

<template>
  <section class="flex h-full flex-col gap-3 overflow-y-auto rounded-lg border border-border bg-card p-4 shadow-card">
    <div class="flex items-center justify-between gap-2">
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

    <p v-if="loading" class="text-sm text-text3">{{ locale.t('common.loading', 'Загрузка…') }}</p>
    <p v-else-if="failed" class="text-sm text-text3">
      {{ locale.t('gradesOverview.failed', 'Не удалось получить статистику.') }}
    </p>
    <p v-else-if="!hasData" class="text-sm text-text3">
      {{ locale.t('gradesOverview.empty', 'Оценок пока нет — как появятся, покажу сводку.') }}
    </p>

    <template v-else>
      <!-- Кольцо общего среднего. Число в центре — главное, что читают. -->
      <div class="flex items-center gap-4">
        <!-- Кольцо шире внутреннего круга ровно на толщину дуги. Размеры подобраны под
             САМОЕ ДЛИННОЕ значение («4.00»): при 96/74 px и text-xl цифры вылезали за
             белый кружок — поймано скриншотом, не рассуждением. -->
        <div class="relative grid size-28 shrink-0 place-items-center rounded-full" :style="ringStyle">
          <div class="grid size-[88px] place-items-center rounded-full bg-card">
            <span class="font-title text-lg font-extrabold leading-none" :class="STATUS[avgStatus].text">
              {{ average ? average.toFixed(2) : '—' }}
            </span>
          </div>
        </div>
        <div class="min-w-0">
          <p class="text-sm font-semibold text-text">{{ locale.t('gradesOverview.averageLabel', 'Средний балл') }}</p>
          <p class="mt-0.5 text-xs text-text3">{{ locale.t('gradesOverview.outOf', { max: MAX_SCORE }) }}</p>
          <p class="mt-1 text-xs text-text2">
            {{ locale.t('gradesOverview.subjectsCounted', { n: perSubject.length }) }}
          </p>
        </div>
      </div>

      <!-- Предметы: полоса + само число (значение не передаётся цветом одним). -->
      <ul v-if="perSubject.length" class="flex flex-col gap-2">
        <li v-for="s in perSubject" :key="s.subject">
          <div class="flex items-baseline justify-between gap-2">
            <span class="min-w-0 truncate text-xs text-text2" :title="s.subject">{{ s.subject }}</span>
            <span class="shrink-0 text-xs font-bold" :class="STATUS[statusOf(s.average)].text">{{ s.average }}</span>
          </div>
          <div class="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-bg2">
            <div class="h-full rounded-full transition-all" :class="STATUS[statusOf(s.average)].bg"
                 :style="{ width: `${Math.max(0, Math.min(100, (Number(s.average) / MAX_SCORE) * 100))}%` }" />
          </div>
        </li>
      </ul>
    </template>
  </section>
</template>
