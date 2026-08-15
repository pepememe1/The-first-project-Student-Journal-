<script setup>
// QuizPlayer — прохождение викторины и соревнования (PLAN-ACTIVITIES §8.4, §8.5).
//
// 🔑 Асинхронная викторина проходится ЛОКАЛЬНО, на сервер уходит ОДИН запрос со всеми
// ответами. Один запрос на участника вместо одного на вопрос — 30 вместо 600 на группу в
// 30 человек, и сеть, моргнувшая посреди прохождения, ничего не теряет.
//
// 🔒 Проверку ответов делает СЕРВЕР. Здесь её нет и быть не может: для локальной проверки
// нужен ключ, а любой студент прочитает его в инструментах разработчика до начала.
import { ref, computed, onMounted, watch } from 'vue'
import AppButton from '@/components/ui/AppButton.vue'
import { useLocaleStore } from '@/stores/locale'
import { useActivityStore } from '@/stores/activity'
import { activitiesApi } from '@/api/endpoints'

const locale = useLocaleStore()
const act = useActivityStore()

const questions = ref([])
const index = ref(0)
const total = ref(0)
const answers = ref({})
const result = ref(null)
const board = ref([])
const busy = ref(false)
const startedAt = ref(Date.now())

const isContest = computed(() => act.kind === 'contest')
const current = computed(() => questions.value[isContest.value ? 0 : index.value] || null)
const answeredHere = computed(() => !!act.state.answered)

async function load() {
  try {
    const { data } = await activitiesApi.questions(act.activity.id)
    questions.value = data.questions || []
    total.value = Number(data.total || 0)
    if (!isContest.value) index.value = 0
  } catch { questions.value = [] }
}

onMounted(load)
// В соревновании вопрос показывает ХОСТ — перечитываем по кадру со сменой номера.
watch(() => act.state.question_index, () => { if (isContest.value) load() })

function pick(q, optId) {
  if (q.type === 'single') answers.value = { ...answers.value, [q.id]: optId }
  else if (q.type === 'multi') {
    const cur = new Set(answers.value[q.id] || [])
    if (cur.has(optId)) cur.delete(optId); else cur.add(optId)
    answers.value = { ...answers.value, [q.id]: [...cur] }
  }
}
function chosen(q, optId) {
  const a = answers.value[q.id]
  return q.type === 'multi' ? (a || []).includes(optId) : a === optId
}
// order: клик по варианту ставит его в конец собранной последовательности.
function placeOrder(q, optId) {
  const cur = [...(answers.value[q.id] || [])]
  const at = cur.indexOf(optId)
  if (at >= 0) cur.splice(at, 1); else cur.push(optId)
  answers.value = { ...answers.value, [q.id]: cur }
}
function orderPos(q, optId) {
  const at = (answers.value[q.id] || []).indexOf(optId)
  return at >= 0 ? at + 1 : ''
}
function setMatch(q, optId, key) {
  answers.value = { ...answers.value, [q.id]: { ...(answers.value[q.id] || {}), [optId]: key } }
}

async function submitAll() {
  busy.value = true
  try {
    const { data } = await activitiesApi.submit(act.activity.id, answers.value,
                                                Date.now() - startedAt.value)
    result.value = data
  } catch { /* noop */ } finally { busy.value = false }
}

async function answerContest(value) {
  busy.value = true
  try { await activitiesApi.answer(act.activity.id, value) } catch { /* noop */ }
  finally { busy.value = false }
}

async function nextQuestion() {
  busy.value = true
  try { await activitiesApi.next(act.activity.id) } catch { /* noop */ }
  finally { busy.value = false }
}

async function loadBoard() {
  try {
    const { data } = await activitiesApi.results(act.activity.id)
    board.value = data.results || []
  } catch { board.value = [] }
}
watch(() => act.activity?.status, (s) => { if (s === 'finished') loadBoard() })
</script>

