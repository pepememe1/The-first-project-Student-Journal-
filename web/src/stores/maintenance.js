// Технические работы (мягкий рубильник, server/app/maintenance.py). Пока включены, всех,
// кроме администратора, сайт переводит на ту же страницу, что и жёсткий рубильник Caddy:
// web/public/maintenance/index.html — одна страница на оба (решение Ярослава 27.10.2026).
// Администратору — плашка и только круг сервера (ADMIN_ROUTES).
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/api/client'
import { getApiBase, isNativeApp } from '@/api/server'
import { isPcProgram } from '@/utils/platform'

// Разделы админки, открытые во время работ; зеркало ADMIN_PREFIXES на сервере.
export const ADMIN_ROUTES = ['/admin/server', '/admin/honeypot', '/admin/audit', '/admin/access', '/admin/settings']

export const useMaintenanceStore = defineStore('maintenance', () => {
  const on = ref(false)
  const message = ref('')
  const since = ref(0)

  async function refresh() {
    try {
      const { data } = await api.get('/app/maintenance')
      on.value = !!data?.on
      message.value = data?.message || ''
      since.value = data?.since || 0
    } catch { /* нет связи — не наше дело решать здесь */ }
    return on.value
  }

  // Программа для Windows работает с журналом из своей копии и без сайта: её на страницу
  // работ не уводим (там бы она ушла по кругу: локальный сервер работ не знает).
  function goToPage() {
    if (isPcProgram()) return false
    const params = new URLSearchParams()
    if (isNativeApp()) params.set('api', getApiBase())
    const back = window.location.pathname + window.location.search
    if (back.startsWith('/') && !back.startsWith('/maintenance')) params.set('back', back)
    window.location.replace('/maintenance/index.html' + (params.toString() ? '?' + params : ''))
    return true
  }

  async function setOn(value, text = '') {
    const { data } = await api.post('/admin/maintenance', { on: value, message: text })
    on.value = !!data?.on
    message.value = data?.message || ''
    since.value = data?.since || 0
    return data
  }

  return { on, message, since, refresh, goToPage, setOn }
})
