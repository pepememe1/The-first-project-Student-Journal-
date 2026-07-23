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
import { useTtsStore } from './tts'

export const useVectorStore = defineStore('vector', () => {
  const auth = useAuthStore()
  const tts = useTtsStore()

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
  let speakSafety = null      // бэкстоп: если событие конца звука не придёт — не «говорим» вечно
  function settle() {
    clearTimeout(settleTimer)
    settleTimer = setTimeout(() => { if (state.value === 'speaking') state.value = 'idle' }, 3000)
  }
  // Приветствие уходит в покой (вызывается один раз при первом монтировании).
  function greetSettle() {
    clearTimeout(settleTimer)
    settleTimer = setTimeout(() => { if (state.value === 'greeting') state.value = 'idle' }, 2500)
  }

  // Автоплей нужно «разбудить» жестом. На ПЕРВЫЙ любой жест — МОЛЧА разблокируем звук
  // (без озвучки), чтобы к первому ответу он уже был готов. Здесь ничего не проговариваем
  // (раньше тут срабатывало приветствие — и оно «выстреливало» на бургер-меню; см. greetOnce).
  if (typeof window !== 'undefined') {
    const primeAudio = () => {
      window.removeEventListener('pointerdown', primeAudio)
      window.removeEventListener('keydown', primeAudio)
      tts.unlock()
    }
    window.addEventListener('pointerdown', primeAudio, { passive: true })
    window.addEventListener('keydown', primeAudio)
  }

  // Приветствие голосом — вызывается ТОЛЬКО при открытии вкладки «ИИ Помощник» (VectorPage),
  // один раз за сессию и только если пользователь ещё ничего не спрашивал.
  let greeted = false
  function greetOnce() {
    if (greeted) return
    greeted = true
    tts.unlock()
    if (tts.enabled && !messages.value.some(m => m.role === 'user')) {
      const g = messages.value.find(m => m.role === 'vector')
      if (g) tts.speak(g.text)
    }
  }

  async function send(text) {
    //Разблокируем автоплей ПРЯМО в жесте (клик/Enter): дальше будет сетевой запрос, и
    //без этого браузер зарежет воспроизведение WAV после паузы (см. tts.unlock).
    tts.unlock()
    const t = (text ?? input.value).trim()
    if (!t || state.value === 'thinking') return
    //Новый вопрос — сразу глушим прежнюю озвучку (barge-in), не дожидаясь нового ответа:
    //Вектор не должен договаривать старое, пока пользователь уже спросил другое.
    tts.stop()
    messages.value.push({ role: 'user', text: t })
    input.value = ''
    state.value = 'thinking'
    tick.value++
    let answer = null
    try {
      const { data } = await vectorApi.ask(t)
      lastMood.value = data.mood || 'neutral'
      lastIntent.value = data.intent || 'help'
      answer = data.text || 'Готово.'
      messages.value.push({ role: 'vector', text: answer })
    } catch (e) {
      const offline = e.response?.status === 404
      messages.value.push({
        role: 'vector',
        text: offline ? 'Серверный «Вектор» ещё подключается.' : 'Не удалось получить ответ. Попробуйте снова.',
      })
      lastMood.value = 'neutral'
    } finally {
      tick.value++
      // Переход к анимации речи. На ПРИВЕТСТВИЕ (hello) Вектор сначала МАШЕТ (greeting),
      // потом «говорит». hold=true — анимация речи ДЕРЖИТСЯ, пока играет звук (её погасит
      // onEnd); hold=false — обычная выдержка ~3с (когда озвучки нет).
      const startSpeaking = (hold) => {
        if (lastIntent.value === 'hello') {
          state.value = 'greeting'
          clearTimeout(settleTimer)
          settleTimer = setTimeout(() => { state.value = 'speaking'; if (!hold) settle() }, 1400)
        } else {
          state.value = 'speaking'
          if (!hold) settle()
        }
      }
      // Есть ответ и озвучка включена → маскот ДЕРЖИТ «думает», пока синтез едет, начинает
      // говорить РОВНО со стартом звука (onStart) и держит анимацию речи, ПОКА звук не
      // кончится (onEnd). Если звук не пришёл (медленный/сбой) — обычная выдержка через таймаут.
      if (answer && tts.enabled) {
        let triggered = false
        const startFrom = (hold) => { if (!triggered) { triggered = true; startSpeaking(hold) } }
        clearTimeout(speakSafety)
        tts.speak(answer, {
          onStart: () => {
            startFrom(true)
            //Бэкстоп на случай, если onEnd не придёт (редкий сбой аудио).
            clearTimeout(speakSafety)
            speakSafety = setTimeout(() => {
              if (state.value === 'speaking' || state.value === 'greeting') state.value = 'idle'
            }, 20000)
          },
          onEnd: () => {
            clearTimeout(speakSafety); clearTimeout(settleTimer)
            if (state.value === 'speaking' || state.value === 'greeting') state.value = 'idle'
          },
        })
        setTimeout(() => startFrom(false), 1800)   // звук не пришёл → обычная выдержка
      } else {
        startSpeaking(false)
      }
    }
  }
  function ask(q) { send(q) }

  return { messages, input, state, lastMood, lastIntent, tick, collapsed, setCollapsed,
           sprite, anim, label, cmds, send, ask, greetSettle, greetOnce }
})
