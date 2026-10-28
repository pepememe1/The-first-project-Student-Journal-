<script setup>
// ReminderDialog — «Напомнить о сообщении» (§D19).
//
// Дату из текста разбирает СЕРВЕР и детерминированно, без модели: «завтра в 15:00»
// регулярка понимает надёжнее, а модель ошибается молча — напоминание, съехавшее на день,
// хуже ненайденного, потому что на него уже положились.
//
// Разобранная дата — это ПОДСКАЗКА, а не решение за человека: она подставляется в поле,
// и её видно и можно поправить до нажатия «Напомнить».
import { ref, computed, onMounted } from 'vue'
import { AlarmClock, X } from '@lucide/vue'
import { messengerApi } from '@/api/endpoints'
import { useToast } from '@/composables/useToast'
import { useLocaleStore } from '@/stores/locale'
import { addDays, collegeParts, formatCollege, fromCollegeInput, fromCollegeWall, toCollegeInput } from '@/utils/collegeTime'
import { messageSnippet } from '@/utils/messagePreview'

const props = defineProps({ message: { type: Object, required: true } })
const emit = defineEmits(['close'])

const toast = useToast()
const locale = useLocaleStore()
const BCP47 = { ru: 'ru-RU', en: 'en-US', zh: 'zh-CN' }
// datetime-local: «YYYY-MM-DDTHH:mm» — ЧАСЫ КОЛЛЕДЖА (Улан-Удэ), а не устройства. До
// 15.10.2026 поле показывало время устройства: у родителя в Москве «10:00» из подсказки
// превращалось в 05:00, а набранное им «10:00» срабатывало в 15:00 по Улан-Удэ.
const value = ref('')
const matched = ref('')
const loading = ref(true)
const saving = ref(false)

const preview = computed(() => {
  if (!value.value) return ''
  const d = fromCollegeInput(value.value)
  return Number.isNaN(d.getTime())
    ? ''
    : formatCollege(d, BCP47[locale.active] || 'ru-RU', { day: '2-digit', month: 'long', hour: '2-digit', minute: '2-digit' })
})

onMounted(async () => {
  try {
    const { data } = await messengerApi.reminderSuggest(props.message.id)
    if (data.when) {
      value.value = toCollegeInput(new Date(data.when))
      matched.value = data.matched || ''
    }
  } catch { /* подсказки может и не быть — это нормально */ }
  if (!value.value) {
    // Даты в тексте нет — предлагаем завтра утром: ставить «прямо сейчас» бессмысленно.
    const t = collegeParts(addDays(new Date(), 1))
    value.value = toCollegeInput(fromCollegeWall(t.year, t.month, t.day, 9, 0))
  }
  loading.value = false
})

async function save() {
  const d = fromCollegeInput(value.value)
  if (Number.isNaN(d.getTime())) { toast.error(locale.t('reminder.needDate', 'Укажите дату и время')); return }
  saving.value = true
  try {
    // Отдаём ISO с зоной: на сервере remind_at хранится в UTC, и «наивное» время
    // клиента сдвинуло бы срабатывание на часовой пояс.
    await messengerApi.createReminder(props.message.id, d.toISOString())
    toast.success(locale.t('reminder.willRemind', { when: preview.value }))
    emit('close')
  } catch (e) {
    toast.error(e?.response?.data?.detail || locale.t('reminder.failed', 'Не удалось поставить напоминание'))
  } finally { saving.value = false }
}
</script>

<template>
  <div v-dialog class="fixed inset-0 z-50 grid place-items-center p-4" style="background: var(--gb-overlay)"
       @click.self="emit('close')">
    <div class="w-full max-w-sm rounded-xl border border-border2 bg-card p-4 shadow-card">
      <div class="mb-3 flex items-center gap-2">
        <AlarmClock class="size-4 text-accent" />
        <h3 class="flex-1 font-title text-sm font-bold text-text">{{ locale.t('reminder.title', 'Напомнить о сообщении') }}</h3>
        <button type="button" @click="emit('close')" :aria-label="locale.t('common.close')"
                class="grid size-7 place-items-center rounded-md text-text3 hover:bg-bg2">
          <X class="size-4" />
        </button>
      </div>

      <!-- Подпись, а не тело: у картинки и гифки в теле ссылка (`messageSnippet`). -->
      <p class="mb-3 line-clamp-3 rounded-md border-l-2 border-accent bg-bg2 px-3 py-2 text-xs text-text2">
        {{ messageSnippet(message) }}
      </p>

      <p v-if="loading" class="py-3 text-center text-sm text-text3">{{ locale.t('reminder.searching', 'Ищем дату в тексте…') }}</p>
      <template v-else>
        <label class="block">
          <span class="mb-1 block text-tiny uppercase text-text3">{{ locale.t('reminder.when', 'Когда напомнить') }}</span>
          <input v-model="value" type="datetime-local"
                 class="h-10 w-full rounded-lg border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent" />
          <span class="mt-1 block text-xs text-text3">{{ locale.t('reminder.collegeTime', 'Время — по Улан-Удэ') }}</span>
        </label>
        <p v-if="matched" class="mt-1.5 text-xs text-text3">
          {{ locale.t('reminder.fromText', { matched }) }}
        </p>
      </template>

      <div class="mt-4 flex justify-end gap-2">
        <button type="button" @click="emit('close')"
                class="rounded-lg border border-border2 px-3 py-1.5 text-sm text-text2 hover:bg-bg2">{{ locale.t('common.cancel') }}</button>
        <button type="button" :disabled="saving || loading" @click="save"
                class="rounded-lg bg-accent px-4 py-1.5 text-sm font-semibold text-white hover:bg-accent2 disabled:opacity-50">
          {{ saving ? locale.t('reminder.saving', 'Ставим…') : locale.t('reminder.action', 'Напомнить') }}
        </button>
      </div>
    </div>
  </div>
</template>
