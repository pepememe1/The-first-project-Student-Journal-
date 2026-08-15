<script setup>
// PollPlayer — опрос (PLAN-ACTIVITIES §8.2).
//
// 🔑 Распределение видит ТОЛЬКО создатель. Студенту показываем «проголосовало N из M»:
// число ничего не раскрывает и снимает вопрос «дошло ли вообще».
//
// ⚠️ Формулировка про приватность честная — «результаты видит только преподаватель», а
// НЕ «анонимно». Голос не анонимен для сервера осознанно (иначе ни накрутку не поймать,
// ни ошибочное нажатие не исправить), и первая же разобранная жалоба вскрыла бы обман.
import { ref, computed, onMounted, watch } from 'vue'
import { Check } from '@lucide/vue'
import { useLocaleStore } from '@/stores/locale'
import { useActivityStore } from '@/stores/activity'
import { activitiesApi } from '@/api/endpoints'

const locale = useLocaleStore()
const act = useActivityStore()
const results = ref(null)
const busy = ref(false)

const options = computed(() => act.activity?.params?.options || [])
const question = computed(() => act.activity?.params?.question || '')
const myChoice = computed(() => act.state.my_choice)
const voted = computed(() => Number(act.state.voted_count || 0))
const total = computed(() => Number(act.state.participants || 0))

async function vote(i) {
  if (busy.value) return
  busy.value = true
  try {
    const { data } = await activitiesApi.vote(act.activity.id, i)
    act.state = { ...act.state, my_choice: data.my_choice, voted_count: data.voted_count }
    if (act.isHost) await loadResults()
  } catch { /* noop */ } finally { busy.value = false }
}

async function loadResults() {
  if (!act.isHost) return
  try {
    const { data } = await activitiesApi.pollResults(act.activity.id)
    results.value = data
  } catch { results.value = null }
}

onMounted(loadResults)
// Хост видит распределение живьём: каждый новый голос двигает счётчик кадром по сокету.
watch(voted, () => { if (act.isHost) loadResults() })

function percent(i) {
  if (!results.value?.total) return 0
  return Math.round((results.value.counts[i] * 100) / results.value.total)
}
</script>

<template>
  <div class="flex flex-col gap-4 py-4">
    <h3 class="text-lg font-semibold text-text">{{ question }}</h3>

    <div class="flex flex-col gap-2">
      <button v-for="(o, i) in options" :key="i" type="button"
              :disabled="!act.isRunning || busy" @click="vote(i)"
              class="relative flex min-w-0 items-center gap-2 overflow-hidden rounded-xl border px-3 py-2.5 text-left text-sm transition-colors disabled:cursor-default"
              :class="myChoice === i ? 'border-accent bg-accent-glow' : 'border-border2 bg-bg2 hover:border-accent'">
        <!-- Полоса доли — только у создателя: студенту распределение не показываем. -->
        <span v-if="act.isHost && results" class="absolute inset-y-0 left-0 bg-accent/15"
              :style="{ width: percent(i) + '%' }" aria-hidden="true" />
        <Check v-if="myChoice === i" class="relative size-4 shrink-0 text-accent" />
        <span class="relative min-w-0 flex-1 truncate text-text">{{ o }}</span>
        <span v-if="act.isHost && results" class="relative shrink-0 text-xs font-semibold text-text2">
          {{ results.counts[i] }} · {{ percent(i) }}%
        </span>
      </button>
    </div>

    <p class="text-xs text-text3">
      {{ locale.t('poll.votedOf', { n: voted, total }) }}
      <span v-if="!act.isHost"> · {{ locale.t('poll.privacy', 'Результаты видит только преподаватель') }}</span>
    </p>
  </div>
</template>
