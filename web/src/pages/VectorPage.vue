<script setup>
// VectorPage — чат с маскотом «Вектор» (порт vector/widget.py). Маскот РЕАГИРУЕТ:
// приветствие при открытии → «думает» во время запроса → эмоция по настроению ответа
// (радость/грусть/предупреждение) → возврат в покой. Все позы — из 30 спрайтов эмоций.
// Цифры считает СЕРВЕР (/web/vector/ask) из реальных данных — маскот не выдумывает.
import { ref, computed, onMounted, nextTick } from 'vue'
import { Send, LayoutGrid } from '@lucide/vue'
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
const showQuick = ref(false)     // попап с быстрыми вопросами (как «Быстрые команды» в десктопе)
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

function ask(text) { showQuick.value = false; input.value = text; send() }
</script>

<template>
  <!-- Мобайл: колонка на весь экран — ОЧЕНЬ КРУПНЫЙ маскот сверху + чат снизу.
       Десктоп (lg): чат слева, а Вектор — СПРАВА отдельной колонкой, огромный, во всю
       высоту (от верхней панели до низа), как ИИ-компаньон в Grok. Порядок в DOM: чат,
       потом маскот; на мобиле order переносит маскот наверх. -->
  <div class="flex h-[calc(100dvh-8rem)] flex-col gap-2 sm:h-[calc(100dvh-9.5rem)] lg:grid lg:h-[calc(100vh-11rem)] lg:grid-cols-[1fr_minmax(360px,38vw)] lg:gap-6">
    <!-- Чат (на мобиле снизу, на десктопе слева) -->
    <div class="order-2 flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg border border-border bg-card shadow-card lg:order-1 lg:h-full">
      <div ref="scroller" class="flex-1 space-y-4 overflow-y-auto p-5">
        <div v-for="(m, i) in messages" :key="i" class="flex" :class="m.role === 'user' ? 'justify-end' : ''">
          <div class="max-w-[80%] rounded-lg px-4 py-2.5 text-sm"
               :class="m.role === 'user' ? 'bg-accent text-white' : 'bg-bg2 text-text'">
            {{ m.text }}
          </div>
        </div>
        <p v-if="state === 'thinking'" class="text-xs text-text2">Вектор думает…</p>
      </div>

      <!-- Строка ввода + кнопка «Быстрые вопросы» (попап со списком, как «Быстрые команды»
           в десктопе): нажал кнопку → выехали вопросы → тапнул → Вектор сразу отвечает. -->
      <div class="relative border-t border-border p-3">
        <transition name="pop">
          <div v-if="showQuick && chips.length"
               class="absolute bottom-full left-3 right-3 mb-2 rounded-lg border border-border2 bg-card p-2 shadow-card">
            <p class="px-1 pb-1 text-xs font-semibold text-text3">Быстрые вопросы</p>
            <div class="flex flex-col gap-1">
              <button v-for="c in chips" :key="c" type="button" @click="ask(c)"
                      class="rounded-md px-3 py-2 text-left text-sm text-text transition-colors hover:bg-accent-glow hover:text-accent">
                {{ c }}
              </button>
            </div>
          </div>
        </transition>

        <form class="flex items-center gap-2" @submit.prevent="send">
          <button type="button" @click="showQuick = !showQuick" aria-label="Быстрые вопросы"
                  class="grid size-11 shrink-0 place-items-center rounded-sm border transition-colors"
                  :class="showQuick ? 'border-accent bg-accent-glow text-accent' : 'border-border2 bg-card2 text-text2 hover:border-accent hover:text-accent'">
            <LayoutGrid class="size-5" />
          </button>
          <input v-model="input" placeholder="Спросите Вектора…" @focus="showQuick = false"
                 class="h-11 min-w-0 flex-1 rounded-sm border border-border2 bg-card2 px-3.5 text-text outline-none focus:border-accent focus:bg-card" />
          <button type="submit" aria-label="Отправить"
                  class="grid size-11 shrink-0 place-items-center rounded-sm bg-accent text-white transition-colors hover:bg-accent2 disabled:opacity-50"
                  :disabled="state === 'thinking' || !input.trim()">
            <Send class="size-5" />
          </button>
        </form>
      </div>
    </div>

    <!-- Вектор: на мобиле — ОЧЕНЬ крупный сверху; на десктопе — справа во всю высоту. -->
    <div class="relative order-1 flex shrink-0 items-end justify-center lg:order-2 lg:h-full lg:items-center">
      <Mascot :sprite="sprite" class="h-[46vh] w-[40vh] max-w-[86vw] sm:h-[50vh] sm:w-[42vh] lg:h-full lg:w-full lg:max-w-none" />
      <span class="absolute bottom-1 inline-flex items-center gap-2 rounded-full bg-accent-glow px-3 py-1 text-sm font-medium text-accent shadow-card lg:bottom-3">
        <span class="size-1.5 rounded-full bg-accent" :class="state === 'thinking' ? 'animate-ping' : ''" />
        {{ label }}
      </span>
    </div>
  </div>
</template>

<style scoped>
.pop-enter-active, .pop-leave-active { transition: opacity 0.16s ease, transform 0.16s ease; }
.pop-enter-from, .pop-leave-to { opacity: 0; transform: translateY(6px); }
</style>
