// sidebar.js — ширина боковой навигации: тянется мышью и запоминается.
//
// ━━ ПОЧЕМУ ЭТО НАСТРОЙКА УСТРОЙСТВА, А НЕ АККАУНТА ━━
// Ширина зависит от МОНИТОРА, а не от человека: за 27 дюймами удобна широкая колонка с
// названиями, на ноутбуке 13" её сворачивают до иконок, чтобы освободить место журналу.
// Держи её на сервере — и один и тот же преподаватель, сев за другой компьютер, получил
// бы чужую раскладку. Тот же принцип, что у выбора микрофона и озвучки (§5.2.1).
//
// ⚠️ Значение читается ДО первой отрисовки (в самом модуле, не в onMounted): иначе при
// каждой загрузке сайдбар успевал бы мигнуть стандартной шириной и только потом
// схлопнуться до сохранённой.
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

const KEY = 'gb.sidebar.w'

// Свёрнутое состояние — ровно иконка плюс поля. Меньше нельзя: пропадёт цель нажатия.
export const MIN_W = 56
export const MAX_W = 420
export const DEFAULT_W = 250
// Ниже этого порога подписи не помещаются и обрезались бы многоточием, поэтому вместо
// них включается вертикальный режим. Порог с запасом: «Расписание» — самое длинное слово.
export const COMPACT_UNDER = 132

function load() {
  try {
    const n = Number(localStorage.getItem(KEY))
    if (Number.isFinite(n) && n >= MIN_W && n <= MAX_W) return n
  } catch { /* приватный режим — просто стандартная ширина */ }
  return DEFAULT_W
}

export const useSidebarStore = defineStore('sidebar', () => {
  const width = ref(load())
  const dragging = ref(false)

  /** Свёрнут ли до иконок: подписи уходят под иконку и разворачиваются вертикально. */
  const compact = computed(() => width.value < COMPACT_UNDER)

  function setWidth(px) {
    const w = Math.min(MAX_W, Math.max(MIN_W, Math.round(px)))
    width.value = w
    try { localStorage.setItem(KEY, String(w)) } catch { /* не смогли — не беда */ }
  }

  /** Двойной щелчок по краю: свернуть до иконок или вернуть стандартную ширину. */
  function toggle() { setWidth(compact.value ? DEFAULT_W : MIN_W) }

  return { width, dragging, compact, setWidth, toggle, MIN_W, MAX_W, DEFAULT_W }
})
