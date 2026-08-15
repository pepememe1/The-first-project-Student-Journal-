<script setup>
// ActivityLauncher — выбор категории и подтверждение (PLAN-ACTIVITIES §10).
//
// Подтверждение — ЕДИНАЯ модалка на все категории («Вы выбрали X, подтвердить?»), а не
// своя у каждой: шесть почти одинаковых диалогов разъезжаются формулировками уже на
// третьем, и человек перестаёт их читать.
import { ref, computed } from 'vue'
import { X, Presentation, ListChecks, Trophy, BarChart3, Gauge, Timer, ChevronLeft } from '@lucide/vue'
import AppButton from '@/components/ui/AppButton.vue'
import { useLocaleStore } from '@/stores/locale'
import { useActivityStore } from '@/stores/activity'
import { activitiesApi } from '@/api/endpoints'
import QuizEditor from './quiz/QuizEditor.vue'

const props = defineProps({ conversationId: { type: String, required: true } })
const emit = defineEmits(['close'])
const locale = useLocaleStore()
const act = useActivityStore()

const KINDS = [
  { id: 'board', icon: Presentation },
  { id: 'quiz', icon: ListChecks },
  { id: 'contest', icon: Trophy },
  { id: 'poll', icon: BarChart3 },
  { id: 'pulse', icon: Gauge },
  { id: 'timer', icon: Timer },
]

const chosen = ref('')                 // '' — сетка категорий, иначе экран параметров
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

async function loadQuizzes() {
  try {
    const { data } = await activitiesApi.quizzes({ scope: quizScope.value, q: quizSearch.value })
    quizzes.value = data.quizzes || []
  } catch { quizzes.value = [] }
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
    return { question: question.value.trim(), options: options.value.map((o) => o.trim()).filter(Boolean) }
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
  <div class="fixed inset-0 z-[70] flex items-center justify-center bg-black/50 p-3"
       @click.self="emit('close')">
    <div class="flex max-h-[90vh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl border border-border2 bg-card shadow-xl">
      <div class="flex items-center gap-2 border-b border-border2 px-4 py-3">
        <button v-if="chosen" type="button" @click="chosen = ''"
                class="rounded-lg p-1 text-text3 hover:text-accent">
          <ChevronLeft class="size-5" />
        </button>
        <h2 class="min-w-0 flex-1 truncate text-base font-semibold text-text">
          {{ chosen ? chosenLabel : locale.t('activity.launcher.title', 'Запустить активность') }}
        </h2>
        <button type="button" @click="emit('close')" class="rounded-lg p-1 text-text3 hover:text-accent">
          <X class="size-5" />
        </button>
      </div>

      <div class="min-h-0 flex-1 overflow-y-auto p-4">
        <!-- Сетка категорий. grid-cols-1 обязателен: без явной колонки браузер заводит
             неявную дорожку `auto`, и один длинный неразрывный кусок распирает ВСЮ
             колонку — на телефоне это уезжание за экран (см. §вёрстки CLAUDE.md). -->
        <div v-if="!chosen" class="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <button v-for="k in KINDS" :key="k.id" type="button" @click="choose(k.id)"
                  class="flex min-w-0 flex-col items-start gap-1.5 rounded-xl border border-border2 bg-bg2 p-3 text-left transition-colors hover:border-accent hover:bg-accent-glow">
            <component :is="k.icon" class="size-5 text-accent" />
            <span class="min-w-0 truncate text-sm font-semibold text-text">
              {{ locale.t(`activity.kind.${k.id}`, k.id) }}
            </span>
            <span class="text-[11px] leading-tight text-text3">
              {{ locale.t(`activity.hint.${k.id}`, '') }}
            </span>
          </button>
        </div>

        <div v-else class="flex flex-col gap-3">
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

      <div v-if="chosen" class="flex items-center justify-between gap-2 border-t border-border2 px-4 py-3">
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
              @close="editorFor = null" @saved="loadQuizzes" />
</template>
