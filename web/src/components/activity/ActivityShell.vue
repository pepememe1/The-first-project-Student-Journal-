<script setup>
// ActivityShell — оболочка активности: полный экран либо плавающее окно (PLAN §10).
//
// ⚠️ Живёт в AppShell РЯДОМ с <RouterView>, а не внутри него, и это не стилистика: в том
// же AppShell `mode="out-in"` у <transition> однажды намертво вешал переходы между
// страницами (3.6.6). В анимацию переходов не вмешиваемся вовсе — свёрнутое окно обязано
// пережить переход в «Расписание», а не участвовать в нём.
import { computed } from 'vue'
import { X, Minus, Maximize2 } from '@lucide/vue'
import { useLocaleStore } from '@/stores/locale'
import { useActivityStore } from '@/stores/activity'
import TimerPanel from './timer/TimerPanel.vue'
import PollPlayer from './poll/PollPlayer.vue'
import PulsePlayer from './pulse/PulsePlayer.vue'
import QuizPlayer from './quiz/QuizPlayer.vue'
import BoardCanvas from './board/BoardCanvas.vue'

const locale = useLocaleStore()
const act = useActivityStore()

const PLAYERS = {
  timer: TimerPanel, poll: PollPlayer, pulse: PulsePlayer,
  quiz: QuizPlayer, contest: QuizPlayer, board: BoardCanvas,
}
const player = computed(() => PLAYERS[act.kind] || null)
const title = computed(() =>
  act.activity?.title || locale.t(`activity.kind.${act.kind}`, act.kind))

async function close() {
  // Ведущий закрывает — завершает для всех; участник просто уходит с экрана. Доску
  // спрашиваем отдельно: «сохранить или удалить» — решение хоста, а не побочный эффект.
  if (act.isHost && act.isRunning) {
    const save = act.kind === 'board'
      ? window.confirm(locale.t('board.saveOnFinish', 'Сохранить доску в чат?'))
      : false
    await act.finish(save)
  }
  act.hide()
}
</script>

<template>
  <!-- Полный экран -->
  <div v-if="act.activity && act.mode === 'full'"
       class="fixed inset-0 z-[60] flex flex-col bg-bg">
    <div class="flex shrink-0 items-center gap-2 border-b border-border2 bg-card px-4 py-3">
      <h2 class="min-w-0 flex-1 truncate text-base font-semibold text-text">{{ title }}</h2>
      <span v-if="!act.isRunning" class="shrink-0 rounded-full bg-bg2 px-2 py-0.5 text-[11px] text-text3">
        {{ locale.t('activity.card.finished', 'завершена') }}
      </span>
      <button type="button" @click="act.minimize()"
              class="rounded-lg p-1.5 text-text3 hover:text-accent"
              :title="locale.t('activity.minimize', 'Свернуть')">
        <Minus class="size-5" />
      </button>
      <button type="button" @click="close"
              class="rounded-lg p-1.5 text-text3 hover:text-red"
              :title="locale.t('activity.close', 'Выйти')">
        <X class="size-5" />
      </button>
    </div>
    <!-- min-h-0 обязателен: без него flex-элемент не сжимается ниже размера содержимого,
         и прокрутка уезжает на всю страницу вместо внутренней области. -->
    <div class="flex min-h-0 flex-1 flex-col overflow-y-auto px-4 sm:px-6">
      <component :is="player" v-if="player" />
    </div>
  </div>

  <!-- Свёрнутое плавающее окно: следует за человеком по вкладкам -->
  <button v-else-if="act.activity && act.mode === 'mini'" type="button" @click="act.expand()"
          class="fixed bottom-4 right-4 z-[60] flex max-w-[80vw] items-center gap-2 rounded-2xl border border-border2 bg-card px-3 py-2 shadow-lg hover:border-accent">
    <span class="size-2 shrink-0 rounded-full" :class="act.isRunning ? 'bg-accent' : 'bg-text3'" />
    <span class="min-w-0 truncate text-sm font-semibold text-text">{{ title }}</span>
    <Maximize2 class="size-4 shrink-0 text-text3" />
  </button>
</template>
