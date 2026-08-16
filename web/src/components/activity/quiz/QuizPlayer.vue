<script setup>
// QuizPlayer — прохождение викторины и соревнования (PLAN-ACTIVITIES §8.4, §8.5).
//
// 🔑 Асинхронная викторина проходится ЛОКАЛЬНО, на сервер уходит ОДИН запрос со всеми
// ответами. Один запрос на участника вместо одного на вопрос — 30 вместо 600 на группу в
// 30 человек, и сеть, моргнувшая посреди прохождения, ничего не теряет.
//
// 🔒 Проверку ответов делает СЕРВЕР. Здесь её нет и быть не может: для локальной проверки
// нужен ключ, а любой студент прочитает его в инструментах разработчика до начала.
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import AppButton from '@/components/ui/AppButton.vue'
import QuizResult from './QuizResult.vue'
import ContestPodium from './ContestPodium.vue'
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
const showBoard = ref(false)
// Выбранный, но ЕЩЁ НЕ подтверждённый вариант соревнования. Раньше клик сразу уходил на
// сервер: промах пальцем по соседней плитке стоил вопроса, а подтвердить или передумать
// было нечем — и человек даже не понимал, засчитан ли ответ.
const draft = ref(null)

// Отсчёт до конца ВОПРОСА. Считаем от абсолютного времени окончания, присланного
// сервером: у каждого свои часы, и локальный лимит разошёлся бы между устройствами.
const qEndsAt = computed(() => Date.parse(act.state.question_ends_at || ''))
const qLeft = computed(() => {
  if (!Number.isFinite(qEndsAt.value)) return null
  return Math.max(0, Math.round((qEndsAt.value - nowMs.value) / 1000))
})
const started = computed(() => Number(act.state.question_index ?? -1) >= 0)
const limitSec = computed(() => Math.round(Number(act.state.limit_ms || 30000) / 1000))
const segments = computed(() => Number(act.state.total_questions || total.value || 0) || 1)
const finishedCount = computed(() => (act.state.progress || []).filter((r) => r.done).length)
const timeLimit = ref(0)          //секунды на весь тест, 0 — без ограничения
const nowMs = ref(Date.now())
let quizTick = null

