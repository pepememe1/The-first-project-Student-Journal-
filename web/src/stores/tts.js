/**
 * tts.js — озвучка ответов «Вектора» на сайте и в мобильном приложении.
 *
 * Звук считает СЕРВЕР (/web/vector/tts, Silero) — красиво, одинаково на всех устройствах,
 * телефон не греется. Проигрываем через Web Audio API.
 *
 * ⚠️ Почему Web Audio, а не <audio>. Браузер разрешает воспроизведение только «из жеста»
 * пользователя. Между тапом и звуком у нас сетевой запрос (~секунды) — для `HTMLAudio.play()`
 * жест к тому моменту «протухает», и звук режется (откат на голос браузера). AudioContext
 * ведёт себя иначе: его достаточно ОДИН раз «разбудить» в жесте (unlock → resume), и дальше
 * он играет буферы в любой момент, уже без проверки жеста. Это и есть надёжный путь.
 *
 * Нет AudioContext / не разбужен / сервер выключен / оффлайн → откат на speechSynthesis.
 * Настройка — устройства (localStorage). По умолчанию: ВКЛЮЧЕНО, голос МУЖСКОЙ.
 * Barge-in: новый вопрос/ответ прерывает прежнюю озвучку (см. reqGen).
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { vectorApi } from '@/api/endpoints'

const LS_ENABLED = 'gb.tts.enabled'
const LS_VOICE = 'gb.tts.voice'

function readEnabled() {
  try { return localStorage.getItem(LS_ENABLED) !== 'off' } catch { return true }
}
function readVoice() {
  try { return localStorage.getItem(LS_VOICE) === 'female' ? 'female' : 'male' } catch { return 'male' }
}

export const useTtsStore = defineStore('tts', () => {
  const enabled = ref(readEnabled())
  const voice = ref(readVoice())
  const available = ref(true)
  const speaking = ref(false)

  let ctx = null           // единственный AudioContext (разбуженный, играет всегда)
  let current = null       // текущий BufferSource (для barge-in — его останавливаем)
  // Поколение запроса: barge-in. Синтез идёт по сети — пока WAV едет, пользователь может
  // задать новый вопрос. Каждый stop()/speak() двигает счётчик; ответ на устаревший
  // запрос (my !== reqGen) отбрасываем, чтобы старая фраза не «догнала» новую.
  let reqGen = 0

  function _ensureCtx() {
    if (!ctx) {
      const AC = window.AudioContext || window.webkitAudioContext
      if (AC) ctx = new AC()
    }
    return ctx
  }

  /**
   * «Разбудить» звук. ВЫЗЫВАТЬ СИНХРОННО в обработчике жеста пользователя (клик/тап/Enter):
   * AudioContext стартует suspended, и только жест переводит его в running — после чего он
   * играет в любой момент.
   */
  function unlock() {
    const c = _ensureCtx()
    if (c && c.state === 'suspended') c.resume().catch(() => {})
  }

  function setEnabled(v) {
    enabled.value = !!v
    try { localStorage.setItem(LS_ENABLED, v ? 'on' : 'off') } catch { /* приватный режим */ }
    if (!v) stop()
  }
  function setVoice(v) {
    voice.value = v === 'female' ? 'female' : 'male'
    try { localStorage.setItem(LS_VOICE, voice.value) } catch { /* приватный режим */ }
  }

  async function refreshStatus() {
    try {
      const { data } = await vectorApi.ttsStatus()
      available.value = !!data.available
    } catch { /* оставляем как есть — решит фактический запрос */ }
  }

  function stop() {
    reqGen++                          // всё, что было в пути, теперь устарело
    if (current) { try { current.onended = null; current.stop() } catch { /* уже стоит */ } current = null }
    try { window.speechSynthesis?.cancel() } catch { /* нет API */ }
    speaking.value = false
  }

  // Браузерный фолбэк: озвучиваем через speechSynthesis, подбирая RU-голос по полу.
  // onEnd() — когда фраза дочитана (или сорвалась): по нему UI гасит анимацию речи.
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
    u.pitch = voice.value === 'female' ? 1.0 : 1.2    // мужской чуть выше/живее
    u.rate = 1.05
    u.onend = done
    u.onerror = done
    speaking.value = true
    synth.speak(u)
  }

  /**
   * Озвучить текст ответа Вектора. Прерывает предыдущую озвучку (barge-in). Ничего не
   * делает, если выключено или пусто. Никогда не бросает — озвучка не ломает чат.
   *
   * opts.onStart() вызывается РОВНО в момент, когда звук реально начинает играть (или
   * стартует браузерный фолбэк) — по нему UI синхронно включает анимацию речи, чтобы
   * маскот «думал», пока синтез едет, и заговорил вместе со звуком.
   */
  async function speak(text, opts = {}) {
    const t = (text || '').trim()
    if (!enabled.value || !t) return
    stop()                              // barge-in: гасим прежнюю речь, двигаем поколение
    const my = reqGen
    let fellBack = false                // фолбэк ровно один раз
    const onStart = () => { try { opts.onStart && opts.onStart() } catch { /* noop */ } }
    const onEnd = () => { try { opts.onEnd && opts.onEnd() } catch { /* noop */ } }
    const fallback = () => {
      if (!fellBack && my === reqGen) { fellBack = true; onStart(); _speakFallback(t, onEnd) }
    }
    try {
      const c = _ensureCtx()
      if (!c) throw new Error('no-audiocontext')
      const { data } = await vectorApi.tts(t, voice.value)   // data — ArrayBuffer (WAV)
      if (my !== reqGen) return         // пока синтез ехал, задан новый вопрос — молчим
      if (c.state === 'suspended') await c.resume()
      // decodeAudioData «отбирает» ArrayBuffer — отдаём копию, чтобы оригинал не портить.
      const buf = await c.decodeAudioData(data.slice(0))
      if (my !== reqGen) return
      const src = c.createBufferSource()
      src.buffer = buf
      src.connect(c.destination)
      src.onended = () => {
        if (current === src) { speaking.value = false; current = null; onEnd() }
      }
      current = src
      speaking.value = true
      available.value = true
      onStart()                         // звук вот-вот зазвучит → синхронно включаем речь
      src.start(0)
    } catch (e) {
      if (my !== reqGen) return          // устаревший запрос — не откатываемся и не шумим
      if (e?.response?.status === 503) available.value = false
      fallback()
    }
  }

  return { enabled, voice, available, speaking,
           setEnabled, setVoice, refreshStatus, speak, stop, unlock }
})
