<script setup>
// TimerAlarm — окно «время вышло» с сигналом будильника.
//
// Живёт в оболочке приложения (AppShell), а не в мессенджере: тайм-бокс ставят и идут
// работать — в журнал, в расписание, в статистику. Окно, которое видно только во вкладке
// «Сообщения», не сработало бы ровно в том случае, ради которого таймер и заводят.
//
// Сигнал звучит, пока человек не нажмёт «ОК»: будильник не сообщает, а ТРЕБУЕТ действия.
import { computed, watch, onBeforeUnmount } from 'vue'
import { Timer } from '@lucide/vue'
import { useLocaleStore } from '@/stores/locale'
import { useActivityStore } from '@/stores/activity'
import { playAlarm, stopAlarm } from '@/utils/alarmSound'

const locale = useLocaleStore()
const act = useActivityStore()

const shown = computed(() => !!act.expiredTimer)

// Показываем то время, которое СТАВИЛИ, а не ноль: человек, вернувшийся к экрану через
// десять минут, должен понять, какой именно таймер отзвонил.
const label = computed(() => {
  const s = Math.max(0, Number(act.expiredTimer?.duration_s || 0))
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`
})

watch(shown, (on) => { if (on) playAlarm({ seconds: 60 }); else stopAlarm() })
onBeforeUnmount(stopAlarm)

function ok() {
  stopAlarm()
  act.clearExpiredTimer()
}
</script>

<template>
  <div v-if="shown" class="fixed inset-0 z-[80] flex items-center justify-center bg-black/50 p-4">
    <div class="w-full max-w-xs rounded-2xl border border-border2 bg-card p-6 text-center shadow-xl">
      <Timer class="mx-auto size-7 text-red" />
      <p class="mt-2 text-sm text-text2">{{ locale.t('timer.overTitle', 'Время вышло') }}</p>
      <!-- Мигание — не украшение: окно может всплыть, пока человек смотрит в другое
           место, и статичный текст он заметит позже, чем движение. -->
      <div class="gb-alarm-blink my-3 font-title text-4xl font-bold tabular-nums text-red">
        {{ label }}
      </div>
      <p v-if="act.expiredTimer?.title" class="mb-3 truncate text-xs text-text3">
        {{ act.expiredTimer.title }}
      </p>
      <button type="button" @click="ok"
              class="w-full rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white hover:opacity-90">
        {{ locale.t('common.ok', 'ОК') }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.gb-alarm-blink { animation: gb-alarm-blink 1s steps(2, jump-none) infinite; }
@keyframes gb-alarm-blink { 50% { opacity: .25; } }
/* Мигание — единственный способ привлечь внимание, поэтому при «меньше движения» его не
   выключаем совсем, а делаем мягким: иначе окно теряет смысл. */
@media (prefers-reduced-motion: reduce) {
  .gb-alarm-blink { animation-duration: 2s; }
}
</style>
