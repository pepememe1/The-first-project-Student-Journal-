// markTone.js — цвет среднего балла, одна лесенка на интерфейс (аудит 28.10.2026).
//
// Отметку по среднему считает markOfAverage (зеркало grading.mark_of_average), здесь только
// её цвет. Раньше лесенка «4.5 / 3.5 / 3» жила копиями в журнале преподавателя, у куратора,
// в статистике студента и в кольце среднего, с hex-цветами мимо токенов темы.
import { markOfAverage } from './grading.js'

const TONE_BY_MARK = { 5: 'accent', 4: 'blue', 3: 'orange', 2: 'red' }

/** 'accent' | 'blue' | 'orange' | 'red' | 'none' (оценок нет). */
export function markTone(avg) {
  return TONE_BY_MARK[markOfAverage(avg)] || 'none'
}

/** Класс текста для среднего: журнал, куратор. */
export function markTextClass(avg) {
  return { accent: 'text-accent', blue: 'text-blue', orange: 'text-orange', red: 'text-red', none: 'text-text3' }[markTone(avg)]
}

/** Цвет заливки для среднего: полоски и кольцо в статистике. */
export function markColor(avg) {
  return { accent: 'var(--gb-accent)', blue: 'var(--gb-blue)', orange: 'var(--gb-orange)', red: 'var(--gb-red)', none: 'var(--gb-border2)' }[markTone(avg)]
}
