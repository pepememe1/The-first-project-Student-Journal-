<script setup>
// MessageActionsOverlay — контекстное меню действий над сообщением (как в Telegram).
// Появляется по тапу на сообщение рядом с ним. Набор кнопок зависит от прав
// (своё/чужое, закреплено ли, удалено ли) — см. MESSENGER-PLAN.md §6.8. Эмитит выбранное
// действие наверх (ChatThread выполняет), сам ничего не делает с данными.
import { computed } from 'vue'
import { Reply, Pin, PinOff, Copy, Forward, Trash2, ListChecks, Flag } from '@lucide/vue'

const props = defineProps({
  message: { type: Object, required: true },
  x: { type: Number, default: 0 },
  y: { type: Number, default: 0 },
})
const emit = defineEmits(['pick', 'close'])

const m = computed(() => props.message)
// Позиция: клампим, чтобы меню не уезжало за правый/нижний край.
const style = computed(() => ({
  top: `${Math.min(props.y, (typeof window !== 'undefined' ? window.innerHeight : 800) - 320)}px`,
  left: `${Math.min(props.x, (typeof window !== 'undefined' ? window.innerWidth : 1200) - 220)}px`,
}))

// Список действий по правам (Фаза 3 — личные чаты).
const items = computed(() => {
  const d = m.value.deleted
  const list = []
  if (!d) list.push({ key: 'reply', label: 'Ответить', icon: Reply })
  if (!d) list.push(m.value.pinned
    ? { key: 'unpin', label: 'Открепить', icon: PinOff }
    : { key: 'pin', label: 'Закрепить', icon: Pin })
  if (!d) list.push({ key: 'copy', label: 'Копировать текст', icon: Copy })
  if (!d) list.push({ key: 'forward', label: 'Переслать', icon: Forward })
  list.push({ key: 'select', label: 'Выделить', icon: ListChecks })
  list.push({ key: 'delete', label: 'Удалить', icon: Trash2, danger: true })
  if (!m.value.mine && !d) list.push({ key: 'report', label: 'Пожаловаться', icon: Flag, danger: true })
  return list
})
</script>

<template>
  <!-- Полупрозрачная подложка: клик мимо — закрыть -->
  <div class="fixed inset-0 z-40" @click="emit('close')" @contextmenu.prevent="emit('close')">
    <div class="fixed z-50 w-52 overflow-hidden rounded-xl border border-border2 bg-card py-1 shadow-card"
         :style="style" @click.stop>
      <button v-for="it in items" :key="it.key" type="button"
              @click="emit('pick', it.key); emit('close')"
              class="flex w-full items-center gap-3 px-3.5 py-2 text-left text-sm transition-colors hover:bg-bg2"
              :class="it.danger ? 'text-red' : 'text-text'">
        <component :is="it.icon" class="size-4 shrink-0" :class="it.danger ? 'text-red' : 'text-text3'" />
        {{ it.label }}
      </button>
    </div>
  </div>
</template>
