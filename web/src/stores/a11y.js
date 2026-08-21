/**
 * a11y.js — режим для слабовидящих («версия для слабовидящих», как на порталах вузов).
 *
 * Две независимые настройки:
 *   • fontScale — крупность шрифта (0 обычный / 1 крупнее / 2 максимум) → множитель rem;
 *   • contrast — высокий контраст (приглушённый вторичный текст становится полным,
 *     границы жёстче), включается классом `gb-contrast` на <html>.
 *
 * ⚠️ ЭТО НАСТРОЙКА УСТРОЙСТВА, А НЕ АККАУНТА (как озвучка и микрофон — см. stores/voice.js,
 * stores/tts.js). Слабовидящему нужен крупный шрифт на ЕГО телефоне; на общем ПК колледжа
 * следующий пользователь не должен наследовать чужой масштаб. Поэтому храним только в
 * localStorage и на сервер /me/prefs НЕ роумим.
 *
 * ⚠️ Масштаб применяется к <html> font-size, поэтому меняет rem ВЕЗДЕ (и текст, и rem-отступы
 * Tailwind) — ровно то, что нужно: интерфейс растёт целиком. Фиксированные px (ширина
 * сайдбара) не растут — их текст просто обрезается по truncate, это осознанный размен
 * плотности на читаемость.
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

const LS_KEY = 'gb.a11y'
// Множители rem под три ступени. 1.15 и 1.30 — заметный, но не ломающий раскладку шаг.
const SCALES = [1, 1.15, 1.3]

function loadLocal() {
  try {
    const raw = localStorage.getItem(LS_KEY)
    const v = raw ? JSON.parse(raw) : {}
    const step = Number.isInteger(v.fontScale) ? Math.min(2, Math.max(0, v.fontScale)) : 0
    return { fontScale: step, contrast: !!v.contrast }
  } catch {
    return { fontScale: 0, contrast: false }
  }
}

export const useA11yStore = defineStore('a11y', () => {
  const s = loadLocal()
  const fontScale = ref(s.fontScale)  // 0 | 1 | 2
  const contrast = ref(s.contrast)    // boolean

  // Включён ли режим вообще (для подсветки кнопки-очков).
  const active = computed(() => fontScale.value > 0 || contrast.value)
  const scaleFactor = computed(() => SCALES[fontScale.value] || 1)

  /** Раскладывает текущие настройки в документ. Зовётся из main.js до монтирования. */
  function apply() {
    const root = document.documentElement
    root.style.setProperty('--gb-font-scale', String(scaleFactor.value))
    root.classList.toggle('gb-contrast', contrast.value)
    // Флаг для CSS/тестов и для скрытия декоративного (живой фон и т.п. при желании).
    root.dataset.a11y = active.value ? '1' : ''
  }

  function persist() {
    try {
      localStorage.setItem(LS_KEY, JSON.stringify({ fontScale: fontScale.value, contrast: contrast.value }))
    } catch { /* приватный режим — настройка проживёт до перезагрузки, не критично */ }
  }

  function setFontScale(step) {
    fontScale.value = Math.min(2, Math.max(0, step | 0))
    apply(); persist()
  }
  function cycleFontScale() { setFontScale((fontScale.value + 1) % 3) }
  function setContrast(on) { contrast.value = !!on; apply(); persist() }
  function toggleContrast() { setContrast(!contrast.value) }
  /** Полный сброс к обычному виду — кнопка «Выключить» в меню. */
  function reset() { fontScale.value = 0; contrast.value = false; apply(); persist() }

  return {
    fontScale, contrast, active, scaleFactor,
    apply, setFontScale, cycleFontScale, setContrast, toggleContrast, reset,
  }
})
