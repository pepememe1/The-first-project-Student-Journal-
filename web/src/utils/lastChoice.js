/**
 * lastChoice.js — журнал помнит, с какой группой и предметом человек работал.
 *
 * Зачем (13.10.2026, живой обход: «Журнал, Студенты и Статистика каждый раз открываются на
 * первой группе списка, а не на той, с которой работали»). Преподаватель ведёт одну-две
 * группы изо дня в день, и выбирать их заново на каждой странице — лишний шаг, на котором
 * неуверенный человек ещё и ошибается группой.
 *
 * 🔒 Выбор принадлежит ЧЕЛОВЕКУ, а компьютер в колледже общий. Правило проекта: всё, что
 * лежит в localStorage, либо ключуется логином, либо стирается при выходе. Здесь ключ —
 * отпечаток логина (сам логин бывает почтой, оставлять его в хранилище после выхода
 * незачем). Следующий вошедший чужого выбора не увидит: у него другой ключ.
 *
 * ⚠️ Запомненное — подсказка, а не истина: вызывающий обязан сверить его со списком,
 * который прислал сервер (`pickRemembered`). Группу могли снять с преподавателя, и слепая
 * подстановка открыла бы журнал, который сервер не отдаст.
 */
import { fingerprint } from './sessionResume.js'

const PREFIX = 'gb.choice:'

function box(given) {
  if (given) return given
  try { return typeof localStorage === 'undefined' ? null : localStorage } catch { return null }
}

/** Запомненный выбор человека: `{ group, subject, ... }` или пустой объект. */
export function recallChoice(login, { store } = {}) {
  const b = box(store)
  if (!b || !String(login || '').trim()) return {}
  try {
    const v = JSON.parse(b.getItem(PREFIX + fingerprint(login)) || '{}')
    return v && typeof v === 'object' && !Array.isArray(v) ? v : {}
  } catch { return {} }
}

/** Дописать в выбор человека поля `patch` (пустые значения не затирают прежние). */
export function rememberChoice(login, patch, { store } = {}) {
  const b = box(store)
  if (!b || !String(login || '').trim()) return
  const next = { ...recallChoice(login, { store: b }) }
  for (const [k, v] of Object.entries(patch || {})) if (v) next[k] = String(v)
  try { b.setItem(PREFIX + fingerprint(login), JSON.stringify(next)) } catch { /* без памяти — как раньше */ }
}

/**
 * Что выбрать из списка `options`: явное (из ссылки) → запомненное → первое.
 * Значение, которого в списке нет, не берётся никогда.
 */
export function pickRemembered(options, explicit, remembered) {
  const list = options || []
  if (explicit && list.includes(explicit)) return explicit
  if (remembered && list.includes(remembered)) return remembered
  return list[0] || ''
}
