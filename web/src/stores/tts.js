/**
 * tts.js — озвучка ответов «Вектора» на сайте и в мобильном приложении.
 *
 * ТРИ режима (циклятся кнопкой в настройках): 'voice' → 'mumble' → 'off'.
 *   • voice  — настоящий синтез речи. Считает СЕРВЕР (/web/vector/tts, Silero), красиво и
 *              одинаково на всех устройствах; проигрываем через Web Audio API.
 *   • mumble — «бубнеж»: имитация речи короткими «блипами» (как голоса персонажей в
 *              Undertale/Deltarune). Считается ПРЯМО В БРАУЗЕРЕ (Web Audio), без сети и без
 *              TTS — работает всегда и мгновенно.
 *   • off    — тишина.
 *
 * ⚠️ Почему Web Audio, а не <audio>. Браузер разрешает воспроизведение только «из жеста»
 * пользователя. Между тапом и звуком у голоса сетевой запрос (~секунды) — для
 * `HTMLAudio.play()` жест «протухает» и звук режется. AudioContext достаточно ОДИН раз
 * «разбудить» в жесте (unlock → resume), дальше он играет буферы в любой момент.
 *
 * Голос недоступен/оффлайн → откат на speechSynthesis. Настройка — устройства
 * (localStorage). По умолчанию: режим 'voice', голос МУЖСКОЙ.
 * Barge-in: новый вопрос/ответ прерывает прежнюю озвучку (см. reqGen).
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { vectorApi } from '@/api/endpoints'
import { MUMBLE_B64, MUMBLE_SR } from '@/config/mumbleData'

const LS_MODE = 'gb.tts.mode'
const LS_VOICE = 'gb.tts.voice'
const LS_ENABLED_OLD = 'gb.tts.enabled'   // старый ключ (миграция вкл/выкл → режим)
// Отдельная громкость БОКОВОЙ ШТОРКИ. Кнопка в шторке дёргала общий режим, и «выключил
// звук в шторке» гасило озвучку и во вкладке «ИИ Помощник» — то есть локальное действие
// молча меняло глобальную настройку. Это разные ситуации: шторка висит поверх журнала,
// где голос мешает, а на вкладке ИИ за ним и приходят.
const LS_DOCK = 'gb.tts.dock'

const MODES = ['voice', 'mumble', 'off']

function readMode() {
  try {
    const m = localStorage.getItem(LS_MODE)
    if (MODES.includes(m)) return m
    // Миграция со старого «вкл/выкл»: off → 'off', иначе 'voice'.
    return localStorage.getItem(LS_ENABLED_OLD) === 'off' ? 'off' : 'voice'
  } catch { return 'voice' }
}
function readVoice() {
  try { return localStorage.getItem(LS_VOICE) === 'female' ? 'female' : 'male' } catch { return 'male' }
}

export const useTtsStore = defineStore('tts', () => {
  const mode = ref(readMode())              // 'voice' | 'mumble' | 'off'
  const voice = ref(readVoice())
  const available = ref(true)               // доступен ли серверный синтез (для режима voice)
  const speaking = ref(false)

  const enabled = computed(() => mode.value !== 'off')   // совместимость с прежним API
  // Озвучка в боковой шторке — СВОЙ выключатель, независимый от общего режима.
  const dockEnabled = ref((() => {
    try { return localStorage.getItem(LS_DOCK) !== 'off' } catch { return true }
  })())
  function setDockEnabled(v) {
    dockEnabled.value = !!v
    try { localStorage.setItem(LS_DOCK, v ? 'on' : 'off') } catch { /* приватный режим */ }
    if (!v) stop()          //выключили при играющем звуке — замолкаем сразу
  }

  let ctx = null           // единственный AudioContext (разбуженный, играет всегда)
  let stopper = null       // как остановить текущую озвучку (barge-in): голос ИЛИ бубнеж
  let mumbleTimer = null
  let reqGen = 0
  let lastNonOff = mode.value === 'off' ? 'voice' : mode.value   // куда вернуться при «включить»

  function _ensureCtx() {
    if (!ctx) {
      const AC = window.AudioContext || window.webkitAudioContext
      if (AC) ctx = new AC()
    }
    return ctx
  }

  /** «Разбудить» звук. ВЫЗЫВАТЬ СИНХРОННО в обработчике жеста (клик/тап/Enter). */
  function unlock() {
    const c = _ensureCtx()
    if (c && c.state === 'suspended') c.resume().catch(() => {})
  }

  function _persistMode() {
    try { localStorage.setItem(LS_MODE, mode.value) } catch { /* приватный режим */ }
  }
  function setMode(m) {
    if (!MODES.includes(m)) m = 'voice'
    mode.value = m
    if (m !== 'off') lastNonOff = m
    _persistMode()
    if (m === 'off') stop()
  }
  /** Циклическое переключение: Голос → Бубнеж → Выкл → Голос. */
  function cycleMode() {
    setMode(MODES[(MODES.indexOf(mode.value) + 1) % MODES.length])
  }
  /** Совместимость: вкл = вернуть последний звучащий режим, выкл = 'off'. */
  function setEnabled(v) { setMode(v ? lastNonOff : 'off') }

  function setVoice(v) {
    voice.value = v === 'female' ? 'female' : 'male'
    try { localStorage.setItem(LS_VOICE, voice.value) } catch { /* приватный режим */ }
  }

  // Человеческая подпись режима — для кнопки в настройках.
  const modeLabel = computed(() => (
    mode.value === 'voice' ? 'Голос включён'
      : mode.value === 'mumble' ? 'Бубнеж' : 'Озвучка выключена'))

  async function refreshStatus() {
    try {
      const { data } = await vectorApi.ttsStatus()
      available.value = !!data.available
    } catch { /* оставляем как есть — решит фактический запрос */ }
  }

  function stop() {
    reqGen++                          // всё, что было в пути, теперь устарело
    if (mumbleTimer) { clearTimeout(mumbleTimer); mumbleTimer = null }
    if (stopper) { try { stopper() } catch { /* уже стоит */ } stopper = null }
    try { window.speechSynthesis?.cancel() } catch { /* нет API */ }
    speaking.value = false
  }

  // Браузерный фолбэк (для режима voice, если сервер недоступен): speechSynthesis.
  function _speakFallback(text, onEnd) {
    const done = () => { speaking.value = false; try { onEnd && onEnd() } catch { /* noop */ } }
    const synth = window.speechSynthesis
    if (!synth || typeof SpeechSynthesisUtterance === 'undefined') { done(); return }
    const u = new SpeechSynthesisUtterance(text)
    u.lang = 'ru-RU'
    const vs = synth.getVoices().filter(v => /ru/i.test(v.lang))
    if (vs.length) {
      const female = /(irina|milena|katya|elena|alena|female|женск)/i
      const male = /(pavel|yuri|dmitri|male|мужск)/i
      const want = voice.value === 'female' ? female : male
      u.voice = vs.find(v => want.test(v.name)) || vs[0]
    }
    u.pitch = voice.value === 'female' ? 1.0 : 1.2
    u.rate = 1.05
    u.onend = done
    u.onerror = done
    speaking.value = true
    synth.speak(u)
  }

  // Паузы на пунктуации — из-за них бубнеж «дышит» как речь, а не тарахтит без остановки.
  const _PAUSE = { ',': 0.20, ';': 0.22, ':': 0.22, '.': 0.34, '!': 0.36, '?': 0.40,
                   '…': 0.42, '—': 0.14, '-': 0.10, '\n': 0.34 }
  const MUMBLE_GAIN = 1.15      // чуть громче оригинала (~15%) — тембр не меняем
  const MUMBLE_STEP = 0.0825    // шаг склейки: фрагмент 27 мс + пауза ~55 мс между повторами
  const MUMBLE_CHAR = 0.058     // «речевое» время на символ (темп проговаривания)

  // Распакованный фрагмент бубнежа (Float32, кэш). Декодируем base64 → int16 → float ×gain.
  let _grain = null
  function _mumbleGrain() {
    if (_grain) return _grain
    const bin = atob(MUMBLE_B64)
    const n = bin.length >> 1
    const f = new Float32Array(n)
    for (let i = 0; i < n; i++) {
      const s = (bin.charCodeAt(i * 2) | (bin.charCodeAt(i * 2 + 1) << 8)) << 16 >> 16  // LE int16 → знак
      f[i] = (s / 32768) * MUMBLE_GAIN
    }
    _grain = f
    return f
  }

  // Фраза → отрезки: {speak, dur}. Речь — непрерывный прогон букв ДО знака, пауза — сам знак.
  function _mumbleSegments(text) {
    const segs = []
    let run = 0
    for (const ch of text) {
      if (ch in _PAUSE) {
        if (run > 0) { segs.push({ speak: true, dur: run }); run = 0 }
        segs.push({ speak: false, dur: _PAUSE[ch] })
      } else if (/[\p{L}\p{N}]/u.test(ch)) run += MUMBLE_CHAR
      else if (ch === ' ') run += MUMBLE_CHAR * 0.6
      else run += MUMBLE_CHAR * 0.5
    }
    if (run > 0) segs.push({ speak: true, dur: run })
    return segs
  }

  /**
   * «Бубнеж»: фрагмент голоса Влада, СКЛЕЕННЫЙ циклично (шаг MUMBLE_STEP), пока идёт
   * «речь», с паузами на знаках препинания. Один звук — без мужского/женского. Собираем весь
   * сигнал в один AudioBuffer и играем одним источником: onended приходит РОВНО в конце звука,
   * поэтому анимация речи маскота синхронна. Считается в браузере, без сети.
   */
  function _speakMumble(text, onStart, onEnd) {
    const c = _ensureCtx()
    const segs = _mumbleSegments(text)
    if (!c || !segs.some(s => s.speak)) { onStart(0); onEnd(); return }
    if (c.state === 'suspended') c.resume().catch(() => {})

    const g = _mumbleGrain()
    const sr = MUMBLE_SR
    const total = Math.floor(segs.reduce((a, s) => a + s.dur, 0) * sr) + g.length + 4
    const data = new Float32Array(total)
    const step = Math.max(1, Math.floor(sr * MUMBLE_STEP))
    let t = 0
    for (const s of segs) {
      if (s.speak) {
        let pos = Math.floor(t * sr)
        const stop = Math.floor((t + s.dur) * sr)
        while (pos < stop) {                       // блипы не наложены (шаг > длины) → без клиппинга
          const lim = Math.min(g.length, total - pos)
          for (let i = 0; i < lim; i++) data[pos + i] += g[i]
          pos += step
        }
      }
      t += s.dur
    }

    const buf = c.createBuffer(1, total, sr)
    buf.copyToChannel(data, 0)
    const my = reqGen
    const src = c.createBufferSource()
    src.buffer = buf
    src.connect(c.destination)
    src.onended = () => { if (my === reqGen) { speaking.value = false; stopper = null; onEnd() } }
    stopper = () => { try { src.onended = null; src.stop() } catch { /* уже стоит */ } }
    speaking.value = true
    //Длительность бубнежа известна ТОЧНО (сами собрали буфер) — ею синхронизируем
    //анимацию «печати» ответа в VectorPage (см. vector.js::_startTyping).
    onStart((total / sr) * 1000)
    src.start(0)
  }

  /**
   * Озвучить текст ответа Вектора по текущему режиму. Прерывает предыдущую озвучку
   * (barge-in). Ничего не делает, если выключено или пусто. Никогда не бросает.
   * opts.onStart/onEnd — синхронизация анимации речи маскота.
   */
  async function speak(text, opts = {}) {
    const t = (text || '').trim()
    if (mode.value === 'off' || !t) return
    stop()                              // barge-in
    const my = reqGen
    // opts.onStart получает длительность озвучки в мс (0/undefined — неизвестна, см.
    // vector.js::_startTyping, где на этот случай есть запасной темп по числу символов).
    const onStart = (durationMs) => { try { opts.onStart && opts.onStart(durationMs) } catch { /* noop */ } }
    const onEnd = () => { try { opts.onEnd && opts.onEnd() } catch { /* noop */ } }

    if (mode.value === 'mumble') { _speakMumble(t, onStart, onEnd); return }

    // Режим voice: серверный синтез, откат на speechSynthesis.
    let fellBack = false
    const fallback = () => {
      if (!fellBack && my === reqGen) { fellBack = true; onStart(0); _speakFallback(t, onEnd) }
    }
    try {
      const c = _ensureCtx()
      if (!c) throw new Error('no-audiocontext')
      const { data } = await vectorApi.tts(t, voice.value)   // data — ArrayBuffer (WAV)
      if (my !== reqGen) return
      if (c.state === 'suspended') await c.resume()
      const buf = await c.decodeAudioData(data.slice(0))
      if (my !== reqGen) return
      const src = c.createBufferSource()
      src.buffer = buf
      src.connect(c.destination)
      src.onended = () => {
        //Дочиталось само (без barge-in) → гасим анимацию речи.
        if (my === reqGen) { speaking.value = false; stopper = null; onEnd() }
      }
      stopper = () => { try { src.onended = null; src.stop() } catch { /* уже стоит */ } }
      speaking.value = true
      available.value = true
      //Реальная длительность буфера — точная синхронизация «печати» текста со звуком.
      onStart(buf.duration * 1000)
      src.start(0)
    } catch (e) {
      if (my !== reqGen) return
      if (e?.response?.status === 503) available.value = false
      fallback()
    }
  }

  return { mode, enabled, voice, available, speaking, modeLabel,
           dockEnabled, setDockEnabled,
           setMode, cycleMode, setEnabled, setVoice, refreshStatus, speak, stop, unlock }
})
