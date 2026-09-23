/**
 * trustToken.js — секрет доверенного устройства (4.0, «Доверять этому устройству?»).
 *
 * ⚠️ Ключ — С ЛОГИНОМ. На общем телефоне в колледже входят разные люди, и доверие,
 * выданное одному, не должно пропускать без кода из письма другого (сервер это и так
 * проверяет — секрет привязан к логину, — но предъявлять чужой секрет незачем).
 *
 * ⚠️ Выход из аккаунта этот ключ НЕ стирает, и это не забывчивость: семантика принята
 * такая — вышел, а устройство ещё 15 дней доверенное. Стирается ключ, когда сервер
 * доверие снял (галочку сняли) или когда человек сам запросил вход без доверия.
 *
 * Хранилище может отказать (приватный режим, запрет сайта) — тогда доверия просто нет,
 * и вход идёт с кодом из письма. Ни одно чтение не имеет права ронять форму входа.
 */
const PREFIX = 'gb.trust:'

function key(login) {
  return PREFIX + String(login || '').trim().toLowerCase()
}

export function getTrustToken(login) {
  if (!login) return ''
  try { return localStorage.getItem(key(login)) || '' } catch { return '' }
}

export function setTrustToken(login, token) {
  if (!login || !token) return
  try { localStorage.setItem(key(login), token) } catch { /* без хранилища доверия нет */ }
}

export function dropTrustToken(login) {
  if (!login) return
  try { localStorage.removeItem(key(login)) } catch { /* нечего стирать */ }
}
