<script setup>
// PulsePlayer — срез понимания 1–10 (PLAN-ACTIVITIES §8.3).
//
// 🔑 ГЛАВНОЕ. Студенту пишем «преподаватель не увидит, кто это написал», а НЕ «анонимно».
// Автор в базе ЕСТЬ и обязан быть: у отзыва есть кнопка жалобы, и жалоба уходит АДМИНУ —
// без автора она никуда не ведёт. Скрывает автора интерфейс преподавателя, а не база.
// Формулировка «анонимно» была бы обманом, и первая же разобранная жалоба это вскрыла бы.
import { ref, computed, onMounted, watch } from 'vue'
import { Flag } from '@lucide/vue'
import AppButton from '@/components/ui/AppButton.vue'
import { useLocaleStore } from '@/stores/locale'
import { useActivityStore } from '@/stores/activity'
import { activitiesApi } from '@/api/endpoints'

const locale = useLocaleStore()
const act = useActivityStore()

// Готовые причины + «другое» со своим текстом: список из воздуха человек не заполнит,
// а без «другого» он не скажет ровно того, ради чего срез и затевался.
const REASONS = ['tempo', 'terms', 'example', 'noticed', 'other']

const score = ref(0)
const reason = ref('')
const text = ref('')
// Три страницы вместо одной длинной формы: «насколько понятно» → «что именно» →
// «своими словами». Человек отвечает на один вопрос за раз, а не разглядывает анкету —
// на срез посреди пары у него секунды, и длинная форма молча остаётся незаполненной.
const page = ref(0)
const PAGES = 3

// ── Спидометр ───────────────────────────────────────────────────────────────────────
// Полукруг из десяти секторов: 1 слева (красный) → 10 справа (зелёный). Тон HSL течёт
// от 0° к 130°, поэтому середина сама собой жёлтая — таблицы порогов не нужно.
const CX = 100, CY = 104, R_OUT = 82, R_IN = 52
const segColor = (n) => `hsl(${Math.round(((n - 1) / 9) * 130)} 72% 46%)`
const angleOf = (n) => 180 - (n - 0.5) * 18          // центр сектора, в градусах
const rad = (deg) => (deg * Math.PI) / 180
const pt = (deg, r) => [CX + r * Math.cos(rad(deg)), CY - r * Math.sin(rad(deg))]

function segPath(n) {
  const a1 = 180 - (n - 1) * 18 - 1.2                //зазор между секторами — 1.2°
  const a2 = 180 - n * 18 + 1.2
  const [x1, y1] = pt(a1, R_OUT), [x2, y2] = pt(a2, R_OUT)
  const [x3, y3] = pt(a2, R_IN), [x4, y4] = pt(a1, R_IN)
  return `M${x1} ${y1} A${R_OUT} ${R_OUT} 0 0 1 ${x2} ${y2} L${x3} ${y3} A${R_IN} ${R_IN} 0 0 0 ${x4} ${y4} Z`
}
const labelPos = (n) => pt(angleOf(n), (R_OUT + R_IN) / 2)
const needle = computed(() => pt(angleOf(score.value || 0.01), R_IN - 6))
const sent = ref(false)
const summary = ref(null)
const reporting = ref(0)

const done = computed(() => sent.value || !!act.state.mine_done)
const answered = computed(() => Number(act.state.answered_count || 0))
const participants = computed(() => Number(act.state.participants || 0))

async function submit() {
  if (!score.value) return
  page.value = PAGES
  try {
    await activitiesApi.sendFeedback(act.activity.id, score.value, reason.value, text.value.trim())
    sent.value = true
  } catch { /* noop */ }
}

async function loadSummary() {
  if (!act.isHost) return
  try {
    const { data } = await activitiesApi.feedbackSummary(act.activity.id)
    summary.value = data
  } catch { summary.value = null }
}

onMounted(loadSummary)
watch(answered, loadSummary)

async function report(id) {
  reporting.value = id
  try {
    await activitiesApi.reportFeedback(id, 'harassment')
    reporting.value = -1
  } catch { reporting.value = 0 }
}
</script>

