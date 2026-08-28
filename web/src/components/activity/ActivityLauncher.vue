<script setup>
// ActivityLauncher — выбор категории и подтверждение (PLAN-ACTIVITIES §10).
//
// Подтверждение — ЕДИНАЯ модалка на все категории («Вы выбрали X, подтвердить?»), а не
// своя у каждой: шесть почти одинаковых диалогов разъезжаются формулировками уже на
// третьем, и человек перестаёт их читать.
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { X, Presentation, ListChecks, Trophy, BarChart3, Gauge, Timer, ChevronLeft } from '@lucide/vue'
import AppButton from '@/components/ui/AppButton.vue'
import { useLocaleStore } from '@/stores/locale'
import { useAuthStore } from '@/stores/auth'
import { useActivityStore } from '@/stores/activity'
import { activitiesApi } from '@/api/endpoints'
import QuizEditor from './quiz/QuizEditor.vue'
import ActivityWheel from './ActivityWheel.vue'

const props = defineProps({ conversationId: { type: String, required: true } })
const emit = defineEmits(['close'])
const locale = useLocaleStore()
const act = useActivityStore()
//Видимость ссылки на журнал. Настоящая проверка прав — на сервере (эндпоинт
//откажет студенту сам); здесь только то, показывать ли ссылку.
const canSeeJournal = computed(() => ['teacher', 'admin'].includes(useAuthStore().user?.role))

//⚠️ Порядок здесь — это порядок ПО КОЛЕСУ, по часовой стрелке от 12 часов. Меняешь
//местами — у людей меняется мышечная память: в радиальном меню на место жмут не глядя.
//Эмодзи, а не только иконка Lucide: в колесе они различимы боковым зрением, потому что
//цветные, а монохромная иконка на цветном секторе теряется.
const KINDS = [
  { id: 'board', icon: Presentation, emoji: '🖊️' },
  { id: 'quiz', icon: ListChecks, emoji: '📝' },
  { id: 'contest', icon: Trophy, emoji: '🏆' },
  { id: 'poll', icon: BarChart3, emoji: '📊' },
  { id: 'pulse', icon: Gauge, emoji: '🌡️' },
  { id: 'timer', icon: Timer, emoji: '⏱️' },
]

const chosen = ref('')                 // '' — сетка категорий, иначе экран параметров

/**
 * Esc — единственный способ закрыть колесо с клавиатуры.
 *
 * ⚠️ Появился вместе с прозрачным экраном выбора: раньше закрытие держалось на крестике
 * в шапке карточки, а карточки на этом шаге больше нет. Без Esc человек, дошедший сюда
 * с клавиатуры, оказался бы заперт в колесе.
 */
function onKey(e) {
  if (e.key !== 'Escape') return
  if (chosen.value) { chosen.value = '' } else { emit('close') }
}
onMounted(() => window.addEventListener('keydown', onKey))
onUnmounted(() => window.removeEventListener('keydown', onKey))
const busy = ref(false)
const title = ref('')

// Параметры по категориям.
const sheet = ref('blank')
const continueBoardId = ref('')
const boards = ref([])
const durationMin = ref(5)
const pulseSeconds = ref(60)
const question = ref('')
const options = ref(['', ''])
const quizId = ref('')
const quizzes = ref([])
const quizScope = ref('mine')
const quizSearch = ref('')
const limitSec = ref(30)
const editorFor = ref(null)      // null — закрыт; '' — новая викторина; id — правка

const chosenLabel = computed(() => locale.t(`activity.kind.${chosen.value}`, chosen.value))

async function choose(kind) {
  chosen.value = kind
  if (kind === 'board') {
    try {
      const { data } = await activitiesApi.boards(props.conversationId)
      boards.value = data.boards || []
    } catch { boards.value = [] }
  }
  if (kind === 'quiz' || kind === 'contest') await loadQuizzes()
}

watch(() => chosen.value, (k) => { if (k === 'quiz' || k === 'contest') loadQuizzes() })

async function loadQuizzes() {
  try {
    //Библиотека РАЗДЕЛЬНАЯ: у соревнования свои наборы, у викторины свои. Общий список
    //заставлял гадать, что откуда запускается, и позволял выбрать для соревнования набор
    //с заданиями, которые оно не принимает (порядок, сопоставление).
    const { data } = await activitiesApi.quizzes({ scope: quizScope.value, q: quizSearch.value,
                                                  kind: chosen.value === 'contest' ? 'contest' : 'quiz' })
    quizzes.value = data.quizzes || []
  } catch { quizzes.value = [] }
}

