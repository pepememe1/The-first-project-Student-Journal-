/**
 * vector.js — ОБЩЕЕ состояние чата с Вектором (одна переписка на приложение).
 *
 * Как в десктопе «одна история для шторки и вкладки»: и боковой док (VectorDock), и
 * вкладка «ИИ Помощник» (VectorPage) работают с ЭТИМ store — сообщения, состояние
 * маскота и эмоции общие. Цифры считает сервер (/web/vector/ask) из реальных данных.
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { vectorApi } from '@/api/endpoints'
import { chatEmote } from '@/config/mascot'
import { QUICK_COMMANDS } from '@/config/vectorCommands'
import { useAuthStore } from './auth'

export const useVectorStore = defineStore('vector', () => {
  const auth = useAuthStore()

  const messages = ref([
    { role: 'vector', text: 'Привет! Я Вектор. Спросите про средний балл, задолженности или пропуски — я беру цифры из ваших реальных данных.' },
  ])
  const input = ref('')
  const state = ref('greeting')      // greeting | idle | thinking | speaking
  const lastMood = ref('neutral')
  const lastIntent = ref('help')
  // Свёрнут ли боковой док (пользователь может спрятать панель). Запоминаем в localStorage,
  // чтобы состояние держалось между страницами и перезапусками.
  const collapsed = ref(localStorage.getItem('gb.vectorDock') === 'hidden')
  function setCollapsed(v) {
    collapsed.value = !!v
    try { localStorage.setItem('gb.vectorDock', v ? 'hidden' : 'shown') } catch { /* приватный режим */ }
  }
  // Счётчик отправленных — компоненты по нему скроллят свой чат вниз (у каждого свой контейнер).
  const tick = ref(0)

  const sprite = computed(() => chatEmote(state.value, lastMood.value, lastIntent.value))
  // Анимация чата = само состояние (greeting|idle|thinking|speaking) — имена совпадают
  // с файлами /mascot/anim/*.webp. Это «действие» Вектора (гибрид: анимации в чате,
  // а статичные эмоции по успеваемости — на дашборде, см. §5).
  const anim = computed(() => state.value)
  const label = computed(() => ({
    greeting: 'Привет!', thinking: 'Думаю…', speaking: 'Отвечаю', idle: 'Готов помочь',
  }[state.value] || 'Готов помочь'))
  const cmds = computed(() => QUICK_COMMANDS[auth.role] || QUICK_COMMANDS.student)

  let settleTimer = null
  function settle() {
    clearTimeout(settleTimer)
    settleTimer = setTimeout(() => { if (state.value === 'speaking') state.value = 'idle' }, 3000)
  }
  // Приветствие уходит в покой (вызывается один раз при первом монтировании).
  function greetSettle() {
    clearTimeout(settleTimer)
    settleTimer = setTimeout(() => { if (state.value === 'greeting') state.value = 'idle' }, 2500)
  }

  async function send(text) {
    const t = (text ?? input.value).trim()
    if (!t || state.value === 'thinking') return
    messages.value.push({ role: 'user', text: t })
    input.value = ''
    state.value = 'thinking'
    tick.value++
    try {
      const { data } = await vectorApi.ask(t)
      lastMood.value = data.mood || 'neutral'
      lastIntent.value = data.intent || 'help'
      messages.value.push({ role: 'vector', text: data.text || 'Готово.' })
    } catch (e) {
      const offline = e.response?.status === 404
      messages.value.push({
        role: 'vector',
        text: offline ? 'Серверный «Вектор» ещё подключается.' : 'Не удалось получить ответ. Попробуйте снова.',
      })
      lastMood.value = 'neutral'
    } finally {
      tick.value++
      // На ПРИВЕТСТВИЕ (intent hello) Вектор сначала МАШЕТ рукой (greeting), а потом
      // «говорит» ответ. На остальное — сразу переходит к речи.
      if (lastIntent.value === 'hello') {
        state.value = 'greeting'
        clearTimeout(settleTimer)
        settleTimer = setTimeout(() => { state.value = 'speaking'; settle() }, 1400)
      } else {
        state.value = 'speaking'
        settle()
      }
    }
  }
  function ask(q) { send(q) }

  return { messages, input, state, lastMood, lastIntent, tick, collapsed, setCollapsed,
           sprite, anim, label, cmds, send, ask, greetSettle }
})
