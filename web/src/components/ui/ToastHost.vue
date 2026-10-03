<script setup>
// ToastHost — стопка неблокирующих уведомлений (замена alert()). Монтируется один раз
// в App.vue; список берёт из синглтона useToast. Клик по тосту — закрыть.
import { toasts, dismissToast } from '@/composables/useToast'
import { useLocaleStore } from '@/stores/locale'

const locale = useLocaleStore()

const STYLES = {
  success: 'border-accent/40 text-accent',
  error: 'border-red/50 text-red',
  info: 'border-border2 text-text',
}
</script>

<template>
  <!-- ЖИВАЯ ОБЛАСТЬ существует ВСЕГДА, а не появляется вместе с тостом: программа чтения с
       экрана следит за областью, объявленной заранее, и молчит про элемент, который
       вставили уже с текстом (ACCESSIBILITY.md, пробел №2). Ошибки — `role="alert"`:
       их зачитывают сразу, прерывая текущую фразу; «сохранено» ждёт паузы. -->
  <div
    class="pointer-events-none fixed bottom-4 right-4 z-[110] flex w-full max-w-xs flex-col gap-2"
    aria-live="polite"
    aria-relevant="additions"
  >
    <div
      v-for="t in toasts"
      :key="t.id"
      class="pointer-events-auto flex items-start gap-2 rounded-lg border bg-card px-4 py-3 text-sm shadow-card"
      :class="STYLES[t.type] || STYLES.info"
      :role="t.type === 'error' ? 'alert' : 'status'"
      @click="dismissToast(t.id)"
    >
      <span class="flex-1 whitespace-pre-line text-text2">{{ t.message }}</span>
      <button class="text-text3 hover:text-text" :aria-label="locale.t('common.close', 'Закрыть')"
              @click.stop="dismissToast(t.id)">✕</button>
    </div>
  </div>
</template>
