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
