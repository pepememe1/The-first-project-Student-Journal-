<script setup>
// VoiceCommandDialog — ПОДТВЕРЖДЕНИЕ голосовой команды преподавателя перед записью.
//
// Порт десктопного `vector/voice_ui.BatchConfirmDialog` — тот же принцип, что и там:
// голос НИКОГДА не пишет в журнал сам. Показываем, что именно расслышано и что будет
// записано, построчно, с возможностью снять галочку. Причина не в перестраховке:
// распознавание ошибается тихо (Whisper слышит «Вектор» как «Виктор»), а цена ошибки —
// оценка не тому студенту. Такую ошибку человек может не заметить месяцами.
//
// Разбор фразы делает СЕРВЕР (`POST /web/vector/voice/command`, общий модуль
// `voice_command.py`), а запись — существующий `/web/teacher/grade`. Здесь только выбор.
import { ref, computed, watch } from 'vue'
import { Mic, AlertTriangle, Check, X } from '@lucide/vue'
import { useLocaleStore } from '@/stores/locale'

const locale = useLocaleStore()
const props = defineProps({
  // Ответ эндпоинта разбора (см. vector_voice_command на сервере).
  result: { type: Object, required: true },
  busy: { type: Boolean, default: false },
})
const emit = defineEmits(['confirm', 'cancel'])

// По умолчанию отмечено ВСЁ: обычный случай — «всё расслышано верно», и заставлять
// отмечать каждую строку значило бы отменять выигрыш голосового ввода.
const picked = ref([])
watch(() => props.result, (r) => {
  picked.value = (r?.items || []).map((_, i) => i)
}, { immediate: true })

const items = computed(() => props.result?.items || [])
const canWrite = computed(() =>
  props.result?.kind === 'grades' && !!props.result?.lesson_id && picked.value.length > 0)

// Подпись действия человеческим языком: «5» само по себе понятно, а «absent_b» — нет.
// Буквы (Н)/(Б)/(О) — это ЛИТЕРАЛЬНЫЕ коды посещаемости (те же, что в журнале
// преподавателя, TeacherJournal.vue::OPTIONS) — они не переводятся, переводится
// только описание рядом с кодом.
const ACTION_LABEL = computed(() => ({
  grade: locale.t('voiceCommandDialog.action.grade', 'оценка'),
  present: locale.t('voiceCommandDialog.action.present', 'присутствовал'),
  absent_n: locale.t('voiceCommandDialog.action.absentN', 'пропуск (Н)'),
  absent_b: locale.t('voiceCommandDialog.action.absentB', 'по болезни (Б)'),
  absent_o: locale.t('voiceCommandDialog.action.absentO', 'опоздал (О)'),
}))

function toggle(i) {
  const at = picked.value.indexOf(i)
  if (at >= 0) picked.value.splice(at, 1)
  else picked.value.push(i)
}
function submit() {
  if (!canWrite.value) return
  emit('confirm', picked.value.map((i) => items.value[i]))
}
</script>

<template>
  <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
       @click.self="emit('cancel')">
    <div class="w-full max-w-lg rounded-lg border border-border bg-card p-5 shadow-card">
      <div class="mb-3 flex items-start gap-2.5">
        <Mic class="mt-0.5 size-5 shrink-0 text-accent" />
        <div class="min-w-0 flex-1">
          <h3 class="font-title text-lg font-bold text-text">{{ locale.t('voiceCommandDialog.title', 'Подтвердите запись') }}</h3>
          <!-- Показываем РАСПОЗНАННУЮ фразу: если Вектор ослышался, это видно сразу и
               человек поймёт, почему список выглядит странно. -->
          <p class="mt-0.5 truncate text-xs text-text3">{{ locale.t('voiceCommandDialog.heard', { text: result.heard }) }}</p>
        </div>
        <button type="button" @click="emit('cancel')" :aria-label="locale.t('common.close', 'Закрыть')"
                class="grid size-7 shrink-0 place-items-center rounded-md text-text3 hover:bg-bg2">
          <X class="size-4" />
        </button>
      </div>

      <!-- Ошибка разбора: писать нечего, объясняем причину и не показываем пустой список. -->
      <div v-if="result.error"
           class="flex items-start gap-2 rounded-md border border-orange/40 bg-orange/5 px-3 py-2.5 text-sm text-text2">
        <AlertTriangle class="mt-0.5 size-4 shrink-0 text-orange" />
        <span>{{ result.error }}</span>
      </div>

      <template v-else>
        <p v-if="result.lesson_label" class="mb-2 text-xs text-text3">
          {{ locale.t('voiceCommandDialog.lesson', 'Занятие:') }} <span class="font-semibold text-text2">{{ result.lesson_label }}</span>
        </p>

        <ul class="max-h-64 space-y-1 overflow-y-auto rounded-md border border-border2 p-2">
          <li v-for="(it, i) in items" :key="i">
            <label class="flex cursor-pointer items-center gap-2.5 rounded-sm px-2 py-1.5 text-sm hover:bg-bg2">
              <input type="checkbox" :checked="picked.includes(i)" @change="toggle(i)"
                     class="accent-accent" />
              <span class="min-w-0 flex-1 truncate text-text">{{ it.who }}</span>
              <span class="shrink-0 text-xs text-text3">{{ ACTION_LABEL[it.action] || it.action }}</span>
              <span class="w-7 shrink-0 text-right font-title font-bold text-accent">{{ it.grade }}</span>
            </label>
          </li>
          <li v-if="!items.length" class="px-2 py-1.5 text-sm text-text3">
            {{ locale.t('voiceCommandDialog.nothingParsed', 'Ничего не разобрано — повторите команду.') }}
          </li>
        </ul>

        <!-- Мягкие замечания разбора (кого не нашли в списке группы). Не блокируют
             запись остальных: потерять всю команду из-за одной неразобранной фамилии
             хуже, чем записать остальных и сказать про пропущенного. -->
        <ul v-if="result.warnings?.length" class="mt-2 space-y-1">
          <li v-for="(w, i) in result.warnings" :key="i" class="flex items-start gap-2 text-xs text-orange">
            <AlertTriangle class="mt-0.5 size-3.5 shrink-0" />{{ w }}
          </li>
        </ul>
      </template>

      <div class="mt-4 flex flex-wrap gap-2">
        <button type="button" :disabled="!canWrite || busy" @click="submit"
                class="flex-1 rounded-sm bg-accent px-4 py-2.5 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50">
          <Check class="mr-1.5 inline size-4" />
          {{ busy ? locale.t('voiceCommandDialog.writing', 'Записываем…') : locale.t('voiceCommandDialog.writeAction', { n: picked.length }) }}
        </button>
        <button type="button" @click="emit('cancel')"
                class="rounded-sm border border-border2 px-4 py-2.5 text-sm text-text2 hover:bg-bg2">
          {{ locale.t('common.cancel', 'Отмена') }}
        </button>
      </div>
    </div>
  </div>
</template>
