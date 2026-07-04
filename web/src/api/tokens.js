/**
 * tokens.js — единое хранилище токенов и идентификатора устройства (localStorage).
 *
 * Вынесено отдельно от auth-store и axios-клиента, чтобы избежать циклических
 * импортов: и стор, и интерсепторы читают токены отсюда.
 *
 * ⚠️ Веб-модель отличается от десктопа: в браузере нет DPAPI, поэтому access/refresh
 * лежат в localStorage. Это компромисс SPA; безопасность держится на коротком access
 * (5 ч), серверном чёрном списке (revoke) и HTTPS. При «Выйти» токены гасятся и на
 * сервере (/auth/logout), а не только стираются локально.
 */
const K_ACCESS = 'gb.access'
const K_REFRESH = 'gb.refresh'
const K_DEVICE = 'gb.device_id'

export function getAccess() {
  return localStorage.getItem(K_ACCESS) || ''
}

export function getRefresh() {
  return localStorage.getItem(K_REFRESH) || ''
}

export function setTokens({ access, refresh }) {
  if (access != null) localStorage.setItem(K_ACCESS, access)
  if (refresh) localStorage.setItem(K_REFRESH, refresh)
}

export function clearTokens() {
  localStorage.removeItem(K_ACCESS)
  localStorage.removeItem(K_REFRESH)
}

/**
 * Стабильный идентификатор этого браузера (X-Device-Id).
 * Нужен для веб-подтверждения устройства персонала (teacher/admin): по нему сервер
 * узнаёт одобренный браузер. Студентам барьер не применяется, но заголовок шлём всегда.
 */
export function getDeviceId() {
  let id = localStorage.getItem(K_DEVICE)
  if (!id) {
    const rand = (globalThis.crypto?.randomUUID?.() || String(Math.random()).slice(2)).replace(/-/g, '')
    id = `web-${rand}`
    localStorage.setItem(K_DEVICE, id)
  }
  return id
}
