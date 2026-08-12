/**
 * vectorOffline.js — «Вектор» без интернета: отвечает из сохранённой копии данных.
 *
 * Тот же принцип, что у сетевого Вектора и у офлайн-Вектора на десктопе: ФАКТЫ берутся
 * из данных, а не сочиняются. Разница ровно одна — данные не из свежего запроса, а из
 * последнего сохранённого ответа сервера, и человеку об этом говорится прямо.
 *
 * ━━ ЧТО ЗДЕСЬ КАТЕГОРИЧЕСКИ НЕЛЬЗЯ ━━
 * СЧИТАТЬ. Ни средний балл, ни долги, ни часы. Все эти числа уже посчитаны сервером
 * (`grading.py`, `study_hours.py`) и лежат в сохранённом ответе готовыми — мы их только
 * ЧИТАЕМ. Появись здесь хоть одно деление, в продукте оказалось бы ДВЕ формулы среднего
 * балла, и они разошлись бы: у продукта нетривиальные пересдачи, шкалы преподавателей и
 * подгруппы. Инвариант проекта прямой — расчёт живёт в одном месте.
 *
 * ━━ ЧЕГО НЕ ДЕЛАЕМ ━━
 * Не выдумываем ответ, когда данных нет. «Не знаю без сети» — правильный ответ; правдоподобная
 * цифра, взятая непонятно откуда, хуже отказа, потому что её не перепроверят.
 * Никакой LLM: её здесь и не может быть, но даже будь она — переформулировать факты офлайн
 * некому и незачем.
 */
import { findCached, readCache } from '../api/offlineCache.js'
import { classify } from './vectorNlu.js'

/** Интенты, на которые офлайн ответить нечем в принципе — только на сервере. */
const NEEDS_SERVER = new Set([
  'weather',        // погода приезжает из метеослужбы
  'zet',            // порог перевода — серверная политика, офлайн его нет
  'server_state',   // состояние боевой машины
  'debtors',        // сводка по чужим студентам
  'risk',           // риск отчисления считает сервер
])

function journal() { return readCache({ url: '/web/student/journal', params: {} })?.data || null }
function stats() { return readCache({ url: '/web/student/stats', params: {} })?.data || null }
function overview() { return readCache({ url: '/web/student/overview', params: {} })?.data || null }
function schedule() { return findCached('/web/schedule')?.data || null }

function list(items, limit = 12) {
  const shown = items.slice(0, limit)
  const tail = items.length > shown.length ? `\nи ещё ${items.length - shown.length}` : ''
  return shown.join('\n') + tail
}

// ───────────────────────── ответы по интентам ─────────────────────────

function answerGrades() {
  const j = journal()
  if (!j?.subjects?.length) return null
  const rows = j.subjects.map((s) => {
    const graded = (s.lessons || []).filter((l) => l.grade).length
    // s.average пришёл С СЕРВЕРА. Не пересчитываем — см. шапку файла.
    return `• ${s.subject}: ${s.average || '—'}${graded ? ` (оценок: ${graded})` : ' — оценок пока нет'}`
  })
  return `Вот что у меня сохранено по предметам:\n${list(rows)}`
}

function answerAverage() {
  const value = stats()?.average ?? overview()?.average
  if (value == null) return null
  return `Общий средний балл — ${value}.`
}

function answerGradeCount() {
  const o = overview()
  if (!o) return null
  const total = o.grades_total
  if (total == null) return null
  const month = o.grades_month != null ? ` За месяц — ${o.grades_month}.` : ''
  return `Всего оценок — ${total}.${month}`
}

function answerSubjects() {
  const j = journal()
  if (!j?.subjects?.length) return null
  return `Предметы:\n${list(j.subjects.map((s) => `• ${s.subject}`))}`
}

function answerDebts() {
  const d = stats()?.debts
  if (d == null) return null
  if (!d.length) return 'Задолженностей нет.'
  const rows = d.map((x) => (typeof x === 'string' ? `• ${x}` : `• ${x.subject || ''} ${x.lesson || ''}`.trim()))
  return `Задолженности:\n${list(rows)}`
}

