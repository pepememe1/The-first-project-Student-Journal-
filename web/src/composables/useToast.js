// useToast — неблокирующие уведомления (замена браузерного alert()).
// Синглтон: список тостов живёт в модуле, отрисовывает его один <ToastHost/> в App.vue.
// Использование:  const toast = useToast(); toast.error('...'); toast.success('...')
import { reactive } from 'vue'

export const toasts = reactive([])
let seq = 0
//Таймеры снятия: по ним сообщение ставится на паузу, пока на него смотрят (навели мышь).
const timers = new Map()

/**
 * Сколько держать сообщение на экране, мс.
 *
 * 🔥 Было 3,5 с на всё и 6 с на ошибки — независимо от длины (13.10.2026). Ошибка вроде
 * «Не удалось сохранить: итоговая оценка уже выставлена, снимите её…» гасла раньше, чем
 * её успевали дочитать, а человек, который читает медленно, не успевал и короткую.
 * Теперь время зависит от длины текста (медленное чтение — около десяти знаков в
 * секунду), ошибка висит заметно дольше успеха, а верхняя граница не даёт сообщению
 * поселиться на экране навсегда.
 */
export function toastDuration(type, message) {
  const length = String(message ?? '').length
  const floor = type === 'error' ? 8000 : 4000
  const perChar = type === 'error' ? 110 : 70
  return Math.min(30000, Math.max(floor, 1500 + length * perChar))
}

function arm(id, ms) {
  clearTimeout(timers.get(id))
  timers.set(id, setTimeout(() => dismissToast(id), ms))
}

function show(type, message, timeout) {
  const id = ++seq
  const text = String(message ?? '')
  toasts.push({ id, type, message: text })
  if (timeout !== 0) arm(id, timeout || toastDuration(type, text))
  return id
}

export function dismissToast(id) {
  clearTimeout(timers.get(id))
  timers.delete(id)
  const i = toasts.findIndex((t) => t.id === id)
  if (i !== -1) toasts.splice(i, 1)
}

/** Пока на сообщение смотрят (мышь над ним), оно не гаснет. */
export function pauseToast(id) {
  clearTimeout(timers.get(id))
}
/** Отвели взгляд — даём ещё время дочитать и убираем. */
export function resumeToast(id) {
  const t = toasts.find((x) => x.id === id)
  if (t && timers.has(id)) arm(id, Math.max(2500, toastDuration(t.type, t.message) / 2))
}

export function useToast() {
  return {
    success: (m) => show('success', m),
    error: (m) => show('error', m),
    info: (m) => show('info', m),
    //⚠️ `show` — нейтральное сообщение, и держим его НАРОЧНО. Одиннадцать мест звали
    //`toast.show(...)`, которого не существовало: вызов падал с TypeError, а в форме
    //модераторов исключение ловил тот же catch, что и отказ сервера, — модератор был
    //заведён, а на экране стояло «Не удалось сохранить». Вызовы исправлены, а имя
    //оставлено рабочим: опечатка в названии метода не должна ронять обработчик.
    //Набор методов сверяет `web/tests/toastApi.test.mjs`.
    show: (m) => show('info', m),
  }
}
