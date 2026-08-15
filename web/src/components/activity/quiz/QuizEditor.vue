<script setup>
// QuizEditor — конструктор викторины (PLAN-ACTIVITIES §8.4).
//
// Четыре типа заданий: один ответ / несколько / расставить по порядку / сопоставить.
// Ключ (`is_correct`, `correct_position`, `match_key`) редактируется ЗДЕСЬ и приезжает
// только сюда: `GET /quizzes/{id}` отдаёт его автору, а `/{activity}/questions` — никому.
//
// Чужую викторину править нельзя (сервер отвечает 403) — её копируют себе кнопкой
// «Скопировать»: иначе один преподаватель менял бы набор под ногами у другого, который
// прямо сейчас его ведёт.
import { ref, computed, onMounted } from 'vue'
import { X, Plus, Trash2, Copy } from '@lucide/vue'
import AppButton from '@/components/ui/AppButton.vue'
import { useLocaleStore } from '@/stores/locale'
import { activitiesApi } from '@/api/endpoints'

const props = defineProps({ quizId: { type: String, default: '' },
                            kind: { type: String, default: 'quiz' } })
const emit = defineEmits(['close', 'saved'])
const locale = useLocaleStore()

const TYPES = ['single', 'multi', 'order', 'match']

const title = ref('')
const description = ref('')
const tagsText = ref('')
const timeLimitMin = ref(0)   //минуты: секунды человек не считает
const visibility = ref('private')
const questions = ref([])
const canEdit = ref(true)
const busy = ref(false)
const error = ref('')

onMounted(async () => {
  if (!props.quizId) { addQuestion(); return }
  try {
    const { data } = await activitiesApi.quiz(props.quizId)
    title.value = data.title
    description.value = data.description
    tagsText.value = (data.tags || []).join(', ')
    timeLimitMin.value = Math.round((data.time_limit_s || 0) / 60)
    visibility.value = data.visibility
    canEdit.value = !!data.can_edit
    questions.value = (data.questions || []).map((q) => ({
      type: q.type, text: q.text, points: q.points,
      options: q.options.map((o) => ({
        text: o.text, is_correct: !!o.is_correct,
        match_key: o.match_key || '', correct_position: o.correct_position || 0,
      })),
    }))
  } catch { error.value = locale.t('quiz.loadFailed', 'Не удалось загрузить викторину') }
})

function addQuestion() {
  questions.value.push({ type: 'single', text: '', points: 1,
                         options: [{ text: '', is_correct: false }, { text: '', is_correct: false }] })
}
function removeQuestion(i) { questions.value.splice(i, 1) }
function addOption(q) { if (q.options.length < 12) q.options.push({ text: '', is_correct: false }) }
function removeOption(q, i) { if (q.options.length > 2) q.options.splice(i, 1) }

// В `single` верный вариант ровно один — клик по чужому снимает прежний. Иначе набор с
// двумя «верными» проходил бы валидацию и вёл себя непредсказуемо при проверке.
function markCorrect(q, i) {
  if (q.type === 'single') q.options.forEach((o, j) => { o.is_correct = j === i })
  else q.options[i].is_correct = !q.options[i].is_correct
}

const valid = computed(() => title.value.trim() && questions.value.length
  && questions.value.every((q) => q.text.trim() && q.options.every((o) => o.text.trim())))

async function save() {
  busy.value = true
  error.value = ''
  const body = {
    title: title.value.trim(), description: description.value.trim(),
    tags: tagsText.value.split(',').map((t) => t.trim()).filter(Boolean),
    time_limit_s: Math.max(0, Math.round(Number(timeLimitMin.value) || 0) * 60),
    //Категория набора задаётся при СОЗДАНИИ и потом не меняется: перенос
    //набора между библиотеками означал бы задания, которых там быть не может.
    kind: props.kind,
    visibility: visibility.value,
    questions: questions.value.map((q) => ({
      type: q.type, text: q.text.trim(), points: q.points,
      options: q.options.map((o, i) => ({
        text: o.text.trim(), is_correct: !!o.is_correct, match_key: o.match_key || '',
        //В `order` верное место = позиция варианта в списке конструктора: отдельным полем
        //его пришлось бы держать согласованным вручную, а рассогласование ключа заметно
        //не сразу, а только когда все ответы окажутся неверными.
        correct_position: q.type === 'order' ? i + 1 : 0,
      })),
    })),
  }
  try {
    const { data } = props.quizId
      ? await activitiesApi.updateQuiz(props.quizId, body)
      : await activitiesApi.createQuiz(body)
    emit('saved', data)
    emit('close')
  } catch (e) {
    error.value = e?.response?.data?.detail || locale.t('quiz.saveFailed', 'Не удалось сохранить')
  } finally { busy.value = false }
}

