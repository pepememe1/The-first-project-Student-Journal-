<script setup>
// TimerPanel — тайм-бокс (PLAN-ACTIVITIES §8.6).
//
// 🔑 Сервер присылает ВРЕМЯ ОКОНЧАНИЯ один раз, отсчёт ведёт клиент. Тикать по сокету
// каждую секунду всем участникам — самая дорогая реализация самой дешёвой функции, а
// расхождение в полсекунды у таймера пары не значит ничего.
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'
import { Pause, Play, Plus } from '@lucide/vue'
import AppButton from '@/components/ui/AppButton.vue'
import { useLocaleStore } from '@/stores/locale'
import { useActivityStore } from '@/stores/activity'
import { activitiesApi } from '@/api/endpoints'

const locale = useLocaleStore()
const act = useActivityStore()
const now = ref(Date.now())
let tick = null
onMounted(() => { tick = setInterval(() => { now.value = Date.now() }, 250) })
onBeforeUnmount(() => { if (tick) clearInterval(tick) })

const paused = computed(() => !!act.state.paused)
const left = computed(() => {
  if (paused.value) return Math.max(0, Number(act.state.left_s || 0))
  const ends = Date.parse(act.state.ends_at || '')
  if (!Number.isFinite(ends)) return 0
  return Math.max(0, Math.round((ends - now.value) / 1000))
})
const done = computed(() => left.value <= 0 && !paused.value)
const label = computed(() => {
  const m = String(Math.floor(left.value / 60)).padStart(2, '0')
  const s = String(left.value % 60).padStart(2, '0')
  return `${m}:${s}`
})

// Причину отказа показываем ЗДЕСЬ, а не в сторе. Раньше в этом catch стоял
// комментарий «показано в сторе» — неправда дважды: вызов идёт мимо стора (напрямую
// через activitiesApi), а `activity.error` рисуется только на экране запуска
// (ActivityLauncher). То есть ведущий жал «Продлить», сервер отвечал «Активность уже
// завершена», и человек видел ту же тишину, что и при прежнем ложном успехе.
const err = ref('')
async function control(action, seconds = 0) {
  err.value = ''
  try {
    await activitiesApi.timer(act.activity.id, action, seconds)
  } catch (e) {
    err.value = e?.response?.data?.detail
      || locale.t('activity.timer.controlFailed', 'Не удалось изменить таймер')
  }
}
</script>

<template>
  <div class="flex flex-col items-center justify-center gap-6 py-8">
    <div class="text-center">
      <div class="font-mono text-6xl font-bold tabular-nums sm:text-7xl"
           :class="done ? 'text-red' : 'text-accent'">{{ label }}</div>
      <p class="mt-2 text-sm text-text3">
        {{ done ? locale.t('activity.timer.done', 'Время вышло')
                : paused ? locale.t('activity.timer.paused', 'На паузе')
                         : locale.t('activity.timer.running', 'Идёт отсчёт') }}
      </p>
    </div>
    <div v-if="act.isHost && act.isRunning" class="flex flex-wrap justify-center gap-2">
      <AppButton v-if="!paused" variant="ghost" size="sm" @click="control('pause')">
        <Pause class="size-4" /> {{ locale.t('activity.timer.pause', 'Пауза') }}
      </AppButton>
      <AppButton v-else variant="ghost" size="sm" @click="control('resume')">
        <Play class="size-4" /> {{ locale.t('activity.timer.resume', 'Продолжить') }}
      </AppButton>
      <AppButton variant="ghost" size="sm" @click="control('extend', 60)">
        <Plus class="size-4" /> {{ locale.t('activity.timer.extend', '+1 минута') }}
      </AppButton>
    </div>
    <p v-if="err" class="text-sm text-red">{{ err }}</p>
  </div>
</template>