function answerAbsences() {
  const a = stats()?.absences
  if (a == null) return null
  if (typeof a === 'object') {
    const parts = Object.entries(a).map(([k, v]) => `${k}: ${v}`)
    return `Пропуски — ${parts.join(', ')}.`
  }
  return `Пропусков — ${a}.`
}

function answerHomework(subject) {
  const j = journal()
  if (!j?.subjects?.length) return null
  const rows = []
  for (const s of j.subjects) {
    if (subject && s.subject !== subject) continue
    for (const l of s.lessons || []) {
      if (l.type !== 'ДЗ') continue
      const status = l.grade ? `оценка ${l.grade}` : 'не сдано'
      rows.push(`• ${s.subject}: ${l.topic || 'без темы'}${l.date ? ` (${l.date})` : ''} — ${status}`)
    }
  }
  if (!rows.length) return subject ? `По предмету «${subject}» домашних заданий не сохранено.` : 'Домашних заданий не сохранено.'
  return `Домашние задания:\n${list(rows)}`
}

function answerSchedule() {
  const s = schedule()
  const weeks = s?.weeks
  if (!weeks) return null
  // Расписание отдаём КАК ЕСТЬ, без попытки вычислить «что сейчас»: чётность недели и
  // текущая пара считаются по своим правилам (см. контракт week-parity-cases.json), и
  // вторая их копия здесь разошлась бы с продуктом.
  const days = []
  for (const week of Object.keys(weeks)) {
    for (const day of Object.keys(weeks[week] || {})) {
      const pairs = (weeks[week][day] || []).filter(Boolean)
      if (pairs.length) days.push(`• ${day} (неделя ${week}): пар — ${pairs.length}`)
    }
  }
  if (!days.length) return null
  return `Сохранённое расписание:\n${list(days, 14)}`
}

const STATIC = {
  hello: 'Привет! Сейчас я работаю без интернета — отвечаю по сохранённым данным.',
  thanks: 'Пожалуйста!',
  help: 'Без сети я умею: оценки, средний балл, предметы, задолженности, пропуски, '
    + 'домашние задания и сохранённое расписание. Остальное — когда появится связь.',
}

/**
 * Ответить на вопрос без сети.
 *
 * @returns {{text: string, intent: string, mood: string, offline: true}}
 */
export function answerOffline(question, { surnames = [], subjects = null } = {}) {
  // Список предметов нужен классификатору, чтобы понять «что там по физике». Берём его
  // из того же сохранённого журнала, по которому потом и отвечаем: спрашивать вызывающего
  // значило бы, что каждый экран собирает его по-своему и однажды соберёт иначе.
  const subjectList = subjects ?? (journal()?.subjects || []).map((s) => s.subject)
  const { intent, subject } = classify(question, surnames, subjectList)

  let text = null
  if (STATIC[intent]) text = STATIC[intent]
  else if (NEEDS_SERVER.has(intent)) text = null
  else if (intent === 'grades' || intent === 'subject_grades') text = answerGrades()
  else if (intent === 'average') text = answerAverage()
  else if (intent === 'grade_count') text = answerGradeCount()
  else if (intent === 'subjects') text = answerSubjects()
  else if (intent === 'debts') text = answerDebts()
  else if (intent === 'absences') text = answerAbsences()
  else if (intent === 'homework') text = answerHomework(subject)
  else if (intent === 'schedule') text = answerSchedule()

  if (!text) {
    // Честный отказ вместо выдумки. Отдельно называем причину: «не понял вопрос» и
    // «нет данных без сети» — разные вещи, и человек по-разному на них реагирует.
    text = NEEDS_SERVER.has(intent)
      ? 'На этот вопрос я отвечу только со связью — данные считает сервер.'
      : 'Без интернета таких данных у меня не сохранено. Отвечу, когда появится связь.'
  }

  return { text, intent, mood: 'neutral', offline: true }
}
