/**
 * vector.js — ОБЩЕЕ состояние чата с Вектором (одна переписка на приложение).
 *
 * Как в десктопе «одна история для шторки и вкладки»: и боковой док (VectorDock), и
 * вкладка «ИИ Помощник» (VectorPage) работают с ЭТИМ store — сообщения, состояние
 * маскота и эмоции общие. Цифры считает сервер (/web/vector/ask) из реальных данных.
 */
import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import { vectorApi, parentApi } from '@/api/endpoints'
import { chatEmote } from '@/config/mascot'
import { QUICK_COMMANDS } from '@/config/vectorCommands'
import { useAuthStore } from './auth'
import { useTtsStore } from './tts'
import { useLocaleStore } from './locale'

const GREETING_KEY = 'vectorPage.greeting'
const GREETING_FALLBACK = 'Привет! Я Вектор. Спросите про средний балл, задолженности или пропуски — я беру цифры из ваших реальных данных.'

export const useVectorStore = defineStore('vector', () => {
  const auth = useAuthStore()
  const tts = useTtsStore()
  const locale = useLocaleStore()

  const messages = ref([
    { role: 'vector', text: locale.t(GREETING_KEY, GREETING_FALLBACK) },
  ])
  // Приветствие — заглушка ДО первого реального ответа сервера (тот уже приходит на
  // нужном языке через locale_on/prefs.locale). Пока пользователь ничего не спросил,
  // переключение языка обязано перевести и её — иначе «выбрал English, а текст тот же».
  watch(() => locale.active, () => {
    if (messages.value.length === 1 && messages.value[0].role === 'vector') {
      messages.value[0].text = locale.t(GREETING_KEY, GREETING_FALLBACK)
    }
  })
  const input = ref('')
  const state = ref('greeting')      // greeting | idle | thinking | speaking
  const lastMood = ref('neutral')
  const lastIntent = ref('help')
  // Свёрнут ли боковой док (пользователь может спрятать панель). Запоминаем в localStorage,
  // чтобы состояние держалось между страницами и перезапусками.
  // ⚠️ ПО УМОЛЧАНИЮ СВЁРНУТ (с 3.5.6). Раньше умолчанием было «раскрыт», и это было
  // допустимо, пока шторка РАЗДВИГАЛА страницу: контент сужался, но был виден весь.
  // Теперь она НАКЛАДЫВАЕТСЯ поверх (см. AppShell.vue) — при раскрытом умолчании человек
  // на первом же входе видел бы дашборд с закрытой правой третью: карточки статистики и
  // список предметов уходили под панель. Проверено вживую скриншотом, а не в уме.
  // Раскрыл сам — запомним и будем открывать (значение 'shown').
  const collapsed = ref(localStorage.getItem('gb.vectorDock') !== 'shown')
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
    greeting: locale.t('vectorPage.labelGreeting', 'Привет!'),
    thinking: locale.t('vectorPage.labelThinking', 'Думаю…'),
    speaking: locale.t('vectorPage.labelSpeaking', 'Отвечаю'),
    idle: locale.t('vectorPage.labelIdle', 'Готов помочь'),
  }[state.value] || locale.t('vectorPage.labelIdle', 'Готов помочь')))
  const cmds = computed(() => QUICK_COMMANDS[auth.role] || QUICK_COMMANDS.student)

  // Анимация «печати» ответа по символам — потребляется И VectorPage.vue (вкладка «ИИ
  // Помощник»), И VectorDock.vue (боковая шторка): состояние общее на весь мессенджер
  // Вектора. typingReveal ничего в самих messages не меняет, это отдельная надстройка
  // поверх общего списка сообщений — каждый потребитель сам решает, как её показывать.
  // index — какое сообщение сейчас «печатается», text — уже открытая часть, done — конец.
  const typingReveal = ref({ index: -1, text: '', done: true })
  let typingTimer = null
  function _stopTypingTimer() {
    clearInterval(typingTimer)
    typingTimer = null
  }
  // Скорость подстраивается под РЕАЛЬНУЮ длительность озвучки (durationMs из tts.speak —
  // «поспевать за бубнежом»); нет длительности (TTS выключен/фолбэк) — запасной темп по
  // числу символов, чтобы анимация всё равно была, просто не идеально в такт звуку.
  const _FALLBACK_MS_PER_CHAR = 45
  function _startTyping(index, fullText, durationMs) {
    _stopTypingTimer()
    const total = fullText.length
    if (!total) { typingReveal.value = { index, text: '', done: true }; return }
    const dur = Math.max(300, durationMs || total * _FALLBACK_MS_PER_CHAR)
    const startedAt = performance.now()
    typingReveal.value = { index, text: '', done: false }
    typingTimer = setInterval(() => {
      const elapsed = performance.now() - startedAt
      const n = Math.min(total, Math.floor((elapsed / dur) * total))
      typingReveal.value = { index, text: fullText.slice(0, n), done: n >= total }
      if (n >= total) _stopTypingTimer()
    }, 40)
  }
  // Ответ ещё печатался, а уже пришёл новый вопрос — договаривать нечего, показываем
  // прежнее сообщение целиком (иначе оно навсегда осталось бы недопечатанным).
  function _completeTyping() {
    if (typingReveal.value.done) return
    const idx = typingReveal.value.index
    const full = messages.value[idx]?.text ?? typingReveal.value.text
    _stopTypingTimer()
    typingReveal.value = { index: idx, text: full, done: true }
  }
  // Двойной клик по печатающемуся сообщению — сразу показать целиком (см. VectorPage.vue).
  function skipTyping() { _completeTyping() }

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

  // displayText — что показать в СВОЁМ пузыре (может быть переводом кнопки быстрой
  // команды); t — что реально уйдёт в /web/vector/ask. Раздельно потому, что серверный
  // классификатор (vector_nlu.py) понимает только русские ключевые слова (см.
  // config/vectorCommands.js) — нельзя ни переводить запрос (сломает распознавание),
  // ни показывать пользователю русский текст под английской кнопкой (путает).
  async function send(text, displayText) {
    //Разблокируем автоплей ПРЯМО в жесте (клик/Enter): дальше будет сетевой запрос, и
    //без этого браузер зарежет воспроизведение WAV после паузы (см. tts.unlock).
    tts.unlock()
    const t = (text ?? input.value).trim()
    if (!t || state.value === 'thinking') return
    //Новый вопрос — сразу глушим прежнюю озвучку (barge-in), не дожидаясь нового ответа:
    //Вектор не должен договаривать старое, пока пользователь уже спросил другое.
    tts.stop()
    //Прошлый ответ ещё «печатался» — договаривать нечего, раз уже спросили новое.
    _completeTyping()
    messages.value.push({ role: 'user', text: (displayText || '').trim() || t })
    input.value = ''
    state.value = 'thinking'
    tick.value++
    let answer = null
    let msgIndex = -1
    try {
      // У родителя свой эндпоинт: факты собираются в скоупе его ребёнка, а обычный
      // /web/vector/ask роль parent не обслуживает (и не должен — там нет его данных).
      const { data } = auth.role === 'parent'
        ? await parentApi.vectorAsk(t)
        : await vectorApi.ask(t)
      lastMood.value = data.mood || 'neutral'
      lastIntent.value = data.intent || 'help'
      answer = data.text || locale.t('vectorPage.done', 'Готово.')
      msgIndex = messages.value.length
      messages.value.push({ role: 'vector', text: answer })
    } catch (e) {
      const offline = e.response?.status === 404
      messages.value.push({
        role: 'vector',
        text: offline
          ? locale.t('vectorPage.offline', 'Серверный «Вектор» ещё подключается.')
          : locale.t('vectorPage.failed', 'Не удалось получить ответ. Попробуйте снова.'),
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
        const startFrom = (hold, durationMs) => {
          if (!triggered) { triggered = true; startSpeaking(hold); _startTyping(msgIndex, answer, durationMs) }
        }
        clearTimeout(speakSafety)
        tts.speak(answer, {
          onStart: (durationMs) => {
            startFrom(true, durationMs)
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
        //Озвучки нет (выключена/ошибка) — печатаем всё равно, запасным темпом по символам.
        if (answer) _startTyping(msgIndex, answer, null)
      }
    }
  }
  function ask(q, displayText) { send(q, displayText) }

  return { messages, input, state, lastMood, lastIntent, tick, collapsed, setCollapsed,
           sprite, anim, label, cmds, send, ask, greetSettle, greetOnce,
           typingReveal, skipTyping }
})
