/**
 * server.js — адрес сервера в РАНТАЙМЕ (порт desktop app_settings.get_api_url/set_api_url).
 *
 * Зачем: в мобильном приложении (Capacitor) веб-оболочка открывается со своего
 * локального адреса (https://localhost), поэтому относительные `/web/*` никуда не
 * ведут — нужен ЯВНЫЙ адрес сервера. Как в десктопе: при первом запуске пользователь
 * вводит ссылку, она сохраняется и дальше все запросы идут на неё.
 *
 * В браузере (обычный сайт) адрес не нужен — работаем на том же origin (same-origin),
 * поэтому getApiBase() по умолчанию пустой. Пользователь всё равно может задать адрес
 * вручную (кнопка «⚙ Сервер») — удобно для теста.
 */
import { ref } from 'vue'

const LS_KEY = 'gb.api_base'

// Боевой адрес по умолчанию — ВШИТ (как DEFAULT_API_URL в десктопе). В приложении с него
// всё работает сразу; сменить можно кнопкой «⚙ Сервер» (сохранится и перекроет дефолт).
export const DEFAULT_API_BASE = 'https://esstu-gradebook.ru'

// Реактивный текущий адрес (для UI). Пусто = same-origin (браузерный сайт).
export const apiBase = ref(localStorage.getItem(LS_KEY) || '')

/** Приоритет: сохранённый адрес → сборочный VITE_API_BASE → дефолт (в приложении).
 *  В браузере-сайте по умолчанию '' — тот же origin (для dev-прокси и прод-домена). */
export function getApiBase() {
  return localStorage.getItem(LS_KEY) || import.meta.env.VITE_API_BASE
    || (isNativeApp() ? DEFAULT_API_BASE : '')
}

/** Нормализует ввод: добавляет https:// если схемы нет, убирает хвостовые «/». */
export function normalizeUrl(raw) {
  let u = (raw || '').trim()
  if (!u) return ''
  if (!/^https?:\/\//i.test(u)) u = 'https://' + u
  return u.replace(/\/+$/, '')
}

export function setApiBase(url) {
  const u = normalizeUrl(url)
  localStorage.setItem(LS_KEY, u)
  apiBase.value = u
  return u
}

export function clearApiBase() {
  localStorage.removeItem(LS_KEY)
  apiBase.value = ''
}

/** Запущены ли мы как нативное приложение (Capacitor его помечает в window). */
export function isNativeApp() {
  try {
    return !!(window.Capacitor && window.Capacitor.isNativePlatform && window.Capacitor.isNativePlatform())
  } catch {
    return false
  }
}

/** Экран подключения больше НЕ форсируем: есть вшитый дефолт, приложение работает
 *  сразу. Сервер меняют вручную кнопкой «⚙ Сервер». Оставлено для совместимости. */
export function needsServer() {
  return false
}

/** Проверка доступности сервера (GET /health). mode:'no-cors' — чтобы кросс-доменный
 *  ответ (у прод-сервера CORS сужен на его домен) не давал ЛОЖНОЙ ошибки: opaque-ответ
 *  = сервер ответил, значит доступен. В нативе (CapacitorHttp) запрос идёт мимо CORS и
 *  так. Сеть недоступна/адрес неверный → fetch отклонится → false. */
export async function checkHealth(url) {
  const base = normalizeUrl(url)
  if (!base) return false
  try {
    await fetch(base + '/health', { method: 'GET', mode: 'no-cors' })
    return true
  } catch {
    return false
  }
}
