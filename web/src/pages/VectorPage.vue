<script setup>
// VectorPage — чат с маскотом «Вектор» (порт vector/widget.py). Маскот РЕАГИРУЕТ:
// приветствие при открытии → «думает» во время запроса → эмоция по настроению ответа
// (радость/грусть/предупреждение) → возврат в покой. Все позы — из 30 спрайтов эмоций.
// Цифры считает СЕРВЕР (/web/vector/ask) из реальных данных — маскот не выдумывает.
import { ref, computed, onMounted, nextTick } from 'vue'
import { Send } from '@lucide/vue'
import { vectorApi } from '@/api/endpoints'
import Mascot from '@/components/Mascot.vue'
import { chatEmote } from '@/config/mascot'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const messages = ref([
  { role: 'vector', text: 'Привет! Я Вектор. Спросите про средний балл, задолженности или пропуски — я беру цифры из ваших реальных данных.' },
])
const input = ref('')
const state = ref('greeting')    // greeting | idle | thinking | speaking
const lastMood = ref('neutral')
const lastIntent = ref('help')   // намерение из ответа сервера ведёт эмоцию (как emotes.pick)
const scroller = ref(null)
let settleTimer = null

// Быстрые вопросы под роль — как подсказки «Вектора» в десктопе.
const SUGGESTIONS = {
  student: ['Какой мой средний балл?', 'Есть ли задолженности?', 'Сколько пропусков?'],
  teacher: ['Средний по моим группам', 'Кто в зоне риска?'],
  admin: ['Сводка по системе'],
}
const chips = computed(() => SUGGESTIONS[auth.role] || SUGGESTIONS.student)
const sprite = computed(() => chatEmote(state.value, lastMood.value, lastIntent.value))
const label = computed(() => ({
  greeting: 'Привет!', thinking: 'Думаю…', speaking: 'Отвечаю', idle: 'Готов помочь',
}[state.value]))

// Приветствие при открытии — через 2.5с уходит в покой.
onMounted(() => { settleTimer = setTimeout(() => { if (state.value === 'greeting') state.value = 'idle' }, 2500) })

async function scrollDown() {
  await nextTick()
  scroller.value?.scrollTo({ top: scroller.value.scrollHeight, behavior: 'smooth' })
}

function settle() {
  clearTimeout(settleTimer)
  settleTimer = setTimeout(() => { if (state.value === 'speaking') state.value = 'idle' }, 3000)
}

async function send() {
  const text = input.value.trim()
  if (!text || state.value === 'thinking') return
  messages.value.push({ role: 'user', text })
  input.value = ''
  state.value = 'thinking'
  scrollDown()
  try {
    const { data } = await vectorApi.ask(text)
    lastMood.value = data.mood || 'neutral'
    lastIntent.value = data.intent || 'help'
    messages.value.push({ role: 'vector', text: data.text || 'Готово.' })
    state.value = 'speaking'
    settle()
  } catch (e) {
    const offline = e.response?.status === 404
    messages.value.push({
      role: 'vector',
      text: offline ? 'Серверный «Вектор» ещё подключается (эндпоинт /web/vector/ask).'
                    : 'Не удалось получить ответ. Проверьте соединение и попробуйте снова.',
    })
    lastMood.value = 'neutral'
    state.value = 'speaking'
    settle()
  } finally {
    scrollDown()
  }
}

function ask(text) { input.value = text; send() }
</script>

<template>
  <!-- Мобайл: колонка на весь экран — КРУПНЫЙ маскот сверху + чат снизу (как ИИ-компаньон
       в Grok). Десктоп (lg): маскот слева отдельной колонкой, чат справа. -->
  <div class="flex h-[calc(100dvh-8.5rem)] flex-col gap-2 sm:h-[calc(100dvh-10rem)] lg:grid lg:h-auto lg:grid-cols-[300px_1fr] lg:gap-6">
    <!-- Маскот: на телефоне занимает большую часть верха и хорошо виден -->
    <div class="flex shrink-0 flex-col items-center justify-end lg:justify-start lg:pt-2">
      <Mascot :sprite="sprite" class="h-[36vh] w-[30vh] sm:h-[40vh] sm:w-[33vh] lg:h-80 lg:w-64" />
      <span class="-mt-1 inline-flex items-center gap-2 rounded-full bg-accent-glow px-3 py-1 text-sm font-medium text-accent lg:mt-2">
        <span class="size-1.5 rounded-full bg-accent" :class="state === 'thinking' ? 'animate-ping' : ''" />
        {{ label }}
      </span>
    </div>

    <div class="flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg border border-border bg-card shadow-card lg:h-[calc(100vh-12rem)]">
      <div ref="scroller" class="flex-1 space-y-4 overflow-y-auto p-5">
        <div v-for="(m, i) in messages" :key="i" class="flex" :class="m.role === 'user' ? 'justify-end' : ''">
          <div class="max-w-[80%] rounded-lg px-4 py-2.5 text-sm"
               :class="m.role === 'user' ? 'bg-accent text-white' : 'bg-bg2 text-text'">
            {{ m.text }}
          </div>
        </div>
        <p v-if="state === 'thinking'" class="text-xs text-text2">Вектор думает…</p>
      </div>

      <div v-if="chips.length" class="flex flex-wrap gap-2 px-3 pb-1 pt-2">
        <button v-for="c in chips" :key="c" type="button" @click="ask(c)"
                class="rounded-full border border-border2 bg-card2 px-3 py-1 text-xs text-text2 transition-colors hover:border-accent hover:text-accent">
          {{ c }}
        </button>
      </div>

      <form class="flex items-center gap-2 border-t border-border p-3" @submit.prevent="send">
        <input v-model="input" placeholder="Спросите Вектора…"
               class="h-11 flex-1 rounded-sm border border-border2 bg-card2 px-3.5 text-text outline-none focus:border-accent focus:bg-card" />
        <button type="submit" aria-label="Отправить"
                class="grid size-11 shrink-0 place-items-center rounded-sm bg-accent text-white transition-colors hover:bg-accent2 disabled:opacity-50"
                :disabled="state === 'thinking' || !input.trim()">
          <Send class="size-5" />
        </button>
      </form>
    </div>
  </div>
</template>
