/**
 * palette.js — цветовые палитры GradeBookAI (порт desktop `ui/styles.py` + `ui/themes.py`).
 *
 * Тема состоит из двух независимых осей (как в десктопе):
 *   • РЕЖИМ (mode): 'light' / 'dark' — выбирает нейтральную базу поверхностей.
 *   • АКЦЕНТ (id / accent): фирменная бирюза ВСГУТУ или один из 16 пресетов —
 *     красит интерактив (кнопки, активная навигация, фокус, бейджи). В светлом
 *     режиме акцент вдобавок деликатно тонирует поверхности; в тёмном — графит.
 *
 * buildPalette(spec) собирает ПОЛНЫЙ словарь цветов (тот же набор ключей, что и
 * styles.C в десктопе), а theme-store раскладывает его в CSS-переменные :root.
 */

// НЕЙТРАЛИ ────────────────────────────────────────────────────────────────────
// Светлая база — чистый спокойный нейтрал с лёгкой прохладой.
export const NEUTRALS_LIGHT = {
  bg: '#F4F6F8',
  bg2: '#ECEFF2',
  card: '#FFFFFF',
  card2: '#F4F6F8',
  border: '#E4E9ED',
  border2: '#D3DBE1',
  text: '#0F1B22',
  text3: '#46555F',
  text2: '#7A8893',
  red: '#D14343',
  orange: '#D9892B',
  yellow: '#C99A0C',
  shadow: 'rgba(15,27,34,0.10)',
  overlay: 'rgba(15,27,34,0.40)',
}

// Тёмная база — глубокий нейтральный графит (ориентир Linear), НЕ чёрный.
export const NEUTRALS_DARK = {
  bg: '#0E1113',
  bg2: '#15181B',
  card: '#171B1E',
  card2: '#1E2327',
  border: '#272D32',
  border2: '#333A40',
  text: '#ECEEF0',
  text3: '#AEB8BF',
  text2: '#7E8A92',
  red: '#F2776B',
  orange: '#F0A95A',
  yellow: '#E3C152',
  shadow: 'rgba(0,0,0,0.45)',
  overlay: 'rgba(0,0,0,0.55)',
}

// Фирменный акцент ВСГУТУ (бирюза).
export const DEFAULT_ACCENT = {
  green: '#147C8B',
  green2: '#0E6271',
  green_glow: 'rgba(20,124,139,0.14)',
  blue: '#2BA6B8',
}

export const DEFAULT_ID = 'default'

// Готовый пул палитр (как в десктопе). Каждая задаёт только акцент; производные
// (green2 / green_glow / blue) вычисляются автоматически.
export const PRESETS = [
  { id: 'default', name: 'Стандарт ВСГУТУ', accent: DEFAULT_ACCENT.green },
  { id: 'blue', name: 'Синий', accent: '#1A56DB' },
  { id: 'slate', name: 'Грифельный', accent: '#5B6B7F' },
  { id: 'navy', name: 'Тёмно-синий', accent: '#1E4E79' },
  { id: 'steel', name: 'Стальной', accent: '#4A6274' },
  { id: 'tealgrey', name: 'Серо-бирюзовый', accent: '#5E7E7E' },
  { id: 'teal', name: 'Бирюзовый', accent: '#0E7C6B' },
  { id: 'green', name: 'Зелёный', accent: '#2E7D32' },
  { id: 'sage', name: 'Шалфей', accent: '#6F8B5F' },
  { id: 'olive', name: 'Оливковый', accent: '#A8870B' },
  { id: 'amber', name: 'Янтарный', accent: '#C2680F' },
  { id: 'brown', name: 'Коричневый', accent: '#8D6E63' },
  { id: 'maroon', name: 'Бордовый', accent: '#A33B5C' },
  { id: 'mauve', name: 'Лиловый', accent: '#7E5A6B' },
  { id: 'pink', name: 'Розовый', accent: '#C2417F' },
  { id: 'violet', name: 'Фиолетовый', accent: '#6A4FB3' },
]

const PRESET_BY_ID = Object.fromEntries(PRESETS.map((p) => [p.id, p]))

