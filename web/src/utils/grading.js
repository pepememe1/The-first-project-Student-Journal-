// grading.js — JS-порт кастомных шкал оценок (grading.py::SCALES, §ролей 3.3.1).
//
// Каждый преподаватель выбирает СВОЮ шкалу ввода/просмотра (User.prefs.grading_scale).
// "5" — умолчание, ведёт себя как раньше. Средний балл/итоговая — ВСЕГДА в переводе на
// 5-балльную (считает сервер), здесь — только конвертация для клиентского отображения
// (форма ввода, подсветка). Закреплено контрактом docs/contracts/grade-cases.json —
// парные тесты Python (tests/test_grade_contract.py) и JS (web/tests/grades.contract.test.mjs).

import { isFailed as isFailedBase } from './grades.js'
import { useLocaleStore } from '../stores/locale.js'

export const DEFAULT_SCALE = '5'

function leadNum(raw) {
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

export function scaleLabel(scale = DEFAULT_SCALE) {
  return (SCALES[scale] || SCALES[DEFAULT_SCALE]).label
}
