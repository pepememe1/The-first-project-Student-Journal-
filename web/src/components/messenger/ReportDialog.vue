<script setup>
// ReportDialog — модалка жалобы на сообщение. Причина (radio) + описание. При отправке
// наверх уходит (reason_code, description) → создаётся тикет модерации со снимком текста
// (см. MESSENGER-PLAN.md §6.7). Для причины «Другое» описание обязательно.
import { ref, computed } from 'vue'
import { X } from '@lucide/vue'

const props = defineProps({ message: { type: Object, required: true } })
const emit = defineEmits(['submit', 'close'])

const REASONS = [
  ['spam', 'Спам'],
  ['harassment', 'Оскорбления / травля'],
  ['threats', 'Угрозы / насилие'],
  ['fraud', 'Мошенничество'],
  ['illegal', 'Запрещённый контент'],
  ['flood', 'Флуд'],
  ['other', 'Другое'],
]
const reason = ref('spam')
const description = ref('')
const canSubmit = computed(() => reason.value !== 'other' || description.value.trim().length > 0)

function submit() {
  if (!canSubmit.value) return
  emit('submit', reason.value, description.value.trim())
}
</script>

<template>
  <div class="fixed inset-0 z-50 grid place-items-center p-4" style="background: var(--gb-overlay)"
       @click.self="emit('close')">
    <div class="w-full max-w-md rounded-xl border border-border2 bg-card p-5 shadow-card">
      <div class="mb-3 flex items-center justify-between">
        <h3 class="font-title text-lg font-bold text-text">Пожаловаться на сообщение</h3>
        <button type="button" @click="emit('close')" aria-label="Закрыть"
                class="grid size-8 place-items-center rounded-md text-text3 hover:bg-bg2 hover:text-text">
          <X class="size-5" />
        </button>
      </div>

      <p class="mb-3 truncate rounded-md border border-border bg-bg2 px-3 py-2 text-xs text-text3">
        «{{ message.body || 'сообщение' }}»
      </p>

      <div class="space-y-1.5">
        <label v-for="r in REASONS" :key="r[0]"
               class="flex cursor-pointer items-center gap-2.5 rounded-md px-2 py-1.5 text-sm text-text hover:bg-bg2">
          <input type="radio" name="reason" :value="r[0]" v-model="reason" class="accent-[var(--gb-accent)]" />
          {{ r[1] }}
        </label>
      </div>

      <textarea v-model="description" rows="3"
                :placeholder="reason === 'other' ? 'Опишите проблему (обязательно)…' : 'Опишите подробнее (необязательно)…'"
                class="mt-3 w-full resize-none rounded-lg border border-border2 bg-card2 px-3 py-2 text-sm text-text outline-none focus:border-accent" />

      <div class="mt-4 flex justify-end gap-2">
        <button type="button" @click="emit('close')"
                class="rounded-lg border border-border2 px-4 py-2 text-sm text-text2 hover:bg-bg2">Отмена</button>
        <button type="button" @click="submit" :disabled="!canSubmit"
                class="rounded-lg bg-red px-4 py-2 text-sm font-semibold text-white transition-colors hover:opacity-90 disabled:opacity-50">
          Отправить жалобу
        </button>
      </div>
    </div>
  </div>
</template>
