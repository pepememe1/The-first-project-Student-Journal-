// translate.js — перевод сообщений мессенджера.
//
// ⚠️ ПЕРЕВОД ИСХОДЯЩИХ ДЕЛАЕТСЯ ЗДЕСЬ, НА КЛИЕНТЕ, А НЕ НА СЕРВЕРЕ ПРИ ОТПРАВКЕ.
// Разница принципиальная: человек обязан УВИДЕТЬ, что именно уйдёт собеседнику. Если бы
// сервер молча подменял текст в момент отправки, отправитель до конца жизни сообщения
// не знал бы, что там написано — а исправить уже нельзя, оно ушло.
//
// ⚠️ ПРИВАТНОСТЬ. Текст уходит той ИИ-модели, которую подключил администратор. Если это
// GigaChat — личная переписка покидает сервер колледжа. Поэтому по умолчанию всё
// выключено, входящие переводятся ПО КНОПКЕ, а автоперевод человек включает сам. При
// подключённой Ollama текст вообще никуда не уходит (тот же принцип, что у распознавания
// речи). Интерфейс говорит об этом прямо — см. TranslateDialog.vue.
//
// Настройки живут в prefs АККАУНТА, а не в localStorage: человек заходит и с телефона, и
// с компьютера, и заново выставлять пару языков на каждом устройстве — это ровно та
// мелочь, из-за которой функцией перестают пользоваться.
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { meApi, messengerApi } from '@/api/endpoints'

export const AUTO = 'auto'

export const useTranslateStore = defineStore('translate', () => {
  // Языки приходят с сервера — своей копии не держим, иначе однажды покажем язык,
  // которого сервер не знает.
  const languages = ref([])
  const prefs = ref({
    incoming_from: AUTO, incoming_to: 'ru',
    outgoing_from: AUTO, outgoing_to: 'en',
    auto: false,
  })
  const loaded = ref(false)
  const busy = ref(false)
  const error = ref('')
  // Переводы входящих: id сообщения → { text, shown }. Держим в памяти вкладки —
  // перевод это способ ПРОЧИТАТЬ реплику, а не её новая версия, и в базу он не едет.
  const done = ref({})

  const enabled = computed(() => !!prefs.value.auto)

  async function load() {
    if (loaded.value) return
    loaded.value = true
    try {
      const [{ data: langs }, { data: p }] = await Promise.all([
        messengerApi.translateLanguages(), meApi.getPrefs(),
      ])
      languages.value = langs.languages || []
      if (p?.prefs?.translate) prefs.value = { ...prefs.value, ...p.prefs.translate }
    } catch { /* переводчик — дополнение: без него чат работает как обычно */ }
  }

  async function save(next) {
    prefs.value = { ...prefs.value, ...next }
    try {
      await meApi.setPrefs({ translate: { ...prefs.value } })
    } catch (e) {
      error.value = e?.response?.data?.detail || 'Не удалось сохранить настройки перевода'
    }
  }

  /**
   * Перевести произвольный текст. Возвращает строку или '' при неудаче.
   * Причину неудачи кладём в error — молча вернуть исходный текст нельзя: человек
   * решит, что перевод сделан, и что собеседник написал именно это.
   */
  async function translate(text, to, from = AUTO) {
    error.value = ''
    if (!text?.trim()) return ''
    busy.value = true
    try {
      const { data } = await messengerApi.translate(text, to, from)
      if (!data.ok) {
        error.value = data.reason || 'Не удалось перевести'
        return ''
      }
      return data.text
    } catch (e) {
      error.value = e?.response?.data?.detail || 'Переводчик не ответил'
      return ''
    } finally {
      busy.value = false
    }
  }

  /** Перевести ВХОДЯЩЕЕ сообщение и запомнить результат (повторный клик — скрыть). */
  async function toggleMessage(id, text) {
    const have = done.value[id]
    if (have) {
      done.value = { ...done.value, [id]: { ...have, shown: !have.shown } }
      return
    }
    const out = await translate(text, prefs.value.incoming_to, prefs.value.incoming_from)
    if (out) done.value = { ...done.value, [id]: { text: out, shown: true } }
  }

  function shownFor(id) {
    const row = done.value[id]
    return row?.shown ? row.text : ''
  }

  /**
   * Перевод СВОЕГО текста перед отправкой. Возвращает переведённое или исходное —
   * здесь фолбэк на оригинал уместен и даже обязателен: иначе сбой переводчика съел бы
   * сообщение, которое человек уже написал и нажал «отправить».
   */
  async function outgoing(text) {
    if (!prefs.value.auto) return text
    const out = await translate(text, prefs.value.outgoing_to, prefs.value.outgoing_from)
    return out || text
  }

  return { languages, prefs, busy, error, enabled, done,
           load, save, translate, toggleMessage, shownFor, outgoing }
})
