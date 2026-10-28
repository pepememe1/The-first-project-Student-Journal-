// Тексты словарей для сторожей, которые читают их как текст (28.10.2026: словари разложены
// по файлам ru.js, en.js, zh.js — src/i18n/dictionaries.js). Один помощник вместо того,
// чтобы каждый тест знал раскладку сам и молча проверял пустоту после следующего переезда.
import { readFileSync } from 'node:fs'

const I18N = new URL('../src/i18n/', import.meta.url)

export const LANGS = ['ru', 'en', 'zh']

export function dictText(lang) {
  return readFileSync(new URL(`${lang}.js`, I18N), 'utf8')
}

/** Все три словаря подряд — для проверок «ключ есть во всех языках». */
export function allDictText() {
  return LANGS.map(dictText).join('\n')
}

export function dictKeys(lang) {
  return new Set([...dictText(lang).matchAll(/'([\w.]+)':/g)].map((m) => m[1]))
}

export function localesText() {
  return readFileSync(new URL('locales.js', I18N), 'utf8')
}

export const DICT_FILES = [...LANGS.map((l) => `i18n/${l}.js`), 'i18n/locales.js', 'i18n/dictionaries.js']
