/**
 * lessonChecks.js — «защита от дурака» в журнале преподавателя (13.10.2026).
 *
 * Живой обход стенда глазами новичка: занятие создавалось с датой 01.01.2099 и с номером,
 * который уже есть в журнале; окно удаления говорило «оценки перестанут учитываться» и не
 * называло, СКОЛЬКО их и за какое число (в журнале стояли две «Практика №6»). Правила
 * вынесены сюда, чтобы их проверял тест без браузера, а не глаз.
 *
 * ⚠️ Дату и дубль номера мы НЕ запрещаем, а переспрашиваем: занятие «задним числом» и
 * лекция двумя строками с одним номером бывают законными. Запрещаем только то, что датой
 * не является вовсе.
 */

import { collegeParts } from './collegeTime.js'

/** «дд.мм.гггг» → Date (полночь UTC того числа — метка ДНЯ, без пояса) или null. */
export function parseRuDate(text) {
  const m = /^(\d{2})\.(\d{2})\.(\d{4})$/.exec(String(text || '').trim())
  if (!m) return null
  const [day, month, year] = [Number(m[1]), Number(m[2]), Number(m[3])]
  const d = new Date(Date.UTC(year, month - 1, day))
  //31.02 JavaScript молча превращает в 03.03 — такую «дату» не принимаем.
  if (d.getUTCFullYear() !== year || d.getUTCMonth() !== month - 1 || d.getUTCDate() !== day) return null
  return d
}

/** Дальше этого от сегодняшнего дня дата занятия почти наверняка опечатка в годе. */
export const FAR_DATE_DAYS = 60

/**
 * Что не так с датой занятия:
 *   ''       — годится (пустая дата разрешена: экзамен без назначенного дня);
 *   'format' — это не дата вида дд.мм.гггг (запрещаем);
 *   'far'    — дата настоящая, но далеко от сегодня (переспрашиваем).
 */
export function lessonDateIssue(text, today = new Date()) {
  const raw = String(text || '').trim()
  if (!raw) return ''
  const d = parseRuDate(raw)
  if (!d) return 'format'
  //«Сегодня» — число КОЛЛЕДЖА (Улан-Удэ), а не устройства (utils/collegeTime.js).
  const p = collegeParts(today)
  const days = Math.abs(Math.round((d - Date.UTC(p.year, p.month - 1, p.day)) / 86400000))
  return days > FAR_DATE_DAYS ? 'far' : ''
}

/** Сколько отметок (оценок и пропусков) стоит в занятии, включая пересдачи. */
export function lessonMarkCount(lessonId, students) {
  const keys = [lessonId, `${lessonId}_retake`]
  for (let n = 2; n <= 5; n++) keys.push(`${lessonId}_retake_${n}`)
  let count = 0
  for (const s of students || []) {
    for (const k of keys) if ((s.grades || {})[k]) count += 1
  }
  return count
}

/**
 * Занятие с тем же типом и номером в той же подгруппе (кроме самого `exceptId`), или null.
 * Сверяем подгруппу: при раздельном обучении «Практика №1» у каждой подгруппы своя.
 */
export function duplicateLesson(lessons, { type, number, subgroup = 0, exceptId = '' }) {
  const n = Number(number)
  if (!type || !Number.isFinite(n)) return null
  return (lessons || []).find((l) => l.id !== exceptId && l.type === type
    && Number(l.number) === n && Number(l.subgroup || 0) === Number(subgroup || 0)) || null
}

/** Номер занятия: целое от 1 до 999. Всё остальное — опечатка. */
export function lessonNumberOk(value) {
  const n = Number(value)
  return Number.isInteger(n) && n >= 1 && n <= 999
}