<template>
  <div class="flex flex-col gap-4 py-4">
    <!-- Итоговая таблица -->
    <template v-if="act.activity?.status === 'finished'">
      <h3 class="text-lg font-semibold text-text">{{ locale.t('quiz.results', 'Результаты') }}</h3>
      <div class="flex flex-col gap-1.5">
        <div v-for="r in board" :key="r.user_id"
             class="flex min-w-0 items-center gap-2 rounded-lg border border-border2 bg-bg2 px-3 py-2">
          <!-- Награждение за 1–3 место (§8.5) — медаль вместо номера. -->
          <span class="w-7 shrink-0 text-center text-sm font-bold"
                :class="r.place <= 3 ? 'text-accent' : 'text-text3'">
            {{ r.place === 1 ? '🥇' : r.place === 2 ? '🥈' : r.place === 3 ? '🥉' : r.place }}
          </span>
          <span class="min-w-0 flex-1 truncate text-sm text-text">{{ r.name }}</span>
          <span class="shrink-0 text-sm font-semibold text-accent">{{ r.score }}</span>
          <span class="shrink-0 text-xs text-text3">{{ r.correct_count }}/{{ r.total_count }}</span>
        </div>
        <p v-if="!board.length" class="py-6 text-center text-sm text-text3">
          {{ locale.t('quiz.noResults', 'Никто не успел ответить') }}
        </p>
      </div>
    </template>

    <!-- Свой результат после отправки -->
    <template v-else-if="result">
      <div class="py-8 text-center">
        <div class="text-5xl font-bold text-accent">{{ result.score }}</div>
        <p class="mt-2 text-sm text-text2">
          {{ locale.t('quiz.correctOf', { n: result.correct_count, total: result.total_count }) }}
        </p>
      </div>
    </template>

    <!-- Соревнование: вопрос по команде хоста -->
    <template v-else-if="isContest">
      <div v-if="!current" class="py-10 text-center text-sm text-text3">
        {{ act.isHost ? locale.t('quiz.pressNext', 'Нажмите «Следующий вопрос»')
                      : locale.t('quiz.waitHost', 'Ждём преподавателя…') }}
      </div>
      <template v-else>
        <p class="text-xs text-text3">{{ locale.t('quiz.questionNo', { n: (act.state.question_index || 0) + 1, total }) }}</p>
        <h3 class="text-lg font-semibold text-text">{{ current.text }}</h3>
        <div class="flex flex-col gap-2">
          <button v-for="o in current.options" :key="o.id" type="button"
                  :disabled="answeredHere || busy"
                  @click="current.type === 'single' ? answerContest(o.id) : pick(current, o.id)"
                  class="min-w-0 rounded-xl border px-3 py-2.5 text-left text-sm disabled:opacity-60"
                  :class="chosen(current, o.id) ? 'border-accent bg-accent-glow' : 'border-border2 bg-bg2 hover:border-accent'">
            <span class="block truncate text-text">{{ o.text }}</span>
          </button>
        </div>
        <AppButton v-if="current.type === 'multi' && !answeredHere" :disabled="busy"
                   @click="answerContest(answers[current.id] || [])">
          {{ locale.t('quiz.answer', 'Ответить') }}
        </AppButton>
        <p v-if="answeredHere" class="text-sm text-text2">
          {{ locale.t('quiz.answered', 'Ответ принят') }} · {{ locale.t('quiz.myScore', { n: act.state.my_score || 0 }) }}
        </p>
      </template>
      <div v-if="act.isHost" class="flex flex-wrap items-center gap-2 border-t border-border2 pt-3">
        <AppButton size="sm" :disabled="busy" @click="nextQuestion">
          {{ locale.t('quiz.next', 'Следующий вопрос') }}
        </AppButton>
        <span class="text-xs text-text3">
          {{ locale.t('quiz.answeredCount', { n: act.state.answered_count || 0 }) }}
        </span>
      </div>
    </template>

    <!-- Асинхронная викторина: все вопросы, свой темп, одна отправка -->
    <template v-else>
      <div v-if="!current" class="py-10 text-center text-sm text-text3">
        {{ locale.t('quiz.empty', 'Викторин пока нет') }}
      </div>
      <template v-else>
        <p class="text-xs text-text3">{{ locale.t('quiz.questionNo', { n: index + 1, total: questions.length }) }}</p>
        <h3 class="text-lg font-semibold text-text">{{ current.text }}</h3>

        <div v-if="current.type === 'match'" class="flex flex-col gap-2">
          <div v-for="o in current.options" :key="o.id" class="flex min-w-0 items-center gap-2">
            <span class="min-w-0 flex-1 truncate text-sm text-text">{{ o.text }}</span>
            <input type="text" :value="(answers[current.id] || {})[o.id] || ''"
                   @input="setMatch(current, o.id, $event.target.value)"
                   :placeholder="locale.t('quiz.matchPlaceholder', 'Пара')"
                   class="w-32 shrink-0 rounded-lg border border-border2 bg-bg2 px-2 py-1.5 text-sm text-text" />
          </div>
        </div>
        <div v-else class="flex flex-col gap-2">
          <button v-for="o in current.options" :key="o.id" type="button"
                  @click="current.type === 'order' ? placeOrder(current, o.id) : pick(current, o.id)"
                  class="flex min-w-0 items-center gap-2 rounded-xl border px-3 py-2.5 text-left text-sm"
                  :class="(current.type === 'order' ? orderPos(current, o.id) : chosen(current, o.id))
                    ? 'border-accent bg-accent-glow' : 'border-border2 bg-bg2 hover:border-accent'">
            <span v-if="current.type === 'order' && orderPos(current, o.id)"
                  class="size-5 shrink-0 rounded-full bg-accent text-center text-xs font-bold leading-5 text-white">
              {{ orderPos(current, o.id) }}
            </span>
            <span class="min-w-0 flex-1 truncate text-text">{{ o.text }}</span>
          </button>
        </div>

        <div class="flex flex-wrap items-center justify-between gap-2 border-t border-border2 pt-3">
          <AppButton variant="ghost" size="sm" :disabled="index === 0" @click="index -= 1">
            {{ locale.t('quiz.prev', 'Назад') }}
          </AppButton>
          <AppButton v-if="index < questions.length - 1" size="sm" @click="index += 1">
            {{ locale.t('quiz.forward', 'Дальше') }}
          </AppButton>
          <AppButton v-else size="sm" :disabled="busy" @click="submitAll">
            {{ locale.t('quiz.submit', 'Завершить и отправить') }}
          </AppButton>
        </div>
      </template>
    </template>
  </div>
</template>
