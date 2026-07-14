// grades.js — общая fail-логика оценок (JS-порт grading.is_failed из Python).
//
// Раньше правило «завалена ли оценка» дублировалось инлайном в TeacherJournal.vue,
// десктопе и сервере — при правке одной версии другие молча отставали. Теперь единый
// код на Python (grading.is_failed) и здесь (isFailed), закреплённый общим контрактом
// docs/contracts/grade-cases.json: парные тесты (pytest + vitest) не дадут разойтись.
// МЕНЯТЬ правило только вместе с контрактом.

/**
 * Завалена ли оценка (нужна пересдача): непусто И (начинается с «2» или «Н») ЛИБО
 * содержит «Не зачтено». Точный порт grading.is_failed.
 * @param {string} v
 * @returns {boolean}
 */
export function isFailed(v) {
  v = (v || '').trim()
  return !!v && (v.startsWith('2') || v.startsWith('Н') || v.includes('Не зачтено'))
}

/**
 * Ключ записи попытки №ri по экзамену: 0 → id, 1 → id_retake, 2+ → id_retake_N.
 * Порт grading.attempt_key.
 * @param {string} lessonId
 * @param {number} ri
 * @returns {string}
 */
export function attemptKey(lessonId, ri) {
  if (ri <= 0) return lessonId
  return lessonId + (ri === 1 ? '_retake' : `_retake_${ri}`)
}

/**
 * Нужна ли пересдача №ri: за эту попытку уже есть оценка ЛИБО предыдущая завалена.
 * Порт grading.needs_retake. records — {ключ_попытки: оценка}.
 * @param {Record<string,string>} records
 * @param {string} lessonId
 * @param {number} ri
 * @returns {boolean}
 */
export function needsRetake(records, lessonId, ri) {
  if (records[attemptKey(lessonId, ri)]) return true
  return isFailed(records[attemptKey(lessonId, ri - 1)])
}
