// Часы колледжа на клиенте — зеркало корневого `college_clock.py`.
//
// Колледж живёт по Улан-Удэ (UTC+8 круглый год), а устройство — где угодно: студент на
// практике в Москве, родитель в Новосибирске, ноутбук с неверно выставленным поясом.
// До 15.10.2026 сайт брал «сегодня», «вчера» и «который час» у устройства, а сервер — у
// своей машины (Москва): дата занятия по умолчанию, подписи «Сегодня/Вчера» в чате,
// время сообщений, сроки трекера и напоминания расходились с журналом на часы, и только
// у тех, кто не в Улан-Удэ, — то есть ровно там, где этого никто не проверяет.
//
// ⚠️ Смещение — фиксированное число, а не `timeZone: 'Asia/Irkutsk'`: база поясов у
// старых WebView бывает неполной, а летнего времени у Иркутска нет. Число сверяет
// `web/tests/collegeTime.test.mjs` с `college_clock.py` — две копии расходятся молча.
//
// ⚠️ ХРАНИТЬ и отправлять на сервер — по-прежнему МОМЕНТ (`toISOString()`, UTC). Этот
// модуль — про календарь и циферблат: какое число, какой день недели, сколько на часах.
//
// Приём: «стена» — Date, сдвинутый на смещение колледжа; его UTC-геттеры показывают
// часы колледжа. Наружу стена не отдаётся никогда: сериализованная, она была бы другим
// моментом времени.

export const COLLEGE_UTC_OFFSET_MIN = 8 * 60
const OFF_MS = COLLEGE_UTC_OFFSET_MIN * 60000
const DAY_MS = 86400000

const pad = (n) => String(n).padStart(2, '0')

function toDate(v) {
  if (v instanceof Date) return v
  if (v === undefined || v === null || v === '') return new Date(NaN)
  return new Date(v)
}

function wall(v) {
  const d = toDate(v)
  return new Date(d.getTime() + OFF_MS)
}

/** Части даты и времени на часах колледжа. weekday: 0 — воскресенье (как `getDay`). */
export function collegeParts(v = new Date()) {
  const w = wall(v)
  return {
    year: w.getUTCFullYear(), month: w.getUTCMonth() + 1, day: w.getUTCDate(),
    hours: w.getUTCHours(), minutes: w.getUTCMinutes(), seconds: w.getUTCSeconds(),
    weekday: w.getUTCDay(),
  }
}

/** Ключ дня колледжа «ГГГГ-ММ-ДД» — для сравнения «тот же день?» и группировки. */
export function collegeDayKey(v = new Date()) {
  const p = collegeParts(v)
  return Number.isNaN(p.year) ? '' : `${p.year}-${pad(p.month)}-${pad(p.day)}`
}

/** «ДД.ММ.ГГГГ» — формат дат занятий в журнале. */
export function collegeDdmmyyyy(v = new Date()) {
  const p = collegeParts(v)
  return Number.isNaN(p.year) ? '' : `${pad(p.day)}.${pad(p.month)}.${p.year}`
}

/** «ЧЧ:ММ» на часах колледжа. */
export function collegeHhmm(v = new Date()) {
  const p = collegeParts(v)
  return Number.isNaN(p.hours) ? '' : `${pad(p.hours)}:${pad(p.minutes)}`
}

/** Момент, на котором часы колледжа показывают указанные число и время. */
export function fromCollegeWall(year, month, day, hours = 0, minutes = 0) {
  return new Date(Date.UTC(year, month - 1, day, hours, minutes) - OFF_MS)
}

/** Тот же момент через n суток (смещение постоянное — сутки всегда 24 часа). */
export function addDays(v, n) {
  return new Date(toDate(v).getTime() + n * DAY_MS)
}

/** Сколько СУТОК КОЛЛЕДЖА от a до b (по числам, а не по 24-часовым отрезкам). */
export function collegeDayDiff(a, b) {
  const pa = collegeParts(a)
  const pb = collegeParts(b)
  return Math.round((Date.UTC(pb.year, pb.month - 1, pb.day) - Date.UTC(pa.year, pa.month - 1, pa.day)) / DAY_MS)
}

/**
 * Локализованная подпись по часам колледжа — замена `toLocaleString`/`DateString`/
 * `TimeString`. Опции — те же, что у `Intl.DateTimeFormat`; без опций — дата и время.
 */
export function formatCollege(v, locale, opts) {
  const d = toDate(v)
  if (Number.isNaN(d.getTime())) return ''
  const o = opts && Object.keys(opts).length ? opts : { dateStyle: 'short', timeStyle: 'short' }
  try {
    return new Intl.DateTimeFormat(locale || undefined, { ...o, timeZone: 'UTC' }).format(wall(d))
  } catch {
    return `${collegeDdmmyyyy(d)} ${collegeHhmm(d)}`
  }
}

/** Значение для `<input type="datetime-local">`: часы колледжа, «ГГГГ-ММ-ДДTЧЧ:ММ». */
export function toCollegeInput(v) {
  const p = collegeParts(v)
  return Number.isNaN(p.year) ? '' : `${p.year}-${pad(p.month)}-${pad(p.day)}T${pad(p.hours)}:${pad(p.minutes)}`
}

/** Обратное к `toCollegeInput`: то, что человек выбрал, — это время на часах колледжа. */
export function fromCollegeInput(s) {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(String(s || ''))
  return m ? fromCollegeWall(+m[1], +m[2], +m[3], +m[4], +m[5]) : new Date(NaN)
}
