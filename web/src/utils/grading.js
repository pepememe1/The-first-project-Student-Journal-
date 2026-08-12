// grading.js — JS-порт кастомных шкал оценок (grading.py::SCALES, §ролей 3.3.1).
//
// Каждый преподаватель выбирает СВОЮ шкалу ввода/просмотра (User.prefs.grading_scale).
// "5" — умолчание, ведёт себя как раньше. Средний балл/итоговая — ВСЕГДА в переводе на
// 5-балльную (считает сервер), здесь — только конвертация для клиентского отображения
// (форма ввода, подсветка). Закреплено контрактом docs/contracts/grade-cases.json —
// парные тесты Python (tests/test_grade_contract.py) и JS (web/tests/grades.contract.test.mjs).

import { isFailed as isFailedBase, attemptKey } from './grades.js'
import { useLocaleStore } from '../stores/locale.js'

export const DEFAULT_SCALE = '5'

// Типы занятий, оценка за которые идёт в средний балл наравне с практикой.
// Точный порт grading.PRACTICE_TYPES — «ДЗ» добавлено в 3.1, набор живёт в ОДНОМ месте
// (как и в Python), чтобы список типов не разъехался между сервером и офлайн-подсчётом.
export const PRACTICE_TYPES = ['Практика', 'ДЗ']

/** Оценивается ли занятие «как практика» (2–5, идёт в средний балл). Порт grading.is_practice. */
export function isPractice(lessonType) {
  return PRACTICE_TYPES.includes(lessonType)
}

/** Числовая оценка из строки вида '4 (Зачтено)' → 4.0; иначе null. Порт grading.lead_num. */
export function leadNum(raw) {
  const v = (raw || '').trim()
  if (!v) return null
  const head = v.split(/\s+/)[0]
  return ['2', '3', '4', '5'].includes(head) ? Number(head) : null
}

function toFive100(raw) {
  const v = (raw || '').trim()
  if (!v) return null
  const head = v.split(/\s+/)[0]
  const n = Number(head)
  if (!Number.isFinite(n) || head === '') return null
  if (n < 0 || n > 100) return null
  if (n >= 90) return 5.0
  if (n >= 75) return 4.0
  if (n >= 60) return 3.0
  return 2.0
}

function isFailed100(raw) {
  const v = toFive100(raw)
  return v !== null && v <= 2.0
}

const LETTER_TO_FIVE = { A: 5.0, B: 4.0, C: 3.0, D: 2.0, F: 2.0 }

function toFiveLetter(raw) {
  const v = (raw || '').trim()
  if (!v) return null
  const head = v.split(/\s+/)[0].toUpperCase()
  return head in LETTER_TO_FIVE ? LETTER_TO_FIVE[head] : null
}

function isFailedLetter(raw) {
  const v = (raw || '').trim()
  if (!v) return false
  const head = v.split(/\s+/)[0].toUpperCase()
  return head === 'D' || head === 'F'
}

function toFivePassFail() {
  return null // никогда не входит в числовой средний
}

function isFailedPassFail(raw) {
  const v = (raw || '').trim().toLowerCase()
  return v.startsWith('не') || v.startsWith('незач')
}

// ⚠️ `label` — ГЕТТЕР (переводится под текущий язык интерфейса), `values` — НЕТ: это
// буквальные значения оценок, которые преподаватель ВВОДИТ и которые хранятся в БД
// («Зачтено»/«Не зачтено» — контракт с `isFailedPassFail`, сравнивающим ровно эти
// русские строки). Перевод пользовательского ВВОДА — совсем другая, куда более рискованная
// задача (пришлось бы менять, что физически печатает преподаватель), и не входит в задачу
// перевода интерфейса.
export const SCALES = {
  '5': { get label() { return useLocaleStore().t('grading.scale5', '5-балльная') },
    values: ['2', '3', '4', '5'], toFive: leadNum, isFailed: isFailedBase },
  '100': { get label() { return useLocaleStore().t('grading.scale100', '100-балльная') },
    values: Array.from({ length: 101 }, (_, i) => String(i)), toFive: toFive100, isFailed: isFailed100 },
  letter: { get label() { return useLocaleStore().t('grading.scaleLetter', 'Буквенная (A–F)') },
    values: ['A', 'B', 'C', 'D', 'F'], toFive: toFiveLetter, isFailed: isFailedLetter },
  pass_fail: { get label() { return useLocaleStore().t('grading.scalePassFail', 'Зачёт / незачёт') },
    values: ['Зачтено', 'Не зачтено'], toFive: toFivePassFail, isFailed: isFailedPassFail },
}

export function scaleValues(scale = DEFAULT_SCALE) {
  return (SCALES[scale] || SCALES[DEFAULT_SCALE]).values
}

export function toFivePoint(raw, scale = DEFAULT_SCALE) {
  return (SCALES[scale] || SCALES[DEFAULT_SCALE]).toFive(raw)
}

export function isFailedScaled(raw, scale = DEFAULT_SCALE) {
  return (SCALES[scale] || SCALES[DEFAULT_SCALE]).isFailed(raw)
}

