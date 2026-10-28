// locale.js — язык интерфейса (русский / English / 中文).
//
// ━━ ГДЕ ХРАНИТСЯ И ПОЧЕМУ В ДВУХ МЕСТАХ ━━
// Выбор делается на экране ВХОДА, то есть когда аккаунта ещё нет и писать в prefs некуда.
// Поэтому источник правды — localStorage: он работает до входа и сразу. А после входа тот
// же выбор уезжает в prefs аккаунта, чтобы человек, севший за другой компьютер, не
// выставлял язык заново. При следующем входе выигрывает серверное значение — оно новее
// по смыслу («я выбрал это для себя», а не «так стояло на этой машине»).
//
// ⚠️ ЯЗЫК ОБЯЗАН ПЕРЕЖИТЬ ВХОД. Ровно этого просил заказчик, и это же самое хрупкое
// место: вход перезагружает страницу и переписывает localStorage (см. desktop bootstrap),
// поэтому ключ языка НЕ ТРОГАЕТСЯ ни при входе, ни при выходе — только явным выбором.
//
// ━━ ВЫКЛЮЧАТЕЛЬ ━━
// `translateUi=false` возвращает интерфейс к русскому, не стирая выбранный язык: человек
// может выключить перевод и потом включить обратно, не выбирая язык заново.
//
// ━━ СЛОВАРИ ГРУЗЯТСЯ ПО ЯЗЫКУ (28.10.2026) ━━
// Русский — в основном бандле: он нужен всегда как запасной текст. Английский и китайский —
// отдельными кусками, только тому, кто их выбрал: раньше все три ехали каждому одним
// куском в 563 КБ. Пока выбранный словарь грузится, строки берутся из русского; main.js
// ждёт `ready` перед монтированием, чтобы русский не мелькнул в первом кадре.
import { defineStore } from 'pinia'
import { ref, computed, shallowReactive } from 'vue'
import { LOCALES, DEFAULT_LOCALE } from '../i18n/locales.js'
import ru from '../i18n/ru.js'
import { pickPlural } from '../utils/plural.js'

const LOADERS = {
  en: () => import('../i18n/en.js'),
  zh: () => import('../i18n/zh.js'),
}
const KNOWN = new Set(LOCALES.map((l) => l.code))

const LS_LOCALE = 'gb.locale'
const LS_ENABLED = 'gb.locale_on'

function read(key, fallback) {
  try {
    const v = localStorage.getItem(key)
    return v === null ? fallback : v
  } catch { return fallback }
}

export const useLocaleStore = defineStore('locale', () => {
  const locale = ref(read(LS_LOCALE, DEFAULT_LOCALE))
  const translateUi = ref(read(LS_ENABLED, '1') !== '0')
  //Загруженные словари; t() читает отсюда, поэтому догрузка сама перерисует интерфейс.
  const loaded = shallowReactive({ [DEFAULT_LOCALE]: ru })

  // Какой словарь реально применяется. Выключен перевод или неизвестный код — русский.
  const active = computed(() => {
    if (!translateUi.value) return DEFAULT_LOCALE
    return KNOWN.has(locale.value) ? locale.value : DEFAULT_LOCALE
  })

  /** Догрузить словарь языка. Не загрузился (нет сети в браузере) — остаётся русский. */
  async function ensure(code) {
    if (loaded[code] || !LOADERS[code]) return
    try {
      loaded[code] = (await LOADERS[code]()).default
    } catch (e) {
      console.warn(`[locale] словарь ${code} не загрузился — показываю русский`, e)
    }
  }
  const current = computed(() =>
    LOCALES.find((l) => l.code === locale.value) || LOCALES[0])

  /**
   * Перевод по ключу. Нет ключа в выбранном языке → РУССКИЙ, а не ключ и не пустота:
   * «login.submit» вместо кнопки выглядит сломанным, русская надпись — просто
   * непереведённое место, и человек всё равно поймёт, куда нажимать.
   *
   * Второй аргумент — либо строка-fallback (старое поведение, обратная
   * совместимость), либо объект плейсхолдеров для строк вида «Сессия {week}
   * ({first}–{last})» — подстановка делается ПОСЛЕ выбора языка, поэтому значения
   * (числа, уже переведённые слова) не зависят от порядка слов в конкретном языке.
   */
  function t(key, paramsOrFallback = '') {
    const params = paramsOrFallback && typeof paramsOrFallback === 'object'
      ? paramsOrFallback : null
    const fallback = params ? '' : paramsOrFallback
    const dict = loaded[active.value] || {}
    let s = dict[key] || ru[key] || fallback || key
    //Форма слова по числу «{n} подписчик|…|…» — по правилам ТОГО языка, из которого
    //строка взята (нет перевода — русская строка и русские правила).
    if (params && 'n' in params) {
      s = pickPlural(s, params.n, dict[key] ? active.value : DEFAULT_LOCALE)
    }
    if (params) {
      for (const [k, v] of Object.entries(params)) s = s.replaceAll(`{${k}}`, v)
    }
    return s
  }

  function apply() {
    //lang в <html> — не украшение: по нему браузер выбирает перенос строк и шрифт для
    //иероглифов, а скринридер — произношение.
    try { document.documentElement.setAttribute('lang', active.value) } catch { /* SSR */ }
  }

  function set(code, { push = true } = {}) {
    if (!KNOWN.has(code)) return
    locale.value = code
    translateUi.value = true      //явный выбор языка включает перевод обратно
    try {
      localStorage.setItem(LS_LOCALE, code)
      localStorage.setItem(LS_ENABLED, '1')
    } catch { /* приватный режим — переживём, останется на эту сессию */ }
    apply()
    ensure(code)
    if (push) pushToAccount()
  }

  function setTranslateUi(on) {
    translateUi.value = !!on
    try { localStorage.setItem(LS_ENABLED, on ? '1' : '0') } catch { /* см. выше */ }
    apply()
    ensure(active.value)
    pushToAccount()
  }

  /** Сохранить выбор в аккаунт. Молча: до входа сохранять некуда, и это не ошибка. */
  async function pushToAccount() {
    try {
      const { meApi } = await import('@/api/endpoints')
      await meApi.setPrefs({ locale: locale.value, locale_on: translateUi.value })
    } catch { /* не вошли или нет сети — останется локальный выбор */ }
  }

  /** Подтянуть язык аккаунта после входа (серверное значение выигрывает). */
  async function loadFromAccount() {
    try {
      const { meApi } = await import('@/api/endpoints')
      const { data } = await meApi.getPrefs()
      const code = data?.prefs?.locale
      if (code && KNOWN.has(code)) {
        locale.value = code
        try { localStorage.setItem(LS_LOCALE, code) } catch { /* см. выше */ }
      }
      if (typeof data?.prefs?.locale_on === 'boolean') {
        translateUi.value = data.prefs.locale_on
        try { localStorage.setItem(LS_ENABLED, data.prefs.locale_on ? '1' : '0') } catch { /* см. выше */ }
      }
      apply()
      await ensure(active.value)
    } catch { /* нет сети — работаем с локальным выбором */ }
  }

  apply()
  const ready = ensure(active.value)
  return { locale, translateUi, active, current, locales: LOCALES, ready,
           t, set, setTranslateUi, loadFromAccount }
})
