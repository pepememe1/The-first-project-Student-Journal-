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
// ⚠️ Ходим через endpoints.js, а НЕ через голый `api.post('/me/prefs')`.
// Тот файл в своём же докстринге обещает держать ВЕСЬ контракт с сервером, и это
// обещание должно быть правдой: иначе смена адреса правится в пяти местах вместо
// одного, а карта связей репозитория просто не видит такой вызов — для неё эта
// страница с сервером не разговаривает вовсе.
import { meApi } from '@/api/endpoints'

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
    applyFavicon(p.green || '#147C8B', p.green2 || '#0f5d68') // значок вкладки — под тему
  }

  // Фавикон вкладки — гексагон GB в АКЦЕНТНОМ цвете текущей темы. Ставим как data-URI:
  // он меняется вместе с темой (в т.ч. кастомный акцент) и заодно сбрасывает жёсткий
  // кэш фавикона в браузере (старый значок больше не «залипает»).
  function applyFavicon(accent, accent2) {
    // Двухцветный гексагон «GB» — тот же фирменный знак, что BrandLogo (ядро делится по
    // диагонали на accent/accent2), но упрощённый для 16px: без вращения, свечения и
    // тонких колец, которые на вкладке превратились бы в грязь. Тонкая тёмная обводка —
    // чтобы значок читался и на светлой, и на тёмной вкладке. «GB» крупная и жирная.
    const c2 = accent2 || accent
    const svg =
      "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'>" +
      "<defs><linearGradient id='g' x1='0' y1='0' x2='1' y2='1'>" +
      `<stop offset='0.5' stop-color='${accent}'/><stop offset='0.5' stop-color='${c2}'/>` +
      "</linearGradient></defs>" +
      "<path d='M16 0.5 L31 9 L31 23 L16 31.5 L1 23 L1 9 Z' fill='url(#g)' " +
      "stroke='rgba(15,27,34,0.35)' stroke-width='1'/>" +
      "<text x='16' y='22' text-anchor='middle' fill='#fff' " +
      "font-family='Arial,Segoe UI,sans-serif' font-size='17' font-weight='900' letter-spacing='-1'>GB</text></svg>"
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
      // ВАЖНО: тему шлём ОБЪЕКТОМ, как десктоп (`push_my_prefs({"theme": spec})`), а не
      // JSON-строкой — иначе поле prefs.theme несовместимо между вебом и десктопом и тема
      // не «роумится» между устройствами. prefs — JSON-колонка, объект хранится нативно.
      await meApi.setPrefs({ theme: spec.value })
    } catch {
      // офлайн/не залогинен — не страшно, локальная тема уже применена
    }
  }

  /** Подтягивает тему пользователя с сервера при входе (если там сохранена). */
  async function loadFromPrefs() {
    try {
      const { data } = await meApi.getPrefs()
      let t = data?.prefs?.theme
      // Старые записи веба хранились строкой — разбираем; десктоп пишет объект напрямую.
      if (typeof t === 'string') { try { t = JSON.parse(t) } catch { t = null } }
      if (t && typeof t === 'object') set(t, { roam: false })
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
