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
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { LOCALES, DEFAULT_LOCALE, MESSAGES } from '@/i18n/dictionaries'

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

  // Какой словарь реально применяется. Выключен перевод или неизвестный код — русский.
  const active = computed(() => {
    if (!translateUi.value) return DEFAULT_LOCALE
    return MESSAGES[locale.value] ? locale.value : DEFAULT_LOCALE
  })
  const current = computed(() =>
    LOCALES.find((l) => l.code === locale.value) || LOCALES[0])

  /**
   * Перевод по ключу. Нет ключа в выбранном языке → РУССКИЙ, а не ключ и не пустота:
   * «login.submit» вместо кнопки выглядит сломанным, русская надпись — просто
   * непереведённое место, и человек всё равно поймёт, куда нажимать.
   */
  function t(key, fallback = '') {
    const dict = MESSAGES[active.value] || {}
    return dict[key] || MESSAGES[DEFAULT_LOCALE][key] || fallback || key
  }

  function apply() {
    //lang в <html> — не украшение: по нему браузер выбирает перенос строк и шрифт для
    //иероглифов, а скринридер — произношение.
    try { document.documentElement.setAttribute('lang', active.value) } catch { /* SSR */ }
  }

  function set(code, { push = true } = {}) {
    if (!MESSAGES[code]) return
    locale.value = code
    translateUi.value = true      //явный выбор языка включает перевод обратно
    try {
      localStorage.setItem(LS_LOCALE, code)
      localStorage.setItem(LS_ENABLED, '1')
    } catch { /* приватный режим — переживём, останется на эту сессию */ }
    apply()
    if (push) pushToAccount()
  }

  function setTranslateUi(on) {
    translateUi.value = !!on
    try { localStorage.setItem(LS_ENABLED, on ? '1' : '0') } catch { /* см. выше */ }
    apply()
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
      if (code && MESSAGES[code]) {
        locale.value = code
        try { localStorage.setItem(LS_LOCALE, code) } catch { /* см. выше */ }
      }
      if (typeof data?.prefs?.locale_on === 'boolean') {
        translateUi.value = data.prefs.locale_on
        try { localStorage.setItem(LS_ENABLED, data.prefs.locale_on ? '1' : '0') } catch { /* см. выше */ }
      }
      apply()
    } catch { /* нет сети — работаем с локальным выбором */ }
  }

  apply()
  return { locale, translateUi, active, current, locales: LOCALES,
           t, set, setTranslateUi, loadFromAccount }
})
