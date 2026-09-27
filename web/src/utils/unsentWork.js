/**
 * unsentWork.js — «всё ли дошло до сервера» перед выходом из аккаунта (W-11, 26.09.2026).
 *
 * 🔥 ЗАЧЕМ. На общем компьютере колледжа выход — это смена владельца устройства. Правки,
 * не дошедшие до боя, при этом не пропадают: очередь программы лежит в зашифрованной
 * копии и дождётся владельца (F-02), очередь сайта и телефона — в хранилище под его
 * логином. Но уйдут они, ТОЛЬКО когда он снова войдёт ЗДЕСЬ ЖЕ. Человек этого не знал:
 * функция `desk_outbox.has_unsent` существовала и не звалась никем, выход спрашивал
 * «точно?» только у пасхалки. Преподаватель уходил, уверенный, что оценки на сервере, а
 * они ждали его на чужом компьютере аудитории.
 *
 * ⚠️ Очередей ДВЕ, и спрашивать надо обе: в программе журнал пишет через локальный
 * сервер (`/desk/sync/status`), на сайте и телефоне — через `outbox.js`. Программа при
 * этом тоже держит `outbox.js` (на случай, когда её же локальный сервер недоступен).
 * ⚠️ Выход не ЗАПРЕЩАЕТСЯ — только спрашивает. Запрет запер бы человека в чужом аккаунте
 * на общем компьютере ровно тогда, когда сети нет, то есть когда очередь и не уйдёт.
 */
import { getAccess } from '../api/tokens.js'
import { pending, rejected, flushOutbox } from '../api/outbox.js'

//Сколько ждём попытку дослать очередь сайта перед выходом. Сеть есть — очередь уходит
//за доли секунды и вопроса не будет; сети нет — клиент ждал бы свои 20 с на КАЖДОЙ
//записи, а человек смотрел бы на зависшую кнопку «Выйти».
const FLUSH_WAIT_MS = 4000

/**
 * Сводка по обеим очередям. Чистая функция — её держит `unsentWork.test.mjs`.
 *
 * `desk` — ответ `/desk/sync/status` (null — мы не в программе), `sitePending` и
 * `siteRejected` — размеры очередей `outbox.js`.
 * `waiting` — ещё не отправлено; `problems` — ждёт решения человека (конфликт, отказ);
 * `unknown` — программа не смогла прочитать свою очередь, и сказать «всё ушло» нельзя.
 */
export function unsentSummary(desk, sitePending = 0, siteRejected = 0) {
  const ob = desk && desk.outbox && typeof desk.outbox === 'object' ? desk.outbox : {}
  const unknown = Boolean(desk && (desk.unknown || ob.available === false))
  let waiting = (Number(ob.pending) || 0) + (Number(sitePending) || 0)
  const problems = (Number(ob.conflicts) || 0) + (Number(ob.rejected) || 0)
    + (Number(siteRejected) || 0)
  //Признак от самой программы (`desk_outbox.has_unsent`) главнее счётчиков: правило «что
  //считается неотправленным» живёт у неё одно, и разойтись с ним здесь молча нельзя.
  if (desk && desk.unsent === true && waiting + problems === 0) waiting = 1
  return { waiting, problems, unknown, total: waiting + problems }
}

/** Спрашивать ли человека перед выходом. */
export function shouldAskBeforeLogout(summary) {
  return Boolean(summary && (summary.total > 0 || summary.unknown))
}

/** Строки вопроса: [ключ словаря, параметры]. Порядок — от важного к общему. */
export function unsentMessageParts(summary) {
  const parts = []
  if (summary.waiting > 0) parts.push(['logout.unsent.waiting', { n: summary.waiting }])
  if (summary.problems > 0) parts.push(['logout.unsent.problems', { n: summary.problems }])
  if (summary.unknown) parts.push(['logout.unsent.unknown', {}])
  return parts
}

/**
 * Состояние очереди программы; null — мы не в программе.
 *
 * ⚠️ На сайте `/desk/*` не маршрут API, и заглушка SPA отвечает на него СТРАНИЦЕЙ с кодом
 * 200. Поэтому «не программа» — это и 404/403, и ответ, который не разбирается как JSON.
 * Любая другая беда своего же локального сервера (5xx) — «не знаем», а не «всё ушло».
 */
export async function readDeskStatus(fetchImpl = globalThis.fetch, waitMs = FLUSH_WAIT_MS) {
  //⚠️ Со СРОКОМ (второй заход Полковника, 26.09.2026): локальный сервер, занятый
  //долгой операцией, иначе держал бы кнопку «Выйти» бесконечно. Не ответил вовремя —
  //«не знаем», и человек получает вопрос, а не зависший экран.
  const ctl = typeof AbortController !== 'undefined' ? new AbortController() : null
  const TIMEOUT = Symbol('timeout')
  let r
  let t
  try {
    const token = getAccess()
    const timer = new Promise((resolve) => {
      t = setTimeout(() => { if (ctl) ctl.abort(); resolve(TIMEOUT) }, waitMs)
    })
    r = await Promise.race([fetchImpl('/desk/sync/status', {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      ...(ctl ? { signal: ctl.signal } : {}),
    }), timer])
  } catch {
    return null        //до своего локального сервера не достучаться иначе как вне программы
  } finally {
    clearTimeout(t)
  }
  if (r === TIMEOUT) return { unknown: true }
  if (r.status === 404 || r.status === 403) return null
  let data
  try {
    data = await r.json()
  } catch {
    return null
  }
  if (!r.ok) return { unknown: true }
  return data && typeof data === 'object' ? data : null
}

//⚠️ Таймер гасим сами: висящий `setTimeout` держал бы процесс `node --test` (та же
//грабля, что у повтора в outbox.js), а в браузере — лишний тик после выхода.
function withTimeout(promise, ms) {
  let t
  const timer = new Promise((resolve) => { t = setTimeout(resolve, ms) })
  return Promise.race([promise, timer]).finally(() => clearTimeout(t))
}

/** Попробовать дослать очередь сайта и собрать сводку по обеим очередям. */
export async function collectUnsent({ fetchImpl = globalThis.fetch, flush = flushOutbox,
  waitMs = FLUSH_WAIT_MS } = {}) {
  if (pending.value.length) {
    try { await withTimeout(Promise.resolve().then(flush), waitMs) } catch { /* не вышло — спросим */ }
  }
  const desk = await readDeskStatus(fetchImpl, waitMs)
  return unsentSummary(desk, pending.value.length, rejected.value.length)
}
