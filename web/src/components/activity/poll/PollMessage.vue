<script setup>
// PollMessage — опрос ПРЯМО В ЛЕНТЕ, как в Telegram: голосуют кнопками в сообщении,
// ничего не открывая.
//
// Почему не оверлей, как остальные активности: опрос — это вопрос на один клик. Ради
// него открывать полноэкранное окно, терять из виду переписку и потом закрывать окно —
// три действия вместо одного, и до конца доходит меньше людей, чем спросили.
//
// 🔒 Распределение голосов приходит с сервера ТОЛЬКО создателю либо когда автор явно
// включил открытые голоса. Здесь его не вычисляют — если сервер не прислал `tally`,
// показывать нечего, и это не «спрятано в интерфейсе», а не отдано вовсе.
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { BarChart3, Check, Clock } from '@lucide/vue'
import { useLocaleStore } from '@/stores/locale'
import { activitiesApi } from '@/api/endpoints'

const props = defineProps({ activity: { type: Object, required: true } })
const locale = useLocaleStore()

const busy = ref(false)
const mine = ref(props.activity.my_choice ?? null)
const votedCount = ref(Number(props.activity.voted_count || 0))
const tally = ref(props.activity.tally || null)

const options = computed(() => props.activity.options || [])

// Счётчик и распределение приходят снаружи (WS-кадр патчит карточку в сторе) — держим
// локальные значения в согласии с ними, иначе чужой голос был бы виден только после
// перезахода в беседу.
watch(() => props.activity.voted_count, (v) => {
  if (v !== undefined && v !== null) votedCount.value = Number(v)
})
watch(() => props.activity.tally, (v) => { if (v) tally.value = v })
watch(() => props.activity.my_choice, (v) => { if (v !== undefined && mine.value === null) mine.value = v })
const closed = computed(() => props.activity.status !== 'running' || expired.value)

// Срок окончания — как в Telegram. Считает клиент от присланного сервером времени:
// тикать по сокету всем участникам ради подписи «осталось 4 мин» слишком дорого.
const now = ref(Date.now())
let tick = null
onMounted(() => { tick = setInterval(() => { now.value = Date.now() }, 1000) })
onBeforeUnmount(() => { if (tick) clearInterval(tick) })

const endsAt = computed(() => Date.parse(props.activity.ends_at || ''))
const expired = computed(() => Number.isFinite(endsAt.value) && endsAt.value <= now.value)
const leftLabel = computed(() => {
  if (!Number.isFinite(endsAt.value)) return ''
  const s = Math.max(0, Math.round((endsAt.value - now.value) / 1000))
  if (!s) return locale.t('poll.closed', 'опрос завершён')
  if (s < 60) return locale.t('poll.leftSec', { n: s })
  return locale.t('poll.leftMin', { n: Math.ceil(s / 60) })
})

const total = computed(() => (tally.value || []).reduce((a, b) => a + b, 0) || votedCount.value)
function percent(i) {
  if (!tally.value || !total.value) return 0
  return Math.round((tally.value[i] / total.value) * 100)
}

async function vote(i) {
  if (busy.value || closed.value) return
  busy.value = true
  const prev = mine.value
  mine.value = i                                     //оптимистично: клик обязан отзываться сразу
  try {
    const { data } = await activitiesApi.vote(props.activity.id, i)
    votedCount.value = Number(data.voted_count ?? votedCount.value)
    if (data.tally) tally.value = data.tally
  } catch {
    mine.value = prev                                //не прошло — возвращаем как было
  } finally { busy.value = false }
}
</script>

<template>
  <div class="my-1 w-full max-w-md rounded-2xl border border-border2 bg-card p-3">
    <div class="mb-2 flex items-start gap-2">
      <BarChart3 class="mt-0.5 size-4 shrink-0 text-accent" />
      <span class="min-w-0 flex-1 break-words text-sm font-semibold text-text">
        {{ activity.question || activity.title }}
      </span>
    </div>

    <div class="flex flex-col gap-1.5">
      <button v-for="(o, i) in options" :key="i" type="button"
              :disabled="busy || closed" @click="vote(i)"
              class="relative w-full overflow-hidden rounded-lg border px-3 py-2 text-left text-sm transition-colors disabled:cursor-default"
              :class="mine === i ? 'border-accent text-text' : 'border-border2 text-text2 hover:border-accent'">
        <!-- Полоса доли — ПОД текстом, а не вместо него: процент читают, а вариант
             выбирают, и подменять одно другим нельзя. -->
        <span v-if="tally" class="absolute inset-y-0 left-0 bg-accent/15"
              :style="{ width: percent(i) + '%' }" />
        <span class="relative flex items-center gap-2">
          <Check v-if="mine === i" class="size-3.5 shrink-0 text-accent" />
          <span class="min-w-0 flex-1 break-words">{{ o }}</span>
          <span v-if="tally" class="shrink-0 text-xs font-semibold tabular-nums text-text3">
            {{ percent(i) }}%
          </span>
        </span>
      </button>
    </div>

    <div class="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-tiny text-text3">
      <span>{{ locale.t('poll.votedCount', { n: total }) }}</span>
      <span v-if="leftLabel" class="flex items-center gap-1">
        <Clock class="size-3" />{{ leftLabel }}
      </span>
      <!-- Честная подпись: голос виден автору опроса всегда, а классу — только если
           автор включил открытые голоса. Писать «анонимно» было бы неправдой. -->
      <span>{{ activity.public_votes ? locale.t('poll.public', 'видно, кто как проголосовал')
                                     : locale.t('poll.private', 'результаты видит преподаватель') }}</span>
    </div>
  </div>
</template>
