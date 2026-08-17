<script setup>
// ActivityShell — оболочка активности: полный экран либо плавающее окно (PLAN §10).
//
// ⚠️ Живёт в AppShell РЯДОМ с <RouterView>, а не внутри него, и это не стилистика: в том
// же AppShell `mode="out-in"` у <transition> однажды намертво вешал переходы между
// страницами (3.6.6). В анимацию переходов не вмешиваемся вовсе — свёрнутое окно обязано
// пережить переход в «Расписание», а не участвовать в нём.
import { computed, ref, onMounted, onBeforeUnmount } from 'vue'
import { X, Minus, Maximize2 } from '@lucide/vue'
import { useLocaleStore } from '@/stores/locale'
import { useConfirm } from '@/composables/useConfirm'
import { useActivityStore } from '@/stores/activity'
import TimerPanel from './timer/TimerPanel.vue'
import PollPlayer from './poll/PollPlayer.vue'
import PulsePlayer from './pulse/PulsePlayer.vue'
import QuizPlayer from './quiz/QuizPlayer.vue'
import BoardCanvas from './board/BoardCanvas.vue'
import ActivityPortfolio from './ActivityPortfolio.vue'

const locale = useLocaleStore()
const { confirm } = useConfirm()
const act = useActivityStore()
const portfolioOpen = ref(false)

const PLAYERS = {
  timer: TimerPanel, poll: PollPlayer, pulse: PulsePlayer,
  quiz: QuizPlayer, contest: QuizPlayer, board: BoardCanvas,
}
const player = computed(() => PLAYERS[act.kind] || null)
const title = computed(() =>
  act.activity?.title || locale.t(`activity.kind.${act.kind}`, act.kind))

// ── Предпросмотр для свёрнутого окна ────────────────────────────────────────────────
// Берём ТО ЖЕ живое состояние, что рисует полный экран (`act.state`), — второго
// источника не заводим, иначе окно показывало бы одно, а развёрнутая активность другое.

// Последние штрихи, а не все: свёрнутое окно 224 px шириной, рисовать в нём тысячу
// линий незачем, а узнаётся доска по свежему.
const previewStrokes = computed(() => (act.state?.strokes || []).slice(-60))

function strokePoints(s) {
  const p = s?.p || []
  const out = []
  for (let i = 0; i + 1 < p.length; i += 2) out.push(`${p[i] * 100},${p[i + 1] * 56}`)
  return out.join(' ')
}

const nowMs = ref(Date.now())
let miniTick = null
onMounted(() => { miniTick = setInterval(() => { nowMs.value = Date.now() }, 1000) })
onBeforeUnmount(() => { if (miniTick) clearInterval(miniTick) })

const previewBig = computed(() => {
  const st = act.state || {}
  if (act.kind === 'timer') {
    const left = Math.max(0, Math.round((Date.parse(st.ends_at || '') - nowMs.value) / 1000))
    if (!st.ends_at) return '—'
    return `${String(Math.floor(left / 60)).padStart(2, '0')}:${String(left % 60).padStart(2, '0')}`
  }
  if (act.kind === 'poll') return String(Object.keys(st.votes || {}).length)
  if (act.kind === 'pulse') return String((st.answered || []).length)
  if (act.kind === 'contest') {
    const i = Number(st.question_index ?? -1)
    return i >= 0 ? String(i + 1) : '—'
  }
  return String(Object.keys(st.scores || {}).length || 0)
})

const previewSmall = computed(() => {
  if (act.kind === 'timer') return locale.t('activity.mini.left', 'осталось')
  if (act.kind === 'poll') return locale.t('activity.mini.voted', 'проголосовали')
  if (act.kind === 'pulse') return locale.t('activity.mini.answered', 'ответили')
  if (act.kind === 'contest') return locale.t('activity.mini.question', 'вопрос')
  return locale.t('activity.mini.finished', 'прошли тест')
})

async function close() {
  // Ведущий закрывает — завершает для всех; участник просто уходит с экрана. Доску
  // спрашиваем отдельно: «сохранить или удалить» — решение хоста, а не побочный эффект.
  if (act.isHost && act.isRunning) {
    let save = false
    if (act.kind === 'board') {
      // ⚠️ Своя плашка, а не `window.confirm`. Родное окно браузера здесь не годится
      // по трём причинам: оно выпадает из оформления продукта, его нельзя перевести
      // (кнопки подписаны языком системы, а у нас три языка), и в вебвью внутри
      // программы оно выглядит как окно постороннего приложения поверх журнала.
      // `useConfirm` — тот же диалог, что уже подтверждает удаление группы и опасные
      // команды раздела «Сервер».
      save = await confirm({
        title: locale.t('board.saveOnFinishTitle', 'Завершить доску'),
        message: locale.t('board.saveOnFinish', 'Сохранить доску в чат? Иначе она будет удалена.'),
        okText: locale.t('board.saveOnFinishOk', 'Сохранить'),
        cancelText: locale.t('board.saveOnFinishNo', 'Удалить'),
      })
    }
    await act.finish(save)
  }
  act.hide()
}
</script>

