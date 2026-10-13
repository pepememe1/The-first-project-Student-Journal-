/**
 * sessionResume.js — вернуть человека туда, где его застало окончание сессии.
 *
 * Зачем (13.10.2026). Сессия живёт пять часов. Когда она кончалась, журнал молча
 * показывал форму входа, а после входа открывал ГЛАВНУЮ: преподаватель, ставивший оценки
 * в журнале группы, оказывался на другом экране и заново искал группу и предмет. Для
 * человека, который и так не уверен в себе за компьютером, это выглядит как «я что-то
 * сломал и всё пропало».
 *
 * 🔒 ВОЗВРАЩАЕМ ТОЛЬКО ТОГО ЖЕ ЧЕЛОВЕКА. Компьютер в колледже общий: сессия кончилась у
 * одного, а войти следом может другой, и вести его на чужую страницу с чужой группой в
 * адресе нельзя. Поэтому рядом с адресом лежит отпечаток логина, и адрес отдаётся только
 * при совпадении.
 * ⚠️ Именно отпечаток, а не логин: логином бывает почта, и оставлять её в хранилище
 * вкладки после конца сессии незачем. Отпечаток не секрет и не защита — он только
 * отличает «тот же» от «другой»; совпадение у разных людей ничего не открывает, потому
 * что доступ к странице всё равно проверяют роутер и сервер.
 *
 * ⚠️ `sessionStorage`, а не `localStorage`: возврат относится к ЭТОЙ вкладке и не должен
 * пережить её закрытие. Чтение ОДНОРАЗОВОЕ — адрес стирается при первом же запросе.
 */
import { safeRedirect } from './deepLinks.js'

const KEY = 'gb.resume'
/** Дольше возвращать незачем: через полсуток человек уже не помнит, где был. */
export const RESUME_MAX_AGE_MS = 12 * 60 * 60 * 1000

/** Короткий отпечаток строки (djb2). Не криптография — см. шапку. */
export function fingerprint(text) {
  let h = 5381
  for (const ch of String(text || '').trim()) h = ((h * 33) ^ ch.codePointAt(0)) >>> 0
  return h.toString(36)
}

function storage(given) {
  if (given) return given
  try { return typeof sessionStorage === 'undefined' ? null : sessionStorage } catch { return null }
}

/** Адрес, куда возвращаться незачем: вход, промах по адресу, первый экран. */
function resumable(fullPath) {
  const path = safeRedirect(fullPath)
  if (!path || path === '/' || /^\/(404|connect)(\/|\?|$)/.test(path)) return ''
  return path
}

/** Запомнить, где был человек `login`, когда сессия кончилась. */
export function rememberResume(login, fullPath, { now = Date.now(), store } = {}) {
  const box = storage(store)
  const path = resumable(fullPath)
  if (!box || !path || !String(login || '').trim()) return false
  try {
    box.setItem(KEY, JSON.stringify({ who: fingerprint(login), path, at: now }))
    return true
  } catch { return false }      //приватный режим: без возврата, вход от этого не зависит
}

/** Куда вернуть вошедшего `login` ('' — некуда). Запись стирается в любом случае. */
export function takeResume(login, { now = Date.now(), store } = {}) {
  const box = storage(store)
  if (!box) return ''
  let saved = null
  try {
    saved = JSON.parse(box.getItem(KEY) || 'null')
    box.removeItem(KEY)
  } catch { return '' }
  if (!saved || saved.who !== fingerprint(login)) return ''
  if (!(now - Number(saved.at) < RESUME_MAX_AGE_MS)) return ''
  return resumable(saved.path)
}

/** Забыть адрес возврата: человек вышел сам и возвращать его некуда. */
export function dropResume({ store } = {}) {
  try { storage(store)?.removeItem(KEY) } catch { /* хранилище недоступно — и так пусто */ }
}
