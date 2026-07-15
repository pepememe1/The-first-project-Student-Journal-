// useToast — неблокирующие уведомления (замена браузерного alert()).
// Синглтон: список тостов живёт в модуле, отрисовывает его один <ToastHost/> в App.vue.
// Использование:  const toast = useToast(); toast.error('...'); toast.success('...')
import { reactive } from 'vue'

export const toasts = reactive([])
let seq = 0

function show(type, message, timeout) {
  const id = ++seq
  toasts.push({ id, type, message: String(message ?? '') })
  if (timeout !== 0) setTimeout(() => dismissToast(id), timeout || 3500)
  return id
}

export function dismissToast(id) {
  const i = toasts.findIndex((t) => t.id === id)
  if (i !== -1) toasts.splice(i, 1)
}

export function useToast() {
  return {
    success: (m) => show('success', m),
    error: (m) => show('error', m, 6000), // ошибки держим дольше
    info: (m) => show('info', m),
  }
}
