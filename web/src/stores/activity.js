/**
 * stores/activity.js — текущая активность беседы (docs/PLAN-ACTIVITIES.md).
 *
 * Состояние живёт в Pinia, а не в компоненте, по одной причине: свёрнутая активность
 * превращается в плавающее окно, которое следует за человеком по вкладкам. Держи его в
 * компоненте страницы — и переход в «Расписание» убил бы идущую викторину.
 *
 * Кадры состояния приходят по WebSocket мессенджера (отдельного канала нет), приём от
 * участника идёт по HTTP.
 */
import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import { activitiesApi } from '@/api/endpoints'
import { acceptsFrame, mergeFrame } from '@/utils/frameOrder'

export const useActivityStore = defineStore('activity', () => {
  const activity = ref(null)        // {id, kind, host_id, is_host, status, params, ...}
  const state = ref({})             // payload последнего принятого кадра
  const seq = ref(-1)               // номер последнего принятого кадра
  const mode = ref('hidden')        // hidden | full | mini
  const launcherFor = ref('')       // id беседы, для которой открыт выбор категории
  const loading = ref(false)
  const error = ref('')

  const isRunning = computed(() => activity.value?.status === 'running')
  const isHost = computed(() => !!activity.value?.is_host)
  const kind = computed(() => activity.value?.kind || '')

  /**
   * Принять кадр состояния.
   *
   * Само правило — в `utils/frameOrder.js`: чистой функцией без импортов, чтобы его
   * можно было проверить тестом. Стор тянет алиас `@/api/endpoints`, который `node
   * --test` не разрешает, и проверка правила «по месту» была бы копией — то есть
   * зелёной при сломанном сторе.
   */
  function applyFrame(frame) {
    if (!frame || !activity.value) return false
    if (frame.activity_id && frame.activity_id !== activity.value.id) return false
    if (!acceptsFrame(seq.value, frame.seq)) return false
    seq.value = Number(frame.seq)
    state.value = mergeFrame(state.value, frame.payload)
    return true
  }

  /** Событие «в беседе запустили активность» — для тех, кто её ещё не видит. */
  async function onStarted(ev, conversationId) {
    if (!ev || ev.conversation_id !== conversationId) return
    await load(conversationId)
    if (mode.value === 'hidden') mode.value = 'mini'
  }

  function onFinished(ev) {
    if (!activity.value || ev?.activity_id !== activity.value.id) return
    activity.value = { ...activity.value, status: 'finished' }
    if (ev.summary) state.value = { ...state.value, summary: ev.summary }
  }

  async function load(conversationId) {
    if (!conversationId) return
    loading.value = true
    try {
      const { data } = await activitiesApi.current(conversationId)
      _adopt(data.activity)
    } catch { /* беседа без активности — не ошибка */ }
    finally { loading.value = false }
  }

  function _adopt(a) {
    if (!a) { reset(); return }
    activity.value = a
    state.value = a.state?.payload || {}
    seq.value = Number(a.state?.seq ?? -1)
  }

  async function start(conversationId, kindName, params = {}, title = '') {
    error.value = ''
    loading.value = true
    try {
      const { data } = await activitiesApi.start(conversationId, kindName, params, title)
      _adopt(data)
      mode.value = 'full'
      launcherFor.value = ''
      return true
    } catch (e) {
      error.value = e?.response?.data?.detail || 'Не удалось запустить активность'
      return false
    } finally { loading.value = false }
  }

  async function finish(save = false) {
    if (!activity.value) return
    try {
      const { data } = await activitiesApi.finish(activity.value.id, save)
      activity.value = { ...activity.value, status: 'finished' }
      state.value = { ...state.value, summary: data.summary || {} }
    } catch (e) {
      error.value = e?.response?.data?.detail || 'Не удалось завершить активность'
    }
  }

  /** Открыть уже идущую активность по нажатию карточки в ленте. */
  async function open(activityId) {
    loading.value = true
    try {
      const { data } = await activitiesApi.get(activityId)
      _adopt(data)
      mode.value = 'full'
    } catch (e) {
      error.value = e?.response?.data?.detail || 'Активность недоступна'
    } finally { loading.value = false }
  }

  function openLauncher(conversationId) { launcherFor.value = conversationId }
  function closeLauncher() { launcherFor.value = '' }
  function minimize() { mode.value = 'mini' }
  function expand() { mode.value = 'full' }
  function hide() { mode.value = 'hidden' }

  /**
   * ⚠️ Обязателен при выходе из аккаунта. Активность живёт ВНЕ страницы и переживает
   * смену пользователя в той же вкладке (SPA не перезагружается) — без сброса следующий
   * вошедший увидел бы чужую викторину поверх своего кабинета. Ровно та же граница, по
   * которой уже сбрасываются сторы мессенджера, Вектора и профиля.
   */
  function reset() {
    activity.value = null
    state.value = {}
    seq.value = -1
    mode.value = 'hidden'
    launcherFor.value = ''
    error.value = ''
  }

  return {
    activity, state, seq, mode, launcherFor, loading, error,
    isRunning, isHost, kind,
    applyFrame, onStarted, onFinished, load, start, finish, open,
    openLauncher, closeLauncher, minimize, expand, hide, reset,
  }
})
