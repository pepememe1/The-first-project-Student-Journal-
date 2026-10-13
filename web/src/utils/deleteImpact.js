/**
 * deleteImpact.js — что показать в окне удаления: какие числа и нужен ли набор названия.
 *
 * Зачем (13.10.2026, живой обход стенда). Окна «Удалить группу К74/1?» и «Удалить
 * студента …?» не говорили о последствиях ничего, хотя за группой стояли девять студентов
 * и сотни отметок. Числа считает сервер (`GET /web/admin/delete-impact`), а здесь —
 * правила показа, вынесенные из компонента, чтобы их проверял тест.
 *
 * ⚠️ Нулевые строки не показываем: «Отметок: 0, родителей: 0» — шум, за которым не видно
 * единственной важной цифры.
 */

/** Какие числа и в каком порядке показывать для каждого вида объекта. */
export const IMPACT_FIELDS = {
  group: ['students', 'lessons', 'marks', 'teachers'],
  subject: ['groups', 'lessons', 'marks'],
  student: ['marks', 'finals', 'parents'],
  teacher: ['subjects', 'journals', 'curated'],
}

/** Ненулевые числа по порядку: `[{ field, n }]`. Неизвестный вид — пусто. */
export function impactRows(kind, counts) {
  const fields = IMPACT_FIELDS[kind] || []
  return fields
    .map((field) => ({ field, n: Number((counts || {})[field] || 0) }))
    .filter((row) => row.n > 0)
}

/**
 * Требовать ли набрать название, прежде чем удалять.
 *
 * Только у группы, за которой стоят люди или отметки: это единственное удаление, которое
 * одним нажатием убирает из журналов сразу многих. Остальным хватает окна с числами —
 * если набирать название на каждое удаление, его начнут набирать не читая.
 */
export function needsTyping(kind, counts) {
  if (kind !== 'group' || !counts) return false
  return Number(counts.students || 0) > 0 || Number(counts.marks || 0) > 0
}

/** Набранное совпадает с названием (регистр и пробелы по краям не важны). */
export function typedMatches(typed, required) {
  const norm = (s) => String(s || '').trim().toLowerCase()
  return norm(required) !== '' && norm(typed) === norm(required)
}
