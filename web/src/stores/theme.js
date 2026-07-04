/**
 * theme.js — стор оформления (порт логики desktop `ui/theme_service.py` + `theme_ui.py`).
 *
 * Тема хранится как маленький spec: {id, mode?, accent?, schedule?}.
 *   • локально — в localStorage (мгновенный старт, работает офлайн);
 *   • «роумится» между устройствами пользователя через POST /me/prefs (ключ "theme").
 * applyPalette раскладывает buildPalette(spec) в CSS-переменные :root — ровно как
 * apply_palette() пересобирает styles.C в десктопе.
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { buildPalette, normalizeSpec, effectiveMode } from '@/theme/palette'
import { api } from '@/api/client'

const LS_KEY = 'gb.theme'

// Соответствие ключей палитры (styles.C) → CSS-переменным --gb-*.
const VAR_MAP = {
  bg: '--gb-bg', bg2: '--gb-bg2', card: '--gb-card', card2: '--gb-card2',
  border: '--gb-border', border2: '--gb-border2',
  text: '--gb-text', text2: '--gb-text2', text3: '--gb-text3',
  red: '--gb-red', orange: '--gb-orange', yellow: '--gb-yellow',
  shadow: '--gb-shadow', overlay: '--gb-overlay',
  green: '--gb-accent', green2: '--gb-accent2', green_glow: '--gb-accent-glow', blue: '--gb-blue',
}

function loadLocal() {
  try {
    const raw = localStorage.getItem(LS_KEY)
    return raw ? normalizeSpec(JSON.parse(raw)) : { id: 'default' }
  } catch {
    return { id: 'default' }
  }
}

export const useThemeStore = defineStore('theme', () => {
  const spec = ref(loadLocal())

  const palette = computed(() => buildPalette(spec.value))
  const isDark = computed(() => effectiveMode(spec.value) === 'dark')

  /** Раскладывает текущую палитру в CSS-переменные документа. */
  function apply() {
    const p = palette.value
    const root = document.documentElement
    for (const [key, cssVar] of Object.entries(VAR_MAP)) {
      if (p[key] != null) root.style.setProperty(cssVar, p[key])
    }
    root.dataset.mode = p.mode // 'light' | 'dark' — на случай mode-специфичных правил
    const meta = document.querySelector('meta[name="theme-color"]')
    if (meta) meta.setAttribute('content', p.card)
    applyFavicon(p.green || '#147C8B') // значок вкладки — под тему
  }

  // Фавикон вкладки — гексагон GB в АКЦЕНТНОМ цвете текущей темы. Ставим как data-URI:
  // он меняется вместе с темой (в т.ч. кастомный акцент) и заодно сбрасывает жёсткий
  // кэш фавикона в браузере (старый значок больше не «залипает»).
  function applyFavicon(accent) {
    const svg =
      "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'>" +
      `<path d='M16 2 L28.1 9 L28.1 23 L16 30 L3.9 23 L3.9 9 Z' fill='${accent}'/>` +
      "<text x='16' y='20.6' text-anchor='middle' fill='#fff' " +
      "font-family='Segoe UI,Arial,sans-serif' font-size='11.5' font-weight='800'>GB</text></svg>"
    let link = document.querySelector("link[rel~='icon']")
    if (!link) {
      link = document.createElement('link')
      link.rel = 'icon'
      document.head.appendChild(link)
    }
    link.type = 'image/svg+xml'
    link.href = 'data:image/svg+xml,' + encodeURIComponent(svg)
  }

  /** Меняет тему локально и (при онлайне) отправляет в /me/prefs для роуминга. */
  function set(newSpec, { roam = true } = {}) {
    spec.value = normalizeSpec(newSpec)
    localStorage.setItem(LS_KEY, JSON.stringify(spec.value))
    apply()
    if (roam) pushPrefs()
  }

  function setPreset(id) { set({ ...spec.value, id }) }
  function setCustom(accent) { set({ ...spec.value, id: 'custom', accent }) }
  function setMode(mode) { set({ ...spec.value, mode: mode === 'dark' ? 'dark' : undefined }) }
  function toggleMode() { setMode(isDark.value ? 'light' : 'dark') }
  function setSchedule(enabled, start = '18:00', end = '08:00') {
    set({ ...spec.value, schedule: { enabled, start, end } })
  }

  async function pushPrefs() {
    try {
      await api.post('/me/prefs', { theme: JSON.stringify(spec.value) })
    } catch {
      // офлайн/не залогинен — не страшно, локальная тема уже применена
    }
  }

  /** Подтягивает тему пользователя с сервера при входе (если там сохранена). */
  async function loadFromPrefs() {
    try {
      const { data } = await api.get('/me/prefs')
      const t = data?.prefs?.theme
      if (t) set(t, { roam: false })
    } catch {
      // нет доступа/офлайн — остаёмся на локальной теме
    }
  }

  // Тёмная тема по расписанию: раз в минуту пересчитываем режим (без сети).
  let timer = null
  function startScheduleWatcher() {
    if (timer) return
    timer = setInterval(() => {
      if (spec.value.schedule?.enabled) apply()
    }, 60 * 1000)
  }

  return {
    spec, palette, isDark,
    apply, set, setPreset, setCustom, setMode, toggleMode, setSchedule,
    loadFromPrefs, startScheduleWatcher,
  }
})