// ЦВЕТОВЫЕ ХЕЛПЕРЫ ─────────────────────────────────────────────────────────────
// HSV на шкале s,v ∈ [0,255] — как в Qt (QColor), чтобы сдвиги совпадали с десктопом.
function clamp(v) {
  return Math.max(0, Math.min(255, Math.round(v)))
}

function hexToRgb(hex) {
  const h = hex.replace('#', '')
  return {
    r: parseInt(h.slice(0, 2), 16),
    g: parseInt(h.slice(2, 4), 16),
    b: parseInt(h.slice(4, 6), 16),
  }
}

function rgbToHex(r, g, b) {
  const to = (x) => clamp(x).toString(16).padStart(2, '0')
  return `#${to(r)}${to(g)}${to(b)}`
}

function rgbToHsv255({ r, g, b }) {
  const rn = r / 255, gn = g / 255, bn = b / 255
  const max = Math.max(rn, gn, bn), min = Math.min(rn, gn, bn)
  const d = max - min
  let h = 0
  if (d !== 0) {
    if (max === rn) h = ((gn - bn) / d) % 6
    else if (max === gn) h = (bn - rn) / d + 2
    else h = (rn - gn) / d + 4
    h *= 60
    if (h < 0) h += 360
  }
  const s = max === 0 ? 0 : d / max
  return { h, s: s * 255, v: max * 255 }
}

function hsv255ToRgb({ h, s, v }) {
  const sn = s / 255, vn = v / 255
  const c = vn * sn
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1))
  const m = vn - c
  let r = 0, g = 0, b = 0
  if (h < 60) [r, g, b] = [c, x, 0]
  else if (h < 120) [r, g, b] = [x, c, 0]
  else if (h < 180) [r, g, b] = [0, c, x]
  else if (h < 240) [r, g, b] = [0, x, c]
  else if (h < 300) [r, g, b] = [x, 0, c]
  else [r, g, b] = [c, 0, x]
  return { r: (r + m) * 255, g: (g + m) * 255, b: (b + m) * 255 }
}

// Сдвиг яркости/насыщенности в HSV (для производных акцента). Порт _shift_value.
function shiftValue(hex, dv, ds = 0) {
  const hsv = rgbToHsv255(hexToRgb(hex))
  const rgb = hsv255ToRgb({ h: hsv.h, s: clamp(hsv.s + ds), v: clamp(hsv.v + dv) })
  return rgbToHex(rgb.r, rgb.g, rgb.b)
}

// rgba-«свечение» акцента (подсветки/hover). Порт _glow.
function glow(hex, alpha = 0.1) {
  const { r, g, b } = hexToRgb(hex)
  return `rgba(${r},${g},${b},${alpha})`
}

// Подмешивает акцент к БЕЛОМУ (ratio — доля акцента). Порт _tint.
function tint(hex, ratio) {
  const { r, g, b } = hexToRgb(hex)
  return rgbToHex(
    r * ratio + 255 * (1 - ratio),
    g * ratio + 255 * (1 - ratio),
    b * ratio + 255 * (1 - ratio),
  )
}

// Смешивает два цвета (ratio — доля hex_b). Порт _mix.
function mix(hexA, hexB, ratio) {
  const a = hexToRgb(hexA), b = hexToRgb(hexB)
  return rgbToHex(
    a.r * (1 - ratio) + b.r * ratio,
    a.g * (1 - ratio) + b.g * ratio,
    a.b * (1 - ratio) + b.b * ratio,
  )
}

// Акцентные слоты из основного цвета темы. Порт _accent_slots.
function accentSlots(accent, accent2 = null) {
  return {
    green: accent,
    green2: shiftValue(accent, -35),
    green_glow: glow(accent, 0.14),
    blue: accent2 || shiftValue(accent, 30, -25),
  }
}

// СВЕТЛЫЙ режим: деликатный оттенок акцента на поверхностях. Порт _tinted_surfaces.
function tintedSurfaces(accent) {
  return {
    bg: tint(accent, 0.05),
    bg2: tint(accent, 0.09),
    card2: tint(accent, 0.045),
    border: tint(accent, 0.14),
    border2: tint(accent, 0.22),
  }
}

