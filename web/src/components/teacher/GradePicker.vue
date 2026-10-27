<script setup>
// GradePicker — выбор оценки в журнале на телефоне: лист снизу экрана (23.10.2026).
//
// Раньше ячейка была обычным `<select>`, и Android открывал его системным белым списком:
// мелкие радиокнопки, чужие цвета, буквы «Н / Б / О» без единого слова о смысле (живой
// прогон на S24, Ярослав: «тупой, некрасивый белый, нам нужно своё меню»). Лист устроен
// как у больших приложений: у нижнего края, под большим пальцем; оценки — крупными
// кнопками в цвет журнала; у отметок посещения подписан смысл; текущая выделена;
// «убрать» отдельно и только там, где есть что убирать.
//
// На ПК остаётся `<select>`: там на нём держится ввод с клавиатуры (utils/gradeKeys.js).
// Сотенная шкала — это 101 вариант: кнопками её не показать, поэтому поле с цифровой
// клавиатурой и проверкой по тому же списку допустимого.
// Окно — `v-dialog`: Esc, фокус и системная «назад» закрывают его (§4.28, §4.49).
import { computed, ref } from 'vue'
import { X } from '@lucide/vue'
import { useLocaleStore } from '@/stores/locale'
import haptics from '@/utils/haptics'
import GbIcon from '@/components/ui/GbIcon.vue'

const props = defineProps({
  options: { type: Array, required: true },       // допустимые значения; '' — «убрать»
  current: { type: String, default: '' },
  title: { type: String, default: '' },
  subtitle: { type: String, default: '' },
  toneOf: { type: Function, default: () => '' },  // цвет значения — тот же, что в ячейке
})
const emit = defineEmits(['pick', 'close'])
const locale = useLocaleStore()

const ATTENDANCE = {
  '✓': ['teacherJournal.legendPresent', 'был на занятии'],
  'Н': ['teacherJournal.legendN', 'неявка — идёт в пропуски'],
  'Б': ['teacherJournal.legendB', 'болезнь — идёт в пропуски'],
  'О': ['teacherJournal.legendO', 'опоздал — в пропуски НЕ идёт'],
}
const marks = computed(() => props.options.filter((o) => o && ATTENDANCE[o]))
const scores = computed(() => props.options.filter((o) => o && !ATTENDANCE[o]))
//Больше дюжины вариантов кнопками не показать (сотенная шкала): тогда поле ввода.
const typed = computed(() => scores.value.length > 12)
const draft = ref(typed.value && scores.value.includes(props.current) ? props.current : '')
const draftOk = computed(() => scores.value.includes(String(draft.value).trim()))
const canClear = computed(() => props.options.includes('') && !!props.current)

function pick(value) {
  haptics.tap()
  emit('pick', value)
}
function submitDraft() {
  if (draftOk.value) pick(String(draft.value).trim())
}
</script>

<template>
  <div v-dialog class="fixed inset-0 z-[70] flex items-end justify-center bg-black/50" @click.self="emit('close')">
    <div role="dialog" aria-modal="true" :aria-label="title"
         class="gb-sheet w-full max-w-md rounded-t-2xl border border-b-0 border-border bg-card shadow-card"
         style="padding-bottom: calc(1rem + var(--gb-safe-bottom))">
      <div class="mx-auto mt-2 h-1 w-10 rounded-full bg-border2" aria-hidden="true" />
      <div class="flex items-start gap-3 px-4 pb-2 pt-3">
        <div class="min-w-0 flex-1">
          <p class="truncate font-title text-base font-bold text-text">{{ title }}</p>
          <p v-if="subtitle" class="truncate text-sm text-text3">{{ subtitle }}</p>
        </div>
        <button type="button" class="grid size-11 shrink-0 place-items-center rounded-full text-text2 hover:bg-bg2"
                :aria-label="locale.t('common.close', 'Закрыть')" @click="emit('close')">
          <X class="size-5" />
        </button>
      </div>

      <div class="flex flex-col gap-3 px-4">
        <div v-if="scores.length && !typed" class="grid gap-2"
             :class="scores.length <= 2 ? 'grid-cols-2' : 'grid-cols-4'">
          <button v-for="v in scores" :key="v" type="button"
                  class="min-h-14 rounded-xl border-2 font-title text-xl font-bold transition-colors"
                  :class="[toneOf(v), v === current ? 'border-accent bg-accent-glow' : 'border-border2 bg-card2']"
                  :aria-pressed="v === current" @click="pick(v)">{{ v }}</button>
        </div>
        <form v-else-if="typed" class="flex gap-2" @submit.prevent="submitDraft">
          <input v-model="draft" inputmode="numeric" maxlength="3" autofocus
                 :aria-label="locale.t('gradePicker.scoreLabel', 'Баллы')"
                 :placeholder="locale.t('gradePicker.scorePlaceholder', 'Баллы, 0–100')"
                 class="h-14 min-w-0 flex-1 rounded-xl border-2 border-border2 bg-card2 px-4 font-title text-xl font-bold text-text outline-none focus:border-accent" />
          <button type="submit" :disabled="!draftOk"
                  class="h-14 shrink-0 rounded-xl bg-accent px-5 font-semibold text-white disabled:opacity-50">
            {{ locale.t('gradePicker.set', 'Поставить') }}
          </button>
        </form>

        <div v-if="marks.length" class="flex flex-col gap-1.5">
          <button v-for="m in marks" :key="m" type="button"
                  class="flex min-h-12 items-center gap-3 rounded-xl border-2 px-3 text-left transition-colors"
                  :class="m === current ? 'border-accent bg-accent-glow' : 'border-border2 bg-card2'"
                  :aria-pressed="m === current" @click="pick(m)">
            <span class="w-6 shrink-0 text-center font-title text-lg" :class="toneOf(m)">{{ m }}</span>
            <span class="text-sm text-text2">{{ locale.t(ATTENDANCE[m][0], ATTENDANCE[m][1]) }}</span>
          </button>
        </div>

        <button v-if="canClear" type="button"
                class="min-h-12 rounded-xl border-2 border-red/30 text-sm font-semibold text-red hover:bg-red/10"
                @click="pick('')"><GbIcon name="clear" class="size-4 shrink-0" /> {{ locale.t('gradePicker.clear', 'Убрать отметку') }}</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* Лист въезжает снизу — оттуда, где его и ждут. Без движения для тех, кто его отключил. */
@media (prefers-reduced-motion: no-preference) {
  .gb-sheet { animation: gb-sheet-in 0.22s cubic-bezier(0.32, 0.72, 0, 1); }
}
@keyframes gb-sheet-in { from { transform: translateY(100%); } to { transform: none; } }
</style>
