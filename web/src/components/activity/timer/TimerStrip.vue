<script setup>
// TimerStrip — идущий тайм-бокс ПОД НАЗВАНИЕМ БЕСЕДЫ, а не внутри окна активности.
//
// Зачем отдельно от TimerPanel: таймер ставят, чтобы на него поглядывали, продолжая
// работать. Пока он жил только в полноэкранном окне, человек либо смотрел на таймер и не
// видел чат, либо работал и не видел таймер. В шапке он виден всегда и никому не мешает.
//
// ⚠️ Отсчёт считает КЛИЕНТ от присланного сервером времени окончания. Слать тик каждую
// секунду всем участникам — самая дорогая реализация самой дешёвой функции.
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { Timer, Pause, Play, Square } from '@lucide/vue'
import { useLocaleStore } from '@/stores/locale'
import { useActivityStore } from '@/stores/activity'
import { activitiesApi } from '@/api/endpoints'

const locale = useLocaleStore()
const act = useActivityStore()

const now = ref(Date.now())
let tick = null
onMounted(() => { tick = setInterval(() => { now.value = Date.now() }, 1000) })
onBeforeUnmount(() => { if (tick) clearInterval(tick) })

// Таймер ищем среди ВСЕХ идущих активностей, а не среди открытой: рядом с ним может
// идти доска или викторина, и полоска обязана быть видна независимо от того, что человек
// открыл на экране. Раньше она держалась на `act.activity` и пропадала при любом другом
// открытии — со стороны это выглядело как «таймер исчез и завершить его нечем».
const mine = computed(() => (act.running || []).find((x) => x.kind === 'timer') || null)
const visible = computed(() => !!mine.value)
const live = computed(() => mine.value?.state?.payload || {})
const paused = computed(() => !!live.value.paused)

const left = computed(() => {
  if (paused.value) return Math.max(0, Number(live.value.left_s || 0))
  const ends = Date.parse(live.value.ends_at || '')
  if (!Number.isFinite(ends)) return 0
  return Math.max(0, Math.round((ends - now.value) / 1000))
})

const label = computed(() => {
  const s = left.value
  const mm = String(Math.floor(s / 60)).padStart(2, '0')
  const ss = String(s % 60).padStart(2, '0')
  return `${mm}:${ss}`
})

// Последняя минута — красным. Цвет здесь несёт смысл, а не украшает: в этот момент
// человек решает, успевает он дописать или уже пора сдавать.
const urgent = computed(() => left.value > 0 && left.value <= 60)

async function control(action) {
  try { await activitiesApi.timer(mine.value.id, action) } catch { /* noop */ }
  await act.refreshRunning(mine.value?.conversation_id)
}
async function finish() {
  //Завершаем ИМЕННО таймер, а не то, что открыто на экране: это разные активности.
  try { await activitiesApi.finish(mine.value.id, false) } catch { /* noop */ }
  await act.refreshRunning(mine.value?.conversation_id)
}
</script>

<template>
  <!-- ОТДЕЛЬНОЕ окошко под полоской с названием, а не строка внутри неё: в шапке оно
       конкурировало с названием беседы за ширину и на телефоне обрезало и то и другое.
       Здесь у таймера своя строка на всю ширину, и он читается с расстояния. -->
  <div v-if="visible"
       class="flex items-center gap-3 border-b border-border2 bg-card px-4 py-2"
       :class="urgent ? 'text-red' : 'text-text2'">
    <Timer class="size-4 shrink-0" />
    <span class="text-lg font-bold tabular-nums">{{ label }}</span>
    <span v-if="paused" class="text-xs">{{ locale.t('timer.paused', 'пауза') }}</span>
    <span class="flex-1" />

    <!-- Кнопки — ТОЛЬКО у ведущего. Студенту здесь нечего нажимать: остановить чужой
         таймер он не вправе, а неактивные кнопки читались бы как поломка. -->
    <template v-if="mine?.is_host">
      <button type="button" @click="control(paused ? 'resume' : 'pause')"
              class="ml-1 grid size-6 shrink-0 place-items-center rounded text-text3 hover:bg-card hover:text-accent"
              :title="paused ? locale.t('timer.resume', 'Продолжить') : locale.t('timer.pause', 'Остановить')">
        <component :is="paused ? Play : Pause" class="size-3.5" />
      </button>
      <button type="button" @click="finish"
              class="grid size-6 shrink-0 place-items-center rounded text-text3 hover:bg-card hover:text-red"
              :title="locale.t('timer.finish', 'Завершить')">
        <Square class="size-3.5" />
      </button>
    </template>
  </div>
</template>
