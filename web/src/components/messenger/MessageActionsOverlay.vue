<script setup>
// MessageActionsOverlay — контекстное меню действий над сообщением (как в Telegram).
// Появляется по тапу на сообщение рядом с ним. Набор кнопок зависит от прав
// (своё/чужое, закреплено ли, удалено ли) — см. MESSENGER-PLAN.md §6.8. Эмитит выбранное
// действие наверх (ChatThread выполняет), сам ничего не делает с данными.
import { computed } from 'vue'
import { Reply, Pin, PinOff, Copy, Forward, Trash2, ListChecks, Flag, AlarmClock } from '@lucide/vue'

const props = defineProps({
  message: { type: Object, required: true },
  x: { type: Number, default: 0 },
  y: { type: Number, default: 0 },
})
const emit = defineEmits(['pick', 'react', 'close'])

// §D3: реакции-эмодзи — тот же белый список, что на сервере (MessageReaction.emoji).
const REACTIONS = ['👍', '✅', '❤️', '😂', '👀', '🔥', '💯', '❓', '📌']

const m = computed(() => props.message)
// Позиция: клампим, чтобы меню не уезжало за правый/нижний край.
const style = computed(() => ({
  top: `${Math.min(props.y, (typeof window !== 'undefined' ? window.innerHeight : 800) - 360)}px`,
  left: `${Math.min(props.x, (typeof window !== 'undefined' ? window.innerWidth : 1200) - 240)}px`,
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
  // §D19: «Напомнить» показываем ВСЕГДА, а не только когда в тексте нашлась дата —
  // человек может захотеть напомнить себе о сообщении без всякой даты. Разобранную из
  // текста дату диалог просто подставит в поле как готовый вариант.
  if (!d) list.push({ key: 'remind', label: 'Напомнить', icon: AlarmClock })
  list.push({ key: 'select', label: 'Выделить', icon: ListChecks })
  list.push({ key: 'delete', label: 'Удалить', icon: Trash2, danger: true })
  if (!m.value.mine && !d) list.push({ key: 'report', label: 'Пожаловаться', icon: Flag, danger: true })
  return list
})
</script>

<template>
  <!-- Полупрозрачная подложка: клик мимо — закрыть -->
  <div class="fixed inset-0 z-40" @click="emit('close')" @contextmenu.prevent="emit('close')">
    <div class="fixed z-50 w-56 overflow-hidden rounded-xl border border-border2 bg-card py-1 shadow-card"
         :style="style" @click.stop>
      <!-- §D3: быстрые реакции — строка эмодзи над списком действий (как в Telegram).
           flex-wrap — 9 эмодзи не помещаются в один ряд узкой панели, переносим на вторую. -->
      <div v-if="!m.deleted" class="flex flex-wrap justify-center gap-0.5 border-b border-border px-1.5 py-1.5">
        <button v-for="e in REACTIONS" :key="e" type="button"
                @click="emit('react', e); emit('close')"
                class="grid size-7 place-items-center rounded-md text-base transition-colors hover:bg-bg2">
          {{ e }}
        </button>
      </div>
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