// Показать ли итог всем после завершения. По умолчанию да: иначе победителя не увидит
// никто, кроме автора. Выключается, когда вопрос чувствительный.
const revealResults = ref(true)

// Срок опроса. Сервер по умолчанию ставит сутки и принимает duration_s (30 с .. 7 дней,
// 0 — без срока); здесь даём выбрать пресетом, как в Telegram.
const POLL_DURATIONS = [3600, 4 * 3600, 8 * 3600, 24 * 3600, 3 * 24 * 3600, 0]
const pollDuration = ref(24 * 3600)
function durLabel(s) {
  if (!s) return locale.t('poll.durNone', 'Без срока')
  if (s % 86400 === 0) return locale.t('poll.durDays', { n: s / 86400 })
  return locale.t('poll.durHours', { n: s / 3600 })
}

function addOption() { if (options.value.length < 12) options.value.push('') }
function removeOption(i) { if (options.value.length > 2) options.value.splice(i, 1) }

const canStart = computed(() => {
  if (chosen.value === 'poll') {
    return question.value.trim() && options.value.filter((o) => o.trim()).length >= 2
  }
  if (chosen.value === 'quiz' || chosen.value === 'contest') return !!quizId.value
  if (chosen.value === 'timer') return durationMin.value > 0
  return !!chosen.value
})

function params() {
  if (chosen.value === 'board') {
    const p = { sheet: sheet.value }
    if (continueBoardId.value) p.continue_board_id = continueBoardId.value
    return p
  }
  if (chosen.value === 'timer') return { duration_s: Math.round(durationMin.value * 60) }
  if (chosen.value === 'pulse') return { duration_s: pulseSeconds.value }
  if (chosen.value === 'poll') {
    return {
      question: question.value.trim(),
      options: options.value.map((o) => o.trim()).filter(Boolean),
      reveal_results: revealResults.value,
      duration_s: pollDuration.value,
    }
  }
  if (chosen.value === 'contest') return { quiz_id: quizId.value, limit_ms: limitSec.value * 1000 }
  return { quiz_id: quizId.value }
}

async function confirm() {
  busy.value = true
  const ok = await act.start(props.conversationId, chosen.value, params(), title.value.trim())
  busy.value = false
  if (ok) emit('close')
}
</script>

