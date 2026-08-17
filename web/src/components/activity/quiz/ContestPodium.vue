<script setup>
// ContestPodium — финальная страница соревнования: пьедестал и полный лидерборд.
//
// Пьедестал первым, а таблица по кнопке: соревнование объявляют вслух, и в этот момент
// на экране должны быть трое, а не список из тридцати строк мелким шрифтом. Остальным
// список нужен — но потом, чтобы найти себя.
import { ref, computed } from 'vue'
import { useLocaleStore } from '@/stores/locale'

const props = defineProps({ results: { type: Array, default: () => [] } })
const locale = useLocaleStore()

const boardOpen = ref(false)

const top = computed(() => props.results.slice(0, 3))
// Порядок на подиуме — 2-1-3, как на настоящем: первое место в середине и выше.
const podium = computed(() => {
  const [a, b, c] = top.value
  return [
    { r: b, place: 2, h: 'h-20' },
    { r: a, place: 1, h: 'h-28' },
    { r: c, place: 3, h: 'h-14' },
  ].filter((x) => x.r)
})
const MEDAL = { 1: '🥇', 2: '🥈', 3: '🥉' }
</script>

<template>
  <div class="flex flex-col items-center gap-6 py-6">
    <h3 class="font-title text-xl font-bold text-text">
      {{ locale.t('contest.over', 'Соревнование завершено') }}
    </h3>

    <!-- Пьедестал -->
    <div v-if="podium.length" class="flex w-full max-w-md items-end justify-center gap-2">
      <div v-for="p in podium" :key="p.place" class="flex min-w-0 flex-1 flex-col items-center gap-1">
        <span class="text-2xl">{{ MEDAL[p.place] }}</span>
        <span class="w-full truncate text-center text-sm font-semibold text-text">{{ p.r.name }}</span>
        <span class="text-xs tabular-nums text-accent">{{ p.r.score }}</span>
        <!-- Подставка: первое место выше остальных — место читается по высоте, а не
             только по цифре, и это видно с последней парты. -->
        <div class="w-full rounded-t-lg border border-b-0 border-border2"
             :class="[p.h, p.place === 1 ? 'bg-accent/25' : 'bg-bg2']" />
      </div>
    </div>
    <p v-else class="py-6 text-sm text-text3">
      {{ locale.t('quiz.noResults', 'Никто не успел ответить') }}
    </p>

    <button type="button" @click="boardOpen = !boardOpen"
            class="rounded-lg border border-border2 px-4 py-2 text-sm font-semibold text-text2 hover:border-accent hover:text-accent">
      {{ locale.t('quiz.leaderboard', 'Лидерборд') }}
    </button>

    <!-- Полная таблица. Первая тройка выделена свечением, остальные обычным списком:
         иначе на экране тридцать одинаковых строк и победителей в них не найти. -->
    <div v-if="boardOpen" class="flex w-full max-w-lg flex-col gap-1.5">
      <div v-for="r in results" :key="r.user_id"
           class="flex min-w-0 items-center gap-2 rounded-lg px-3 py-2"
           :class="r.place <= 3 ? 'bg-accent/10 ring-1 ring-accent/40' : 'bg-bg2'">
        <span class="w-7 shrink-0 text-center text-sm font-bold"
              :class="r.place <= 3 ? 'text-accent' : 'text-text3'">
          {{ MEDAL[r.place] || r.place }}
        </span>
        <span class="min-w-0 flex-1 truncate text-sm text-text">{{ r.name }}</span>
        <!-- «Выполнено» считает ОТВЕТИВШИХ: неверный ответ — тоже работа, а вот
             промолчавшему задание не засчитывается. -->
        <span class="shrink-0 text-xs tabular-nums text-text3">
          {{ locale.t('contest.doneTasks', { n: r.answered_count ?? 0, total: r.total_count }) }}
        </span>
        <span class="shrink-0 text-sm font-semibold tabular-nums text-accent">{{ r.score }}</span>
      </div>
    </div>
  </div>
</template>