// Счётчик идёт от ОТКРЫТИЯ теста, а не от запуска активности: человек мог зайти в беседу
// через десять минут после старта, и общий отсчёт съел бы его время ни за что.
const leftS = computed(() => {
  if (!timeLimit.value) return null
  return Math.max(0, timeLimit.value - Math.round((nowMs.value - startedAt.value) / 1000))
})
const leftLabel = computed(() => {
  const s = leftS.value
  if (s === null) return ''
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`
})

// Палитра плиток — как в Kahoot: четыре крупных цветных поля, узнаваемых с проектора
// через весь кабинет. Цвета ЛИТЕРАЛЬНЫЕ, а не токены темы: плитка обязана выглядеть
// одинаково в светлой и тёмной теме (это «поле ответа», а не элемент оформления), и
// различаться между собой человек должен по цвету, а не по подписи.
const TILE = [
  { bg: '#e21b3c', ring: '#ff5c74' },   // 1 — красный
  { bg: '#1368ce', ring: '#4b95ee' },   // 2 — синий
  { bg: '#d89e00', ring: '#f5c53d' },   // 3 — жёлтый
  { bg: '#26890c', ring: '#4fbb2e' },   // 4 — зелёный
]
//Вариантов может быть больше четырёх — палитру повторяем по кругу, а не оставляем
//бесцветные плитки: серая плитка среди цветных читается как недоступная.
const tileOf = (i) => TILE[i % TILE.length]

const isContest = computed(() => act.kind === 'contest')
const current = computed(() => questions.value[isContest.value ? 0 : index.value] || null)
const answeredHere = computed(() => !!act.state.answered)

async function load() {
  try {
    const { data } = await activitiesApi.questions(act.activity.id)
    questions.value = data.questions || []
    total.value = Number(data.total || 0)
    timeLimit.value = Number(data.time_limit_s || 0)
    if (!isContest.value) index.value = 0
  } catch { questions.value = [] }
}

onMounted(() => {
  load()
  quizTick = setInterval(() => {
    nowMs.value = Date.now()
    //Время вышло — отправляем то, что успел человек. Молча оставить его на экране с
    //нулём значило бы потерять уже данные ответы.
    if (leftS.value === 0 && !result.value && !isContest.value && !act.isHost && !busy.value) {
      submitAll()
    }
  }, 1000)
})
onBeforeUnmount(() => { if (quizTick) clearInterval(quizTick) })
// В соревновании вопрос показывает ХОСТ — перечитываем по кадру со сменой номера.
watch(() => act.state.question_index, () => {
  if (!isContest.value) return
  draft.value = null            //новый вопрос — выбор с чистого листа
  load()
})

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

// Отправляем ТОЛЬКО число пройденных заданий — ни одного ответа. Это не возврат к
// «запрос на каждый вопрос»: тяжёлой была проверка с записью в базу, а здесь сервер
// кладёт число в память процесса и пересылает ведущему.
function goForward() {
  index.value += 1
  if (act.isHost) return
  activitiesApi.progress(act.activity.id, index.value).catch(() => {})
}

async function submitAll() {
  busy.value = true
  try {
    const { data } = await activitiesApi.submit(act.activity.id, answers.value,
                                                Date.now() - startedAt.value)
    result.value = data
  } catch { /* noop */ } finally { busy.value = false }
}

/** Подтвердить выбранный вариант. После подтверждения сменить его нельзя (баллы зависят
 *  от скорости, и «сначала наугад, потом исправлю» обесценило бы соревнование). */
async function confirmAnswer() {
  if (draft.value === null || answeredHere.value || busy.value) return
  await answerContest(draft.value)
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
    <!-- Соревнование заканчивается ПЬЕДЕСТАЛОМ: места объявляют вслух, и в этот момент
         на экране должны быть трое, а не список из тридцати строк. Полная таблица —
         по кнопке внутри. -->
    <template v-if="act.activity?.status === 'finished' && isContest">
      <ContestPodium :results="board" />
    </template>

    <template v-else-if="act.activity?.status === 'finished'">
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
      <QuizResult :result="result" />
      <!-- Кнопка выхода обязана быть ЗДЕСЬ. Без неё экран результата был тупиком: выйти
           можно было только крестиком в шапке, а свернуть — значило вернуться в тест.
           Результат к этому моменту уже у преподавателя (его отправил `submitAll`),
           поэтому кнопка просто закрывает окно и ничего не теряет. -->
      <div class="flex justify-center pb-2">
        <AppButton size="sm" @click="act.hide()">
          {{ locale.t('quiz.finish', 'Завершить') }}
        </AppButton>
      </div>
    </template>

    <!-- ВЕДУЩИЙ — всегда мониторинг, а не задание: он тест не решает. Ветка стоит ВЫШЕ
         соревнования намеренно: раньше `isContest` перехватывал её, и преподаватель,
         запустивший соревнование, смотрел на первый вопрос. -->
    <template v-else-if="act.isHost">
      <div class="flex flex-wrap items-baseline gap-3">
        <span class="text-3xl font-bold text-accent">{{ finishedCount }}</span>
        <span class="text-sm text-text3">
          {{ locale.t('quiz.doneOf', { n: finishedCount, total: (act.state.progress || []).length }) }}
        </span>
        <AppButton v-if="isContest" size="sm" class="ml-auto" :disabled="busy" @click="nextQuestion">
          {{ locale.t('quiz.next', 'Следующий вопрос') }}
        </AppButton>
      </div>

      <!-- Шкала на каждого: делится на столько частей, сколько заданий, и заполняется
           по мере прохождения. Одно число «закончил / не закончил» не отвечало на
           главный вопрос преподавателя — ждать ещё или уже собирать. -->
      <div v-if="(act.state.progress || []).length" class="flex flex-col gap-2">
        <div v-for="r in act.state.progress" :key="r.user_id" class="flex min-w-0 items-center gap-2">
          <span class="w-36 shrink-0 truncate text-sm text-text">{{ r.name }}</span>
          <span class="flex min-w-0 flex-1 gap-0.5">
            <span v-for="i in segments" :key="i"
                  class="h-2.5 flex-1 rounded-[2px] transition-colors"
                  :class="i <= r.walked ? (r.done ? 'bg-accent' : 'bg-accent/55') : 'bg-bg2'" />
          </span>
          <span class="w-16 shrink-0 text-right text-xs tabular-nums text-text3">
            {{ r.done ? `${r.correct_count}/${r.total_count}` : `${r.walked}/${segments}` }}
          </span>
        </div>
      </div>
      <p v-else class="py-8 text-center text-sm text-text3">
        {{ locale.t('quiz.nobodyFinished', 'Пока никто не начал') }}
      </p>
    </template>

    <!-- Соревнование: вопрос по команде хоста -->
    <template v-else-if="isContest">
      <!-- До старта: у ведущего кнопка «Старт» с честным предупреждением о времени,
           у остальных — ожидание. Раньше здесь стояло «Нажмите Следующий вопрос», и
           преподаватель не знал, сколько секунд получит группа на задание. -->
      <div v-if="!started" class="flex flex-col items-center gap-3 py-10 text-center">
        <p class="text-sm text-text2">
          {{ locale.t('quiz.perQuestion', { n: limitSec }) }}
        </p>
        <AppButton v-if="act.isHost" :disabled="busy" @click="nextQuestion">
          {{ locale.t('quiz.start', 'Старт') }}
        </AppButton>
        <p v-else class="text-sm text-text3">{{ locale.t('quiz.waitHost', 'Ждём преподавателя…') }}</p>
      </div>

      <template v-else-if="current">
        <div class="flex items-center justify-between gap-2">
          <p class="text-xs text-text3">{{ locale.t('quiz.questionNo', { n: (act.state.question_index || 0) + 1, total }) }}</p>
          <!-- Отсчёт вопроса виден ВСЕМ: он объясняет, почему вопрос вот-вот сменится. -->
          <span v-if="qLeft !== null"
                class="rounded-full bg-bg2 px-2.5 py-0.5 text-sm font-bold tabular-nums"
                :class="qLeft <= 5 ? 'text-red' : 'text-text2'">{{ qLeft }}</span>
        </div>
        <h3 class="text-lg font-semibold text-text">{{ current.text }}</h3>
        <span class="self-start rounded-full bg-bg2 px-2 py-0.5 text-tiny text-text3">
          {{ locale.t(`quiz.type.${current.type}`, current.type) }}
        </span>

        <!-- Плитки: выбранная ЧУТЬ БОЛЬШЕ, остальные тусклее — до подтверждения видно,
             что именно выбрано, и промах пальцем можно исправить. -->
        <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <button v-for="(o, i) in current.options" :key="o.id" type="button"
                  :disabled="answeredHere || busy"
                  @click="draft = o.id"
                  class="flex min-h-[104px] min-w-0 items-center gap-3 rounded-2xl px-4 py-4 text-left transition-all disabled:cursor-default"
                  :style="{ backgroundColor: tileOf(i).bg,
                            outline: draft === o.id ? `3px solid ${tileOf(i).ring}` : 'none',
                            outlineOffset: '2px' }"
                  :class="draft !== null && draft !== o.id ? 'scale-[0.97] opacity-45'
                          : draft === o.id ? 'scale-[1.03]' : ''">
            <span class="grid size-8 shrink-0 place-items-center rounded-lg bg-black/25 text-base font-bold text-white">
              {{ i + 1 }}
            </span>
            <span class="min-w-0 flex-1 break-words text-lg font-bold leading-tight text-white">{{ o.text }}</span>
          </button>
        </div>

        <AppButton v-if="draft !== null && !answeredHere" :disabled="busy" @click="confirmAnswer">
          {{ locale.t('quiz.confirm', 'Подтвердить') }}
        </AppButton>
        <p v-if="answeredHere" class="text-sm text-text2">
          {{ locale.t('quiz.answered', 'Ответ принят') }} · {{ locale.t('quiz.myScore', { n: act.state.my_score || 0 }) }}
        </p>
      </template>

      <!-- Табло между вопросами — то, ради чего в соревнование и играют. Видят все:
           места всё равно объявляются вслух, а скрытые баллы убирают из игры единственное,
           что заставляет тянуться к следующему вопросу. -->
      <div v-if="showBoard && (act.state.board || []).length" class="flex flex-col gap-1.5 border-t border-border2 pt-3">
        <div v-for="r in act.state.board.slice(0, 10)" :key="r.user_id"
             class="flex min-w-0 items-center gap-2 rounded-lg px-3 py-1.5"
             :class="r.place <= 3 ? 'bg-accent/10' : 'bg-bg2'">
          <span class="w-7 shrink-0 text-center text-sm font-bold"
                :class="r.place <= 3 ? 'text-accent' : 'text-text3'">
            {{ r.place === 1 ? '🥇' : r.place === 2 ? '🥈' : r.place === 3 ? '🥉' : r.place }}
          </span>
          <span class="min-w-0 flex-1 truncate text-sm text-text">{{ r.name }}</span>
          <span class="shrink-0 text-sm font-semibold tabular-nums text-accent">{{ r.score }}</span>
        </div>
      </div>

      <div class="flex flex-wrap items-center gap-2 border-t border-border2 pt-3">
        <AppButton v-if="act.isHost" size="sm" :disabled="busy" @click="nextQuestion">
          {{ locale.t('quiz.next', 'Следующий вопрос') }}
        </AppButton>
        <span class="text-xs text-text3">
          {{ locale.t('quiz.answeredCount', { n: act.state.answered_count || 0 }) }}
        </span>
        <AppButton variant="ghost" size="sm" class="ml-auto" @click="showBoard = !showBoard">
          {{ locale.t('quiz.leaderboard', 'Лидерборд') }}
        </AppButton>
      </div>
    </template>

    <!-- Ведущему показываем ХОД, а не задание: он тест не проходит, ему нужно видеть,
         кто закончил, а кого ещё ждать. Раньше здесь открывался первый вопрос — то есть
         преподаватель смотрел на то, чем не пользуется, а нужное было недоступно. -->
    <!-- Асинхронная викторина: все вопросы, свой темп, одна отправка -->
    <template v-else>
      <div v-if="!current" class="py-10 text-center text-sm text-text3">
        {{ locale.t('quiz.empty', 'Викторин пока нет') }}
      </div>
      <template v-else>
        <div class="flex items-center justify-between gap-2">
          <p class="text-xs text-text3">{{ locale.t('quiz.questionNo', { n: index + 1, total: questions.length }) }}</p>
          <span v-if="leftLabel" class="rounded-full bg-bg2 px-2 py-0.5 text-xs font-bold tabular-nums"
                :class="leftS <= 60 ? 'text-red' : 'text-text2'">{{ leftLabel }}</span>
        </div>
        <h3 class="text-lg font-semibold text-text">{{ current.text }}</h3>
        <!-- Тип задания подписан: «выберите один» и «выберите несколько» выглядят
             одинаково, и человек, отметивший один вариант, не знает, ждут ли от него ещё. -->
        <span class="self-start rounded-full bg-bg2 px-2 py-0.5 text-tiny text-text3">
          {{ locale.t(`quiz.type.${current.type}`, current.type) }}
        </span>

        <!-- Сопоставление: слева вопрос, справа ВЫБОР из готовых половин.
             Раньше здесь было поле ввода — попасть в ответ можно было только дословным
             совпадением, то есть задание проверяло грамотность, а не знание.
             🔒 Список половин перемешан сервером и не привязан к строкам, поэтому сам по
             себе ключа не даёт: это те же слова, что и так на экране, в другом порядке. -->
        <div v-if="current.type === 'match'" class="flex flex-col gap-2">
          <div v-for="o in current.options" :key="o.id"
               class="flex min-w-0 flex-wrap items-center gap-2 rounded-xl border border-border2 bg-bg2 px-3 py-2">
            <span class="min-w-0 flex-1 break-words text-sm text-text">{{ o.text }}</span>
            <span class="shrink-0 text-text3">—</span>
            <select :value="(answers[current.id] || {})[o.id] || ''"
                    @change="setMatch(current, o.id, $event.target.value)"
                    class="min-w-[9rem] shrink-0 rounded-lg border border-border2 bg-card px-2 py-1.5 text-sm text-text">
              <option value="">{{ locale.t('quiz.matchPlaceholder', 'Выберите пару') }}</option>
              <option v-for="k in (current.match_pool || [])" :key="k" :value="k">{{ k }}</option>
            </select>
          </div>
        </div>

        <!-- Порядок — список (там важна последовательность, а не цвет).
             Выбор одного/нескольких — те же плитки, что в соревновании. -->
        <div v-else-if="current.type === 'order'" class="flex flex-col gap-2">
          <button v-for="o in current.options" :key="o.id" type="button"
                  @click="placeOrder(current, o.id)"
                  class="flex min-w-0 items-center gap-2 rounded-xl border px-3 py-2.5 text-left text-sm"
                  :class="orderPos(current, o.id) ? 'border-accent bg-accent-glow' : 'border-border2 bg-bg2 hover:border-accent'">
            <span v-if="orderPos(current, o.id)"
                  class="size-5 shrink-0 rounded-full bg-accent text-center text-xs font-bold leading-5 text-white">
              {{ orderPos(current, o.id) }}
            </span>
            <span class="min-w-0 flex-1 truncate text-text">{{ o.text }}</span>
          </button>
        </div>
        <div v-else class="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <button v-for="(o, i) in current.options" :key="o.id" type="button"
                  @click="pick(current, o.id)"
                  class="flex min-h-[104px] min-w-0 items-center gap-3 rounded-2xl px-4 py-4 text-left transition-transform hover:scale-[1.02]"
                  :style="{ backgroundColor: tileOf(i).bg,
                            outline: chosen(current, o.id) ? `3px solid ${tileOf(i).ring}` : 'none',
                            outlineOffset: '2px' }">
            <span class="grid size-8 shrink-0 place-items-center rounded-lg bg-black/25 text-base font-bold text-white">
              {{ i + 1 }}
            </span>
            <span class="min-w-0 flex-1 break-words text-lg font-bold leading-tight text-white">{{ o.text }}</span>
          </button>
        </div>

        <div class="flex flex-wrap items-center justify-between gap-2 border-t border-border2 pt-3">
          <AppButton variant="ghost" size="sm" :disabled="index === 0" @click="index -= 1">
            {{ locale.t('quiz.prev', 'Назад') }}
          </AppButton>
          <AppButton v-if="index < questions.length - 1" size="sm" @click="goForward">
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