// ТЁМНЫЙ режим: подмешиваем немного акцента в графит. Порт _dark_tinted_surfaces.
function darkTintedSurfaces(accent) {
  const d = NEUTRALS_DARK
  return {
    bg: mix(d.bg, accent, 0.1),
    bg2: mix(d.bg2, accent, 0.12),
    card: mix(d.card, accent, 0.09),
    card2: mix(d.card2, accent, 0.12),
    border: mix(d.border, accent, 0.16),
    border2: mix(d.border2, accent, 0.2),
  }
}

// РЕЖИМ С УЧЁТОМ РАСПИСАНИЯ ────────────────────────────────────────────────────
function normHHMM(v, def) {
  try {
    const [hh, mm] = String(v).split(':').map((x) => parseInt(x, 10))
    if (hh >= 0 && hh < 24 && mm >= 0 && mm < 60) {
      return `${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}`
    }
  } catch { /* мусор — вернём дефолт */ }
  return def
}

function inWindow(t, start, end) {
  if (start === end) return false
  if (start < end) return start <= t && t < end
  return t >= start || t < end // окно через полночь (напр. 18:00–08:00)
}

/** Фактический режим с учётом расписания тёмной темы. Порт effective_mode. */
export function effectiveMode(spec, now = null) {
  spec = spec || {}
  const sch = spec.schedule
  if (sch && sch.enabled) {
    const d = now || new Date()
    const t = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
    return inWindow(t, normHHMM(sch.start, '18:00'), normHHMM(sch.end, '08:00')) ? 'dark' : 'light'
  }
  return spec.mode === 'dark' ? 'dark' : 'light'
}

/** Приводит spec к корректному виду (на случай мусора). Порт normalize_spec. */
export function normalizeSpec(spec) {
  if (typeof spec === 'string') {
    try { spec = JSON.parse(spec) } catch { spec = null }
  }
  if (!spec || typeof spec !== 'object' || !spec.id) return { id: DEFAULT_ID }
  const out = { ...spec }
  if (out.mode !== 'light' && out.mode !== 'dark') delete out.mode
  if (out.schedule && typeof out.schedule === 'object') {
    out.schedule = {
      enabled: !!out.schedule.enabled,
      start: normHHMM(out.schedule.start, '18:00'),
      end: normHHMM(out.schedule.end, '08:00'),
    }
  } else {
    delete out.schedule
  }
  return out
}

/**
 * Собирает ПОЛНЫЙ словарь цветов (формат styles.C) по спецификации темы.
 * Порт themes.build_palette.
 */
export function buildPalette(spec) {
  spec = normalizeSpec(spec)
  const mode = effectiveMode(spec)
  const tid = spec.id || DEFAULT_ID

  const cols = { ...(mode === 'dark' ? NEUTRALS_DARK : NEUTRALS_LIGHT) }
  const surfaces = mode === 'light' ? tintedSurfaces : darkTintedSurfaces

  if (tid === 'custom') {
    const accent = spec.accent || DEFAULT_ACCENT.green
    Object.assign(cols, accentSlots(accent, spec.accent2))
    Object.assign(cols, surfaces(accent))
    return { ...cols, mode }
  }
  if (tid === DEFAULT_ID) {
    Object.assign(cols, DEFAULT_ACCENT)
    Object.assign(cols, surfaces(DEFAULT_ACCENT.green))
    return { ...cols, mode }
  }
  const preset = PRESET_BY_ID[tid]
  if (!preset) {
    Object.assign(cols, DEFAULT_ACCENT) // неизвестный id — безопасный откат
    return { ...cols, mode }
  }
  Object.assign(cols, accentSlots(preset.accent, preset.accent2))
  Object.assign(cols, surfaces(preset.accent))
  return { ...cols, mode }
}

/** (accent, accent2, surface) — три цвета для кружка-превью палитры. */
export function swatchColors(spec) {
  const c = buildPalette(spec)
  return [c.green, c.blue, c.card2]
}