async function copySelf() {
  busy.value = true
  try {
    const { data } = await activitiesApi.copyQuiz(props.quizId)
    emit('saved', data)
    emit('close')
  } catch { error.value = locale.t('quiz.saveFailed', 'Не удалось сохранить') }
  finally { busy.value = false }
}
</script>

<template>
  <div class="fixed inset-0 z-[75] flex items-center justify-center bg-black/50 p-3"
       @click.self="emit('close')">
    <div class="flex max-h-[92vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-border2 bg-card shadow-xl">
      <div class="flex items-center gap-2 border-b border-border2 px-4 py-3">
        <h2 class="min-w-0 flex-1 truncate text-base font-semibold text-text">
          {{ quizId ? locale.t('quiz.edit', 'Правка викторины') : locale.t('quiz.create', 'Новая викторина') }}
        </h2>
        <button type="button" @click="emit('close')" class="rounded-lg p-1 text-text3 hover:text-accent">
          <X class="size-5" />
        </button>
      </div>

      <div class="min-h-0 flex-1 overflow-y-auto p-4">
        <div v-if="!canEdit" class="mb-3 rounded-lg border border-border2 bg-bg2 p-3 text-sm text-text2">
          {{ locale.t('quiz.foreign', 'Это чужая викторина — скопируйте её себе, чтобы править') }}
        </div>

        <div class="flex flex-col gap-3">
          <input v-model="title" type="text" maxlength="120" :disabled="!canEdit"
                 :placeholder="locale.t('quiz.title', 'Название')"
                 class="w-full rounded-lg border border-border2 bg-bg2 px-3 py-2 text-sm font-semibold text-text" />
          <input v-model="tagsText" type="text" :disabled="!canEdit"
                 :placeholder="locale.t('quiz.tags', 'Теги через запятую: математика, дроби')"
                 class="w-full rounded-lg border border-border2 bg-bg2 px-3 py-2 text-sm text-text" />
          <!-- Ограничение времени на весь тест. В МИНУТАХ: секунды преподаватель не
               считает, а поле в секундах провоцирует опечатку на порядок. Ноль —
               без ограничения, и так было всегда: пустое поле ничего не меняет. -->
          <label class="flex items-center gap-2 text-sm text-text2">
            <span class="shrink-0">{{ locale.t('quiz.timeLimit', 'Ограничение времени, мин') }}</span>
            <input v-model.number="timeLimitMin" type="number" min="0" max="360" :disabled="!canEdit"
                   class="w-24 rounded-lg border border-border2 bg-bg2 px-3 py-2 text-sm text-text" />
            <span class="text-tiny text-text3">{{ locale.t('quiz.timeLimitHint', '0 — без ограничения') }}</span>
          </label>
          <select v-model="visibility" :disabled="!canEdit"
                  class="w-full rounded-lg border border-border2 bg-bg2 px-3 py-2 text-sm text-text">
            <option value="private">{{ locale.t('quiz.visibility.private', 'Только я') }}</option>
            <option value="college">{{ locale.t('quiz.visibility.college', 'Преподаватели колледжа') }}</option>
          </select>

          <div v-for="(q, qi) in questions" :key="qi"
               class="flex flex-col gap-2 rounded-xl border border-border2 bg-bg2 p-3">
            <div class="flex flex-wrap items-center gap-2">
              <select v-model="q.type" :disabled="!canEdit"
                      class="shrink-0 rounded-lg border border-border2 bg-card px-2 py-1.5 text-xs text-text">
                <option v-for="t in TYPES" :key="t" :value="t">{{ locale.t(`quiz.type.${t}`, t) }}</option>
              </select>
              <input v-model.number="q.points" type="number" min="1" max="100" :disabled="!canEdit"
                     class="w-16 shrink-0 rounded-lg border border-border2 bg-card px-2 py-1.5 text-xs text-text" />
              <span class="min-w-0 flex-1" />
              <button type="button" @click="removeQuestion(qi)" :disabled="!canEdit"
                      class="shrink-0 rounded p-1 text-text3 hover:text-red">
                <Trash2 class="size-4" />
              </button>
            </div>
            <input v-model="q.text" type="text" maxlength="500" :disabled="!canEdit"
                   :placeholder="locale.t('quiz.questionText', 'Текст вопроса')"
                   class="w-full rounded-lg border border-border2 bg-card px-3 py-2 text-sm text-text" />

            <p v-if="q.type === 'order'" class="text-[11px] text-text3">
              {{ locale.t('quiz.orderHint', 'Верный порядок — сверху вниз, как здесь') }}
            </p>

            <div v-for="(o, oi) in q.options" :key="oi" class="flex min-w-0 items-center gap-2">
              <button v-if="q.type === 'single' || q.type === 'multi'" type="button"
                      @click="markCorrect(q, oi)" :disabled="!canEdit"
                      class="size-5 shrink-0 rounded border text-xs font-bold leading-5"
                      :class="o.is_correct ? 'border-accent bg-accent text-white' : 'border-border2 bg-card text-text3'">
                {{ o.is_correct ? '✓' : '' }}
              </button>
              <span v-else-if="q.type === 'order'"
                    class="size-5 shrink-0 rounded-full bg-accent text-center text-xs font-bold leading-5 text-white">
                {{ oi + 1 }}
              </span>
              <input v-model="o.text" type="text" maxlength="500" :disabled="!canEdit"
                     :placeholder="locale.t('quiz.optionText', 'Вариант')"
                     class="min-w-0 flex-1 rounded-lg border border-border2 bg-card px-3 py-1.5 text-sm text-text" />
              <input v-if="q.type === 'match'" v-model="o.match_key" type="text" :disabled="!canEdit"
                     :placeholder="locale.t('quiz.matchKey', 'Пара')"
                     class="w-28 shrink-0 rounded-lg border border-border2 bg-card px-2 py-1.5 text-sm text-text" />
              <button type="button" @click="removeOption(q, oi)" :disabled="!canEdit || q.options.length <= 2"
                      class="shrink-0 rounded p-1 text-text3 hover:text-red disabled:opacity-40">
                <X class="size-4" />
              </button>
            </div>
            <AppButton variant="ghost" size="sm" :disabled="!canEdit" @click="addOption(q)">
              <Plus class="size-4" /> {{ locale.t('quiz.addOption', 'Вариант') }}
            </AppButton>
          </div>

          <AppButton variant="ghost" :disabled="!canEdit" @click="addQuestion">
            <Plus class="size-4" /> {{ locale.t('quiz.addQuestion', 'Добавить вопрос') }}
          </AppButton>
          <p v-if="error" class="text-sm text-red">{{ error }}</p>
        </div>
      </div>

      <div class="flex items-center justify-end gap-2 border-t border-border2 px-4 py-3">
        <AppButton v-if="quizId && !canEdit" variant="ghost" size="sm" :disabled="busy" @click="copySelf">
          <Copy class="size-4" /> {{ locale.t('quiz.copy', 'Скопировать себе') }}
        </AppButton>
        <AppButton variant="ghost" size="sm" @click="emit('close')">
          {{ locale.t('common.cancel', 'Отмена') }}
        </AppButton>
        <AppButton v-if="canEdit" size="sm" :disabled="!valid || busy" @click="save">
          {{ locale.t('common.save', 'Сохранить') }}
        </AppButton>
      </div>
    </div>
  </div>
</template>
