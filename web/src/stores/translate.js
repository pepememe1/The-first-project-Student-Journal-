// translate.js — перевод сообщений мессенджера.
//
// ⚠️ ПЕРЕВОД ИСХОДЯЩИХ ДЕЛАЕТСЯ ЗДЕСЬ, НА КЛИЕНТЕ, А НЕ НА СЕРВЕРЕ ПРИ ОТПРАВКЕ.
// Разница принципиальная: человек обязан УВИДЕТЬ, что именно уйдёт собеседнику. Если бы
// сервер молча подменял текст в момент отправки, отправитель до конца жизни сообщения
// не знал бы, что там написано — а исправить уже нельзя, оно ушло.
//
// ⚠️ ПРИВАТНОСТЬ — ЗДЕСЬ БЫЛА УСТАРЕВШАЯ НЕПРАВДА, ИСПРАВЛЕНО 02.09.2026. Стояло: «текст
// уходит той ИИ-модели, которую подключил администратор; если это GigaChat — личная
// переписка покидает сервер колледжа». С 29.08.2026 это неверно: `deep-translator`
// (HTTP-клиент к форме translate.google.com) удалён ЦЕЛИКОМ, переводит офлайновый Argos
// на нашей же машине, и никакая LLM в переводе не участвует вовсе. Текст переписки
// сервер колледжа не покидает.
//
// Ошибка была не косметической в обе стороны: пользователю обещали утечку, которой нет,
// а разработчику — маршрут данных, которого больше не существует. Тот же класс, что уже
// ловили трижды: докстринг описывал несуществующий модуль и по нему делали выводы.
//
// По умолчанию всё равно всё выключено, а входящие переводятся ПО КНОПКЕ — но теперь
// причина другая и честная: перевод предметной лексики у Argos плохой («две пары по
// математике» → «two couples in math»), и включать его молча за человека нельзя.
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
  // Доступен ли переводчик НА СЕРВЕРЕ. Решает сервер, клиент только показывает — тот же
  // принцип, что у распознавания речи. Без этого диалог предлагал включить автоперевод
  // на сервере, где переводчика нет вовсе: тумблер включался, а сообщения уходили
  // непереведёнными, и понять причину было нечем.
  const status = ref({ available: true, installed: true, pairs: [], reason: '' })
  // Переводы входящих: id сообщения → { text, shown }. Держим в памяти вкладки —
  // перевод это способ ПРОЧИТАТЬ реплику, а не её новая версия, и в базу он не едет.
  const done = ref({})

  const enabled = computed(() => !!prefs.value.auto)

  async function load() {
    if (loaded.value) return
    loaded.value = true
    try {
      const [{ data: langs }, { data: p }, st] = await Promise.all([
        messengerApi.translateLanguages(), meApi.getPrefs(),
        // Статус — отдельным запросом и БЕЗ падения всей загрузки: старый сервер этой
        // ручки не знает, и на нём диалог обязан работать как раньше, а не пустеть.
        messengerApi.translateStatus().catch(() => null),
      ])
      languages.value = langs.languages || []
      if (p?.prefs?.translate) prefs.value = { ...prefs.value, ...p.prefs.translate }
      if (st?.data) status.value = st.data
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

  return { languages, prefs, busy, error, enabled, done, status,
           load, save, translate, toggleMessage, shownFor, outgoing }
})