// ── Средний балл — офлайн-порт grading.practice_average (задача: расчёт на телефоне ──
// без сети, тем же контрактом, что и у сервера/десктопа). НЕ вторая формула: каждая
// ветка построчно повторяет grading.py, парность закреплена docs/contracts/grade-cases.json.

/** Дефолты методики: те же значения, что в grading.DEFAULTS (Н=2.0, экзамены не входят). */
const AVG_DEFAULTS = { avg_absence_weight: 2.0, avg_count_absence: true, avg_include_exam: false }

/** Параметры методики из config с дефолтами. Порт grading.avg_config. */
export function avgConfig(cfg) {
  const c = cfg || {}
  const out = { ...AVG_DEFAULTS }
  for (const k of Object.keys(AVG_DEFAULTS)) {
    if (c[k] !== undefined && c[k] !== null) out[k] = c[k]
  }
  const w = Number(out.avg_absence_weight)
  out.avg_absence_weight = Number.isFinite(w) ? w : 2.0
  out.avg_count_absence = Boolean(out.avg_count_absence)
  out.avg_include_exam = Boolean(out.avg_include_exam)
  return out
}

/**
 * Последняя попытка по экзамену с учётом пересдач: база → id_retake → id_retake_2 → ...
 * Возвращает «сырую» строку оценки. Порт grading.latest_exam_value.
 */
export function latestExamValue(lessonId, records) {
  let val = records[lessonId] || ''
  let i = 1
  for (;;) {
    const key = attemptKey(lessonId, i)
    if (records[key]) {
      val = records[key]
      i += 1
    } else {
      break
    }
  }
  return val
}

/**
 * Средний балл — точный порт grading.practice_average.
 * @param {Array<[string,string]>} items — пары [lessonId, lessonType].
 * @param {Record<string,string>} records — {lessonId|ключ_попытки: оценка}.
 * @param {object|null} cfg — методика (avg_absence_weight/avg_count_absence/avg_include_exam).
 * @param {string|Record<string,string>} scale — шкала ("5"/"100"/"letter"/"pass_fail") ЛИБО
 *   словарь {lessonId: scale} — нужен, когда items смешивает занятия разных преподавателей
 *   с разными шкалами (общий средний по всем предметам).
 * @returns {number} средний балл, округлённый до 2 знаков; 0, если считать нечего.
 */
export function practiceAverage(items, records, cfg = null, scale = DEFAULT_SCALE) {
  const c = avgConfig(cfg)
  let total = 0
  let count = 0
  const scaleIsMap = scale !== null && typeof scale === 'object'
  for (const [lid, ltype] of items) {
    if (isPractice(ltype)) {
      const v = records[lid]
      const lscale = scaleIsMap ? (scale[lid] !== undefined ? scale[lid] : DEFAULT_SCALE) : scale
      const num = v ? toFivePoint(v, lscale) : null
      if (num !== null && num !== undefined) {
        total += num
        count += 1
      } else if (v === 'Н' && c.avg_count_absence) {
        total += c.avg_absence_weight
        count += 1
      }
    } else if (ltype === 'Экзамен' && c.avg_include_exam) {
      const v = latestExamValue(lid, records)
      const num = v ? leadNum(v) : null
      if (num !== null && num !== undefined) {
        total += num
        count += 1
      }
    }
  }
  return count ? roundHalfEven(total / count, 2) : 0.0
}

/**
 * Округление ДО ДВУХ ЗНАКОВ ПО ПРАВИЛАМ PYTHON, а не по правилам JavaScript.
 *
 * 🔥 Это не педантизм, а настоящее расхождение на обычных данных. `round()` в Python
 * при точной середине округляет К ЧЁТНОМУ, а `Math.round` в JavaScript — всегда вверх:
 *
 *     29 / 8 = 3.625   ->   Python 3.62,   Math.round 3.63
 *
 * Восемь практик за семестр с суммой 29 (например 4,4,4,4,4,3,3,3) — рядовой журнал, а
 * не выдуманный край. Разойдись мы здесь, телефон показывал бы 3.63 там, где сервер и
 * десктоп показывают 3.62, и спорить с этим было бы нечем: обе цифры «правильные».
 * Ровно та болезнь, ради избежания которой расчёт и держат в одном месте.
 *
 * ⚠️ Просто сравнить остаток с 0.5 нельзя: 2.675 хранится в double как
 * 2.674999999999999822…, и для Python это НЕ середина — он честно даёт 2.67. Поэтому
 * смотрим на ТОЧНОЕ десятичное разложение числа (`toFixed(20)` даёт его с запасом для
 * наших величин), а не на результат умножения на 100, которое само вносит погрешность.
 */
export function roundHalfEven(x, digits = 2) {
  if (!Number.isFinite(x)) return x
  const sign = x < 0 ? -1 : 1
  const [int, frac = ''] = Math.abs(x).toFixed(20).split('.')
  const keep = frac.slice(0, digits)
  const rest = frac.slice(digits)
  let n = BigInt(int + keep)

  const half = '5' + '0'.repeat(Math.max(0, rest.length - 1))
  if (rest > half) n += 1n                       // строки равной длины сравнимы посимвольно
  else if (rest === half && n % 2n === 1n) n += 1n   // ровно середина -> к чётному

  return sign * Number(n) / 10 ** digits
}
