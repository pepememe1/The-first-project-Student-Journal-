<script setup>
// ToastHost — стопка неблокирующих уведомлений (замена alert()). Монтируется один раз
// в App.vue; список берёт из синглтона useToast. Клик по тосту — закрыть.
import { toasts, dismissToast } from '@/composables/useToast'

const STYLES = {
  success: 'border-accent/40 text-accent',
  error: 'border-red/50 text-red',
  info: 'border-border2 text-text',
}
</script>

<template>
  <div
    class="pointer-events-none fixed bottom-4 right-4 z-[110] flex w-full max-w-xs flex-col gap-2"
  >
    <div
      v-for="t in toasts"
      :key="t.id"
      class="pointer-events-auto flex items-start gap-2 rounded-lg border bg-card px-4 py-3 text-sm shadow-card"
      :class="STYLES[t.type] || STYLES.info"
      role="status"
      @click="dismissToast(t.id)"
    >
      <span class="flex-1 whitespace-pre-line text-text2">{{ t.message }}</span>
      <button class="text-text3 hover:text-text" @click.stop="dismissToast(t.id)">✕</button>
    </div>
  </div>
</template>
