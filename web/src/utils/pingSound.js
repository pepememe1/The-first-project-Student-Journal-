/**
 * pingSound.js — короткий звуковой сигнал ГРОМКОЙ отметки (`/@!Фамилия`).
 *
 * Почему синтез, а не mp3-файл: сигнал нужен один и очень короткий, а лишний бинарник —
 * это ещё один ассет в вебе, в OTA-бандле мобилки и в .exe (там всё считаем, см. §11).
 * Web Audio уже используется для озвучки Вектора (stores/tts.js), инфраструктура есть.
 *
 * Автоплей: браузер разрешает звук только после жеста пользователя. Отдельная разблокировка
 * тут не нужна — тот же AudioContext «будит» вход в приложение (см. primeAudio в
 * stores/vector.js). Если контекст всё же заблокирован, молча ничего не играем: пропущенный
 * сигнал не повод сыпать ошибками, отметка всё равно видна значком «@» и письмом в «Системе».
 */
let _ctx = null

function _context() {
  if (_ctx) return _ctx
  const Ctor = window.AudioContext || window.webkitAudioContext
  if (!Ctor) return null
  try { _ctx = new Ctor() } catch { _ctx = null }
  return _ctx
}

/** Две короткие ноты вверх — узнаваемо «вас позвали», но не тревожно. */
export function playMentionPing() {
  const ctx = _context()
  if (!ctx) return
  try {
    if (ctx.state === 'suspended') ctx.resume()
    const now = ctx.currentTime
    // 880 Гц → 1320 Гц: интервал слышен даже на слабых динамиках ноутбука.
    for (const [freq, at] of [[880, 0], [1320, 0.13]]) {
      const osc = ctx.createOscillator()
      const gain = ctx.createGain()
      osc.type = 'sine'
      osc.frequency.value = freq
      // Плавное затухание вместо резкого стопа — иначе слышен щелчок обрыва волны.
      gain.gain.setValueAtTime(0.0001, now + at)
      gain.gain.exponentialRampToValueAtTime(0.18, now + at + 0.01)
      gain.gain.exponentialRampToValueAtTime(0.0001, now + at + 0.12)
      osc.connect(gain).connect(ctx.destination)
      osc.start(now + at)
      osc.stop(now + at + 0.13)
    }
  } catch { /* звук — не критичная часть уведомления */ }
}