<template>
  <!-- Полный экран.
       🔥 v-show, а НЕ v-if: при сворачивании компонент обязан остаться живым. С v-if он
       уничтожался, и вместе с ним — набранные ответы викторины и номер вопроса: человек
       сворачивал окно, разворачивал и обнаруживал тест с самого начала. Живой отзыв
       Влада «свернул — тест начался заново». Цена v-show — доска и плееры висят в
       памяти свёрнутыми, что и требуется: свёрнутое окно показывает их предпросмотр. -->
  <div v-show="act.activity && act.mode === 'full'"
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
      <!-- 🔥 :key ОБЯЗАТЕЛЕН. v-show выше не даёт компоненту умереть при сворачивании
           (иначе терялись набранные ответы), но из-за этого он переживал и СМЕНУ
           активности: запускаешь новую викторину — а на экране результат прошлой,
           «уже всё пройдено». Ключ по id активности разделяет два случая: свернул —
           тот же экземпляр, начал другую — новый. -->
      <component :is="player" v-if="player" :key="act.activity?.id" />
    </div>
    <!-- «Портфолио» — внизу и только у ведущего: студенту чужие результаты не
         полагаются, а сервер их ему и не отдаст (`/results` отдаёт участнику лишь
         его строку). -->
    <div v-if="act.isHost" class="shrink-0 border-t border-border2 px-4 py-2 sm:px-6">
      <button type="button" @click="portfolioOpen = true"
              class="text-xs text-text3 underline-offset-2 hover:text-accent hover:underline">
        {{ locale.t('activity.portfolio.title', 'Портфолио активностей') }}
      </button>
    </div>
  </div>

  <!-- Свёрнутое плавающее окно: следует за человеком по вкладкам.
       Показывает не только название, но и ЖИВОЙ предпросмотр — как свёрнутая
       трансляция в Discord. Без него свёрнутая активность неотличима от закрытой:
       человек не видит, идёт ли она и что там происходит, и разворачивает наугад. -->
  <button v-if="act.activity && act.mode === 'mini'" type="button" @click="act.expand()"
          class="fixed bottom-4 right-4 z-[60] w-56 max-w-[80vw] overflow-hidden rounded-2xl border border-border2 bg-card text-left shadow-lg hover:border-accent">
    <!-- Доска — уменьшенная копия штрихов. Они хранятся долями 0..1, поэтому
         масштабируются в любой viewBox без пересчёта координат. -->
    <div v-if="act.kind === 'board'" class="relative h-24 w-full bg-bg2">
      <svg viewBox="0 0 100 56" preserveAspectRatio="none" class="h-full w-full">
        <polyline v-for="(s, i) in previewStrokes" :key="i"
                  :points="strokePoints(s)" :stroke="s.c || 'currentColor'"
                  :stroke-width="Math.max(0.4, (s.w || 2) / 4)"
                  fill="none" stroke-linecap="round" stroke-linejoin="round" />
      </svg>
      <span v-if="!previewStrokes.length"
            class="absolute inset-0 flex items-center justify-center text-tiny text-text3">
        {{ locale.t('activity.mini.boardEmpty', 'Пока пусто') }}
      </span>
    </div>
    <!-- Остальные категории картинки не имеют — показываем крупно то единственное
         число, ради которого туда и заглядывают. -->
    <div v-else class="flex h-24 w-full flex-col items-center justify-center bg-bg2 px-3">
      <span class="text-2xl font-bold tabular-nums text-text">{{ previewBig }}</span>
      <span class="mt-0.5 text-tiny text-text3">{{ previewSmall }}</span>
    </div>

    <div class="flex items-center gap-2 px-3 py-2">
      <span class="size-2 shrink-0 rounded-full" :class="act.isRunning ? 'bg-accent' : 'bg-text3'" />
      <span class="min-w-0 flex-1 truncate text-sm font-semibold text-text">{{ title }}</span>
      <Maximize2 class="size-4 shrink-0 text-text3" />
    </div>
  </button>

  <ActivityPortfolio v-if="portfolioOpen && act.activity"
                     :conversation-id="act.activity.conversation_id"
                     @close="portfolioOpen = false" />
</template>
