<script setup>
// PulsePlayer — срез понимания 1–10 (PLAN-ACTIVITIES §8.3).
//
// 🔑 ГЛАВНОЕ. Студенту пишем «преподаватель не увидит, кто это написал», а НЕ «анонимно».
// Автор в базе ЕСТЬ и обязан быть: у отзыва есть кнопка жалобы, и жалоба уходит АДМИНУ —
// без автора она никуда не ведёт. Скрывает автора интерфейс преподавателя, а не база.
// Формулировка «анонимно» была бы обманом, и первая же разобранная жалоба это вскрыла бы.
import { ref, computed, onMounted, watch } from 'vue'
import { Flag } from '@lucide/vue'
import AppButton from '@/components/ui/AppButton.vue'
import { useLocaleStore } from '@/stores/locale'
import { useActivityStore } from '@/stores/activity'
import { activitiesApi } from '@/api/endpoints'

const locale = useLocaleStore()
const act = useActivityStore()

// Готовые причины + «другое» со своим текстом: список из воздуха человек не заполнит,
// а без «другого» он не скажет ровно того, ради чего срез и затевался.
const REASONS = ['tempo', 'terms', 'example', 'noticed', 'other']

const score = ref(0)
const reason = ref('')
const text = ref('')
const sent = ref(false)
const summary = ref(null)
const reporting = ref(0)

const done = computed(() => sent.value || !!act.state.mine_done)
const answered = computed(() => Number(act.state.answered_count || 0))
const participants = computed(() => Number(act.state.participants || 0))

async function submit() {
  if (!score.value) return
  try {
    await activitiesApi.sendFeedback(act.activity.id, score.value, reason.value, text.value.trim())
    sent.value = true
  } catch { /* noop */ }
}

async function loadSummary() {
  if (!act.isHost) return
  try {
    const { data } = await activitiesApi.feedbackSummary(act.activity.id)
    summary.value = data
  } catch { summary.value = null }
}

onMounted(loadSummary)
watch(answered, loadSummary)

async function report(id) {
  reporting.value = id
  try {
    await activitiesApi.reportFeedback(id, 'harassment')
    reporting.value = -1
  } catch { reporting.value = 0 }
}
</script>

<template>
  <div class="flex flex-col gap-4 py-4">
    <!-- Взгляд студента -->
    <template v-if="!act.isHost">
      <div v-if="!done" class="flex flex-col gap-4">
        <h3 class="text-base font-semibold text-text">
          {{ locale.t('pulse.question', 'Насколько понятно?') }}
        </h3>
        <div class="flex flex-wrap gap-1.5">
          <button v-for="n in 10" :key="n" type="button" @click="score = n"
                  class="size-9 shrink-0 rounded-lg border text-sm font-semibold transition-colors"
                  :class="score === n ? 'border-accent bg-accent text-white' : 'border-border2 bg-bg2 text-text2 hover:border-accent'">
            {{ n }}
          </button>
        </div>
        <div class="flex flex-wrap gap-1.5">
          <button v-for="r in REASONS" :key="r" type="button" @click="reason = reason === r ? '' : r"
                  class="rounded-lg border px-2.5 py-1 text-xs"
                  :class="reason === r ? 'border-accent bg-accent-glow text-accent' : 'border-border2 text-text2'">
            {{ locale.t(`pulse.reason.${r}`, r) }}
          </button>
        </div>
        <textarea v-model="text" rows="2" maxlength="500"
                  :placeholder="locale.t('pulse.textPlaceholder', 'Что именно непонятно?')"
                  class="w-full rounded-lg border border-border2 bg-bg2 px-3 py-2 text-sm text-text" />
        <p class="text-xs text-text3">{{ locale.t('pulse.privacy') }}</p>
        <AppButton :disabled="!score" @click="submit">
          {{ locale.t('pulse.send', 'Отправить') }}
        </AppButton>
      </div>
      <p v-else class="py-8 text-center text-sm text-text2">
        {{ locale.t('pulse.thanks', 'Спасибо, ответ отправлен') }}
      </p>
    </template>

    <!-- Взгляд преподавателя: сводка БЕЗ авторов -->
    <template v-else>
      <div class="flex flex-wrap items-baseline gap-3">
        <span class="text-3xl font-bold text-accent">{{ summary?.average ?? 0 }}</span>
        <span class="text-sm text-text3">
          {{ locale.t('pulse.answeredOf', { n: answered, total: participants }) }}
        </span>
      </div>
      <!-- Гистограмма 1–10: полными классами, не шаблонной интерполяцией (Tailwind JIT
           не видит склеенное имя класса при сборке). -->
      <div v-if="summary" class="flex items-end gap-1" style="height: 72px">
        <div v-for="(n, i) in summary.histogram" :key="i"
             class="flex min-w-0 flex-1 flex-col items-center justify-end gap-1">
          <div class="w-full rounded-t bg-accent"
               :style="{ height: (summary.answers ? (n * 100 / summary.answers) : 0) + '%' }" />
          <span class="text-[10px] text-text3">{{ i + 1 }}</span>
        </div>
      </div>
      <div v-if="summary?.items?.length" class="flex flex-col gap-1.5">
        <div v-for="f in summary.items" :key="f.id"
             class="flex min-w-0 items-start gap-2 rounded-lg border border-border2 bg-bg2 px-3 py-2">
          <span class="shrink-0 rounded bg-card px-1.5 py-0.5 text-xs font-semibold text-accent">{{ f.score }}</span>
          <span class="min-w-0 flex-1 break-words text-sm text-text">
            {{ f.text || locale.t(`pulse.reason.${f.reason_code}`, f.reason_code) }}
          </span>
          <!-- Жалоба уходит АДМИНУ: преподаватель автора не видит ни до, ни после. -->
          <button type="button" @click="report(f.id)" :disabled="reporting === -1"
                  class="shrink-0 rounded p-1 text-text3 hover:text-red disabled:opacity-40"
                  :title="locale.t('pulse.report', 'Пожаловаться администратору')">
            <Flag class="size-3.5" />
          </button>
        </div>
      </div>
      <p v-else class="py-6 text-center text-sm text-text3">
        {{ locale.t('pulse.waiting', 'Пока никто не ответил') }}
      </p>
    </template>
  </div>
</template>