<template>
  <!-- ЭКРАН ВЫБОРА: оверлеем является ТОЛЬКО КОЛЕСО (требование Влада к прототипу).
       Ни затемняющей подложки, ни карточки под ним, ни шапки с заголовком: колесо и так
       называет каждую активность, а рамка вокруг радиального меню возвращала ему вид
       «окна с настройками», от которого от сетки 3×2 и уходили.
       ⚠️ Оверлей прозрачный, но КЛИКАБЕЛЬНЫЙ (без `pointer-events: none`): сквозные
       клики попадали бы по журналу и кнопкам под колесом — человек, промахнувшись мимо
       сектора, запускал бы что-то на странице позади. Клик мимо закрывает, Esc тоже. -->
  <div v-if="!chosen" class="fixed inset-0 z-[70] flex items-center justify-center p-3"
       @click.self="emit('close')">
    <!-- Почему колесо и как оно устроено — в докстринге ActivityWheel.vue. Ссылка на
         журнал живёт во ВТУЛКЕ: журнал относится ко всем шести активностям сразу. -->
    <ActivityWheel :kinds="KINDS" :can-see-journal="canSeeJournal"
                   @choose="choose" @journal="act.openJournal(conversationId)" />
  </div>

  <!-- ЭКРАН ПАРАМЕТРОВ: обычная модалка — здесь поля ввода, и им нужны и подложка, и
       шапка с «назад». -->
  <div v-else class="fixed inset-0 z-[70] flex items-center justify-center bg-black/50 p-3"
       @click.self="emit('close')">
    <div class="flex max-h-[90vh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl border border-border2 bg-card shadow-xl">
      <div class="flex items-center gap-2 border-b border-border2 px-4 py-3">
        <button type="button" @click="chosen = ''"
                class="rounded-lg p-1 text-text3 hover:text-accent">
          <ChevronLeft class="size-5" />
        </button>
        <h2 class="min-w-0 flex-1 truncate text-base font-semibold text-text">{{ chosenLabel }}</h2>
        <button type="button" @click="emit('close')" class="rounded-lg p-1 text-text3 hover:text-accent">
          <X class="size-5" />
        </button>
      </div>

      <div class="min-h-0 flex-1 overflow-y-auto p-4">
        <div class="flex flex-col gap-3">
          <label class="flex flex-col gap-1">
            <span class="text-xs font-medium text-text2">{{ locale.t('activity.launcher.name', 'Название (необязательно)') }}</span>
            <input v-model="title" type="text" maxlength="120"
                   class="w-full rounded-lg border border-border2 bg-bg2 px-3 py-2 text-sm text-text" />
          </label>

          <!-- Доска -->
          <template v-if="chosen === 'board'">
            <div class="flex flex-wrap gap-2">
              <button v-for="s in ['blank', 'grid', 'lined']" :key="s" type="button" @click="sheet = s"
                      class="rounded-lg border px-3 py-1.5 text-sm"
                      :class="sheet === s ? 'border-accent bg-accent-glow text-accent' : 'border-border2 text-text2'">
                {{ locale.t(`board.sheet.${s}`, s) }}
              </button>
            </div>
            <label v-if="boards.length" class="flex flex-col gap-1">
              <span class="text-xs font-medium text-text2">{{ locale.t('board.continue', 'Продолжить доску') }}</span>
              <select v-model="continueBoardId" class="w-full rounded-lg border border-border2 bg-bg2 px-3 py-2 text-sm text-text">
                <option value="">{{ locale.t('board.blankStart', 'Начать с чистой') }}</option>
                <option v-for="b in boards" :key="b.id" :value="b.id">
                  {{ b.title || locale.t('activity.kind.board', 'Доска') }} · {{ b.strokes_count }}
                </option>
              </select>
            </label>
          </template>

          <!-- Тайм-бокс -->
          <label v-else-if="chosen === 'timer'" class="flex flex-col gap-1">
            <span class="text-xs font-medium text-text2">{{ locale.t('activity.timer.minutes', 'Минут') }}</span>
            <input v-model.number="durationMin" type="number" min="1" max="360"
                   class="w-full rounded-lg border border-border2 bg-bg2 px-3 py-2 text-sm text-text" />
          </label>

          <!-- Срез понимания -->
          <label v-else-if="chosen === 'pulse'" class="flex flex-col gap-1">
            <span class="text-xs font-medium text-text2">{{ locale.t('activity.pulse.seconds', 'Секунд на ответ') }}</span>
            <input v-model.number="pulseSeconds" type="number" min="10" max="1800"
                   class="w-full rounded-lg border border-border2 bg-bg2 px-3 py-2 text-sm text-text" />
          </label>

          <!-- Опрос -->
          <template v-else-if="chosen === 'poll'">
            <label class="flex flex-col gap-1">
              <span class="text-xs font-medium text-text2">{{ locale.t('poll.question', 'Вопрос') }}</span>
              <input v-model="question" type="text" maxlength="500"
                     class="w-full rounded-lg border border-border2 bg-bg2 px-3 py-2 text-sm text-text" />
            </label>
            <div class="flex flex-col gap-2">
              <div v-for="(o, i) in options" :key="i" class="flex min-w-0 items-center gap-2">
                <input v-model="options[i]" type="text" maxlength="500"
                       :placeholder="locale.t('poll.option', 'Вариант')"
                       class="min-w-0 flex-1 rounded-lg border border-border2 bg-bg2 px-3 py-2 text-sm text-text" />
                <button type="button" @click="removeOption(i)" :disabled="options.length <= 2"
                        class="shrink-0 rounded-lg p-1.5 text-text3 hover:text-red disabled:opacity-40">
                  <X class="size-4" />
                </button>
              </div>
              <AppButton variant="ghost" size="sm" @click="addOption">
                {{ locale.t('poll.addOption', 'Добавить вариант') }}
              </AppButton>
            </div>
            <label class="flex flex-col gap-1">
              <span class="text-xs font-medium text-text2">{{ locale.t('poll.deadline', 'Срок') }}</span>
              <select v-model.number="pollDuration"
                      class="w-full rounded-lg border border-border2 bg-bg2 px-3 py-2 text-sm text-text">
                <option v-for="s in POLL_DURATIONS" :key="s" :value="s">{{ durLabel(s) }}</option>
              </select>
            </label>
            <label class="flex items-start gap-2 text-xs text-text2">
              <input v-model="revealResults" type="checkbox" class="mt-0.5 accent-accent" />
              <span>{{ locale.t('poll.revealOption', 'Показать итог всем после завершения') }}</span>
            </label>
          </template>

          <!-- Викторина и соревнование -->
          <template v-else>
            <div class="flex flex-wrap items-center gap-2">
              <button v-for="s in ['mine', 'college', 'stock']" :key="s" type="button"
                      @click="quizScope = s; loadQuizzes()"
                      class="rounded-lg border px-3 py-1.5 text-sm"
                      :class="quizScope === s ? 'border-accent bg-accent-glow text-accent' : 'border-border2 text-text2'">
                {{ locale.t(`quiz.scope.${s}`, s) }}
              </button>
              <input v-model="quizSearch" @input="loadQuizzes" type="search"
                     :placeholder="locale.t('quiz.search', 'Поиск по названию и тегам')"
                     class="min-w-0 flex-1 rounded-lg border border-border2 bg-bg2 px-3 py-2 text-sm text-text" />
              <AppButton variant="ghost" size="sm" @click="editorFor = ''">
                {{ locale.t('quiz.create', 'Новая викторина') }}
              </AppButton>
            </div>
            <div class="flex max-h-64 flex-col gap-1.5 overflow-y-auto">
              <button v-for="q in quizzes" :key="q.id" type="button" @click="quizId = q.id"
                      class="flex min-w-0 flex-col items-start rounded-lg border px-3 py-2 text-left"
                      :class="quizId === q.id ? 'border-accent bg-accent-glow' : 'border-border2 bg-bg2'">
                <span class="flex min-w-0 items-center gap-1.5">
                  <span class="min-w-0 truncate text-sm font-semibold text-text">{{ q.title }}</span>
                  <span role="button" tabindex="0" @click.stop="editorFor = q.id" @keydown.enter.stop="editorFor = q.id"
                        class="shrink-0 text-[11px] text-text3 underline hover:text-accent">
                    {{ locale.t('quiz.openEditor', 'править') }}
                  </span>
                </span>
                <span class="truncate text-[11px] text-text3">
                  {{ locale.t('quiz.questionsCount', { n: q.questions_count }) }}
                  <span v-if="q.tags.length">· {{ q.tags.join(', ') }}</span>
                </span>
              </button>
              <p v-if="!quizzes.length" class="py-4 text-center text-sm text-text3">
                {{ locale.t('quiz.empty', 'Викторин пока нет') }}
              </p>
            </div>
            <label v-if="chosen === 'contest'" class="flex flex-col gap-1">
              <span class="text-xs font-medium text-text2">{{ locale.t('quiz.limitSeconds', 'Секунд на вопрос') }}</span>
              <input v-model.number="limitSec" type="number" min="5" max="300"
                     class="w-full rounded-lg border border-border2 bg-bg2 px-3 py-2 text-sm text-text" />
            </label>
          </template>

          <p v-if="act.error" class="text-sm text-red">{{ act.error }}</p>
        </div>
      </div>

      <!-- ⚠️ Отдельной ссылки «Журнал активностей» здесь больше НЕТ: она переехала во
           втулку колеса. Две двери в один раздел на одном экране — это не удобство, а
           лишний вопрос «в чём разница». Права те же: видна только тому, кто вправе
           запускать (студенту таблица чужих результатов не полагается). -->

      <div class="flex items-center justify-between gap-2 border-t border-border2 px-4 py-3">
        <span class="min-w-0 truncate text-xs text-text3">
          {{ locale.t('activity.launcher.confirm', { kind: chosenLabel }) }}
        </span>
        <div class="flex shrink-0 gap-2">
          <AppButton variant="ghost" size="sm" @click="emit('close')">
            {{ locale.t('common.cancel', 'Отмена') }}
          </AppButton>
          <AppButton size="sm" :disabled="!canStart || busy" @click="confirm">
            {{ locale.t('activity.launcher.start', 'Запустить') }}
          </AppButton>
        </div>
      </div>
    </div>
  </div>

  <QuizEditor v-if="editorFor !== null" :quiz-id="editorFor"
              :kind="chosen === 'contest' ? 'contest' : 'quiz'"
              @close="editorFor = null" @saved="loadQuizzes" />
</template>