<template>
  <div class="flex flex-col gap-4 py-4">
    <!-- Взгляд студента -->
    <template v-if="!act.isHost">
      <div v-if="!done" class="flex flex-col gap-4">
        <h3 class="text-center text-base font-semibold text-text">
          {{ page === 0 ? locale.t('pulse.question', 'Оцените, насколько вы всё понимаете')
             : page === 1 ? locale.t('pulse.whatExactly', 'Что именно непонятно?')
             : locale.t('pulse.inYourWords', 'Своими словами') }}
        </h3>

        <!-- Страница 1: спидометр. Стрелка нагляднее ряда одинаковых кнопок: видно не
             только выбранное число, но и КРАЙ шкалы, к которому оно ближе. -->
        <div v-show="page === 0" class="flex justify-center">
          <svg viewBox="0 0 200 122" class="w-full max-w-[320px]" role="img"
               :aria-label="locale.t('pulse.question', 'Оцените, насколько вы всё понимаете')">
            <g v-for="n in 10" :key="n" @click="score = n" class="cursor-pointer">
              <path :d="segPath(n)" :fill="segColor(n)"
                    :opacity="score && score !== n ? 0.35 : 1" />
              <text :x="labelPos(n)[0]" :y="labelPos(n)[1] + 4" text-anchor="middle"
                    font-size="12" font-weight="700" fill="#fff">{{ n }}</text>
            </g>
            <line v-if="score" :x1="CX" :y1="CY" :x2="needle[0]" :y2="needle[1]"
                  stroke="currentColor" stroke-width="3" stroke-linecap="round" />
            <circle :cx="CX" :cy="CY" r="7" fill="currentColor" />
          </svg>
        </div>

        <!-- Страница 2: что именно непонятно -->
        <div v-show="page === 1" class="flex flex-wrap justify-center gap-1.5">
          <button v-for="r in REASONS" :key="r" type="button" @click="reason = reason === r ? '' : r"
                  class="rounded-lg border px-3 py-1.5 text-sm"
                  :class="reason === r ? 'border-accent bg-accent-glow text-accent' : 'border-border2 text-text2'">
            {{ locale.t(`pulse.reason.${r}`, r) }}
          </button>
        </div>

        <!-- Страница 3: свободный текст -->
        <div v-show="page === 2" class="flex flex-col gap-2">
          <textarea v-model="text" rows="3" maxlength="500"
                    :placeholder="locale.t('pulse.textPlaceholder', 'Что именно непонятно?')"
                    class="w-full rounded-lg border border-border2 bg-bg2 px-3 py-2 text-sm text-text" />
          <p class="text-xs text-text3">{{ locale.t('pulse.privacy') }}</p>
        </div>

        <div class="flex items-center justify-between gap-2 border-t border-border2 pt-3">
          <AppButton variant="ghost" size="sm" :disabled="page === 0" @click="page -= 1">
            {{ locale.t('quiz.prev', 'Назад') }}
          </AppButton>
          <span class="text-tiny text-text3">{{ page + 1 }} / {{ PAGES }}</span>
          <AppButton v-if="page < PAGES - 1" size="sm" :disabled="page === 0 && !score"
                     @click="page += 1">
            {{ locale.t('quiz.forward', 'Дальше') }}
          </AppButton>
          <AppButton v-else size="sm" :disabled="!score" @click="submit">
            {{ locale.t('quiz.finish', 'Завершить') }}
          </AppButton>
        </div>
      </div>
      <p v-else class="py-8 text-center text-sm text-text2">
        {{ locale.t('pulse.thanks', 'Спасибо, ответ отправлен') }}
      </p>
    </template>

    <!-- Взгляд преподавателя: сводка БЕЗ авторов -->
    <template v-else>
      <div class="flex flex-wrap items-baseline gap-3">
        <span class="text-3xl font-bold text-accent">{{ summary?.average ?? 0 }}</span>
        <span class="text-sm text-text3">
          {{ locale.t('pulse.answeredOf', { n: answered, total: participants }) }}
        </span>
        <!-- Доля отвечает на вопрос «можно ли уже делать выводы»: средний балл по трём
             ответам из тридцати не значит ничего, и это должно быть видно сразу. -->
        <span v-if="participants" class="rounded-full bg-bg2 px-2 py-0.5 text-xs font-semibold text-text2">
          {{ Math.round((answered / participants) * 100) }}%
        </span>
      </div>
      <!-- Гистограмма 1–10: полными классами, не шаблонной интерполяцией (Tailwind JIT
           не видит склеенное имя класса при сборке). -->
      <div v-if="summary" class="flex items-end gap-1" style="height: 72px">
        <div v-for="(n, i) in summary.histogram" :key="i"
             class="flex min-w-0 flex-1 flex-col items-center justify-end gap-1">
          <div class="w-full rounded-t bg-accent"
               :style="{ height: (summary.answers ? (n * 100 / summary.answers) : 0) + '%' }" />
          <span class="text-[10px] text-text3">{{ i + 1 }}</span>
        </div>
      </div>
      <div v-if="summary?.items?.length" class="flex flex-col gap-1.5">
        <div v-for="f in summary.items" :key="f.id"
             class="flex min-w-0 items-start gap-2 rounded-lg border border-border2 bg-bg2 px-3 py-2">
          <span class="shrink-0 rounded bg-card px-1.5 py-0.5 text-xs font-semibold text-accent">{{ f.score }}</span>
          <span class="min-w-0 flex-1 break-words text-sm text-text">
            {{ f.text || locale.t(`pulse.reason.${f.reason_code}`, f.reason_code) }}
          </span>
          <!-- Жалоба уходит АДМИНУ: преподаватель автора не видит ни до, ни после. -->
          <button type="button" @click="report(f.id)" :disabled="reporting === -1"
                  class="shrink-0 rounded p-1 text-text3 hover:text-red disabled:opacity-40"
                  :title="locale.t('pulse.report', 'Пожаловаться администратору')">
            <Flag class="size-3.5" />
          </button>
        </div>
      </div>
      <p v-else class="py-6 text-center text-sm text-text3">
        {{ locale.t('pulse.waiting', 'Пока никто не ответил') }}
      </p>
    </template>
  </div>
</template>
