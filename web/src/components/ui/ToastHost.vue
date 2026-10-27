<script setup>
// ToastHost — стопка неблокирующих уведомлений (замена alert()). Монтируется один раз
// в App.vue; список берёт из синглтона useToast. Клик по тосту — закрыть.
import { toasts, dismissToast, pauseToast, resumeToast } from '@/composables/useToast'
import { useLocaleStore } from '@/stores/locale'
import GbIcon from '@/components/ui/GbIcon.vue'

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
  <!-- На телефоне — сверху, под шапкой: снизу тост ложился на поле ввода чата и Вектора
       (живой прогон 27.10.2026). С sm и шире — прежний угол справа внизу. -->
  <div
    class="pointer-events-none fixed inset-x-4 top-[calc(env(safe-area-inset-top)+4rem)] z-[110] flex flex-col gap-2 sm:inset-x-auto sm:top-auto sm:right-4 sm:bottom-[calc(1rem+var(--gb-bottom-chrome))] sm:w-full sm:max-w-xs"
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
      @mouseenter="pauseToast(t.id)"
      @mouseleave="resumeToast(t.id)"
    >
      <span class="flex-1 whitespace-pre-line text-text2">{{ t.message }}</span>
      <button class="-m-1 grid place-items-center p-1 text-text3 hover:text-text pointer-coarse:-m-3 pointer-coarse:size-11"
              :aria-label="locale.t('common.close', 'Закрыть')"
              @click.stop="dismissToast(t.id)"><GbIcon name="close" class="size-4" /></button>
    </div>
  </div>
</template>
