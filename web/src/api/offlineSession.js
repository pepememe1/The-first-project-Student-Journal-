/**
 * offlineSession.js — состояние связи и ОКНО РАБОТЫ БЕЗ СЕТИ.
 *
 * Две разные вещи, которые легко перепутать:
 *   • срок СЕССИИ — до ближайшего понедельника, решает и проверяет сервер
 *     (server/app/config.py::issue_ttl_min);
 *   • окно ОФЛАЙНА — сколько приложение вправе работать, ни разу не дозвонившись до
 *     сервера. Сутки. Проверить это на сервере невозможно по определению: в этот
 *     момент сервера нет. Поэтому окно закрывает сам клиент, считая от последнего
 *     успешного ответа.
 *
 * ⚠️ Зачем окно вообще нужно. Без него потерянный или отнятый телефон показывает
 * оценки и расписание сколько угодно долго: достаточно не включать сеть, и ни отзыв
 * сессии администратором, ни смена пароля до него не доедут — отзыв доезжает только
 * по сети, которой нет. Сутки — компромисс: студент в дороге или в корпусе без связи
 * успевает всем воспользоваться, а найденный кем-то телефон замолкает к следующему дню.
 *
 * Когда окно вышло, мы НЕ выходим из аккаунта тихо, а стираем локальные данные и
 * требуем вход заново. При этом ОЧЕРЕДЬ НЕОТПРАВЛЕННЫХ ОЦЕНОК не трогаем (см.
 * outbox.js): работа преподавателя не должна пропадать из-за того, что он сутки был
 * вне сети — она уедет на сервер после первого же входа.
 *
 * Всё это включается ТОЛЬКО в приложении. На сайте окна нет: там вкладка и так живёт
 * ровно пока открыта, а «оффлайн-браузер» не наш сценарий.
 */
import { computed, ref } from 'vue'

// Расширения «.js» — чтобы модуль грузился и голым `node --test` (см. outbox.test.mjs).
import { clearCache } from './offlineCache.js'
import { isNativeApp } from './server.js'

const LS_LAST_ONLINE = 'gb.lastOnlineAt'
const LS_GRACE = 'gb.offlineGraceMin'

// Значение по умолчанию совпадает с server/app/config.py::OFFLINE_GRACE_MIN. Сервер
// присылает своё в /me/prefs, и оно перекрывает это — чтобы политику можно было
// поменять без пересборки приложения.
export const DEFAULT_GRACE_MIN = 1440

/** Есть ли сейчас связь с сервером. Меняется по РЕАЛЬНЫМ ответам, а не по
 *  navigator.onLine: тот показывает лишь наличие сети у устройства и радостно
 *  сообщает «онлайн» в вузовском Wi-Fi без интернета. */
export const online = ref(true)

/** Когда последний раз сервер реально ответил (мс). 0 = ещё ни разу в этой установке. */
export const lastOnlineAt = ref(Number(localStorage.getItem(LS_LAST_ONLINE) || 0))

/** Разрешённое окно офлайна в минутах (сервер может переопределить). */
export const graceMin = ref(Number(localStorage.getItem(LS_GRACE) || DEFAULT_GRACE_MIN))

/** Сколько минут офлайна осталось. Отрицательное — окно вышло. */
export const offlineLeftMin = computed(() => {
  if (!lastOnlineAt.value) return graceMin.value
  return graceMin.value - (Date.now() - lastOnlineAt.value) / 60000
})

let expiredHandler = null
/** Что делать, когда окно вышло (App вешает сюда переход на экран входа). */
export function setOfflineExpiredHandler(fn) { expiredHandler = fn }

/** Сервер ответил: мы онлайн, отсчёт окна начинается заново. */
export function noteOnline() {
  online.value = true
  lastOnlineAt.value = Date.now()
  try { localStorage.setItem(LS_LAST_ONLINE, String(lastOnlineAt.value)) } catch { /* квота */ }
}

/** Запрос не дошёл — считаем, что связи нет. */
export function noteOffline() {
  online.value = false
}

/** Политика окна с сервера (приходит в /me/prefs вместе с остальными настройками). */
export function setGraceMin(minutes) {
  const n = Number(minutes)
  if (!Number.isFinite(n) || n <= 0) return
  graceMin.value = n
  try { localStorage.setItem(LS_GRACE, String(n)) } catch { /* квота */ }
}

/**
 * Вышло ли окно. Отдельно ловим ПЕРЕВОД ЧАСОВ НАЗАД.
 *
 * Окно считается по часам самого телефона, а их владелец волен переставить — это
 * первое, что сделает человек, которому нужно продлить доступ к чужому устройству.
 * Отличить «перевели назад» от нормального хода можно надёжно: время последнего
 * удачного ответа не может оказаться в будущем. Оказалось — значит часы двигали, и
 * доверять им больше нельзя; закрываем окно немедленно.
 */
export function offlineWindowExpired() {
  if (!isNativeApp()) return false          // правило только для приложения
  if (!lastOnlineAt.value) return false     // ни одного успешного ответа — судить не по чему
  const elapsed = Date.now() - lastOnlineAt.value
  if (elapsed < 0) return true              // часы перевели назад
  return elapsed > graceMin.value * 60000
}

/**
 * Проверка окна. Зовётся по таймеру, при возвращении приложения из фона и перед
 * показом защищённых страниц — то есть в моменты, когда человек реально что-то видит.
 */
export function enforceOfflineWindow() {
  if (!offlineWindowExpired()) return false
  clearCache()                 // локальную копию оценок с телефона убираем
  online.value = false
  if (expiredHandler) expiredHandler()
  return true
}

let timer = null
/** Периодическая проверка. Минута — достаточно часто: окно измеряется сутками. */
export function startOfflineWatch() {
  if (timer || !isNativeApp()) return
  timer = setInterval(enforceOfflineWindow, 60000)
  enforceOfflineWindow()
}

export function stopOfflineWatch() {
  if (timer) { clearInterval(timer); timer = null }
}

/** Полный сброс при выходе — чтобы у следующего вошедшего окно считалось с нуля. */
export function resetOfflineSession() {
  lastOnlineAt.value = 0
  online.value = true
  try { localStorage.removeItem(LS_LAST_ONLINE) } catch { /* */ }
}
