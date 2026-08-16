/**
 * alarmSound.js — сигнал будильника по истечении тайм-бокса.
 *
 * Отличается от `pingSound` не громкостью, а НАЗНАЧЕНИЕМ: пинг сообщает («вас позвали»),
 * будильник ТРЕБУЕТ действия и поэтому звучит, пока его не выключат. Синтез, а не mp3, по
 * той же причине, что и у пинга: лишний бинарник поехал бы и в веб, и в OTA-бандл, и в .exe.
 *
 * 🔊 СЛЫШЕН ПРИ СВЁРНУТОМ БРАУЗЕРЕ. Это не случайность, а свойство Web Audio: в фоновой
 * вкладке браузер тормозит таймеры JS, но НЕ глушит уже играющий звук. Поэтому вся
 * последовательность гудков ставится в очередь ОДНИМ вызовом по часам AudioContext, а не
 * повторяется из `setInterval` — с интервалом фоновая вкладка растянула бы сигнал или
 * пропустила его вовсе.
 *
 * ⚠️ Автоплей: браузер разрешает звук только после жеста человека. Контекст будим на
 * первом же клике (`primeAudio` в приложении). Если он всё-таки заблокирован — молчим:
 * окно с истёкшим таймером человек всё равно увидит, и это лучше, чем сыпать ошибками.
 */
let _ctx = null
let _stop = null

function _context() {
  if (_ctx) return _ctx
  const Ctor = window.AudioContext || window.webkitAudioContext
  if (!Ctor) return null
  try { _ctx = new Ctor() } catch { _ctx = null }
  return _ctx
}

/** Разбудить звук первым жестом человека. Зовётся один раз при старте приложения. */
export function primeAlarmAudio() {
  const ctx = _context()
  if (ctx && ctx.state === 'suspended') { try { ctx.resume() } catch { /* noop */ } }
}

/**
 * Запустить сигнал. Играет до `stopAlarm()` либо до конца отведённого времени —
 * бесконечный звук в пустом кабинете хуже пропущенного.
 */
export function playAlarm({ seconds = 60 } = {}) {
  stopAlarm()
  const ctx = _context()
  if (!ctx) return
  try {
    if (ctx.state === 'suspended') ctx.resume()
    const started = ctx.currentTime
    const nodes = []
    // Тройной гудок раз в секунду — узнаваемый рисунок будильника, не похожий на пинг
    // отметки. Ставим ВСЮ последовательность заранее: см. про фоновую вкладку в шапке.
    for (let s = 0; s < seconds; s++) {
      for (const beat of [0, 0.18, 0.36]) {
        const at = started + s + beat
        const osc = ctx.createOscillator()
        const gain = ctx.createGain()
        osc.type = 'square'
        osc.frequency.value = 1046            // «до» третьей октавы — режет фоновый шум
        // Плавные фронты: резкий старт и стоп дают щелчок обрыва волны.
        gain.gain.setValueAtTime(0.0001, at)
        gain.gain.exponentialRampToValueAtTime(0.22, at + 0.01)
        gain.gain.exponentialRampToValueAtTime(0.0001, at + 0.15)
        osc.connect(gain).connect(ctx.destination)
        osc.start(at)
        osc.stop(at + 0.16)
        nodes.push(osc)
      }
    }
    _stop = () => { for (const n of nodes) { try { n.stop() } catch { /* уже остановлен */ } } }
  } catch { /* звук — не критичная часть напоминания */ }
}

/** Выключить сигнал (кнопка «ОК» в окне истёкшего таймера). */
export function stopAlarm() {
  if (_stop) { try { _stop() } catch { /* noop */ } }
  _stop = null
}
