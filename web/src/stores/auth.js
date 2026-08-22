/**
 * auth.js — стор авторизации (порт идей desktop sync_client login + saved_session).
 *
 * Как в десктопе: пароль НЕ храним. Персистентный вход — по сохранённым JWT
 * (access + refresh) и «визитке» пользователя (login/role/name), пришедшей в ответе
 * логина. Роль определяет доступные разделы (guard в router).
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { authApi } from '@/api/endpoints'
import { getAccess, setTokens, clearTokens } from '@/api/tokens'
import { clearCache } from '@/api/offlineCache'
import { clearDrafts } from '@/utils/drafts'
import { resetOfflineSession } from '@/api/offlineSession'
import { flushOutbox, reloadOutbox } from '@/api/outbox'
import { registerToken, unregisterToken } from '@/services/push'
import { clear as clearScheduleWidget, refreshFromServer as refreshWidgetSchedule,
  saveEndpoint as saveWidgetEndpoint } from '@/services/scheduleWidget'
import { loginWithPasskey } from '@/api/webauthn'
import { useMessengerStore } from '@/stores/messenger'
import { useVectorStore } from '@/stores/vector'
import { useProfileStore } from '@/stores/profile'
import { useActivityStore } from '@/stores/activity'

const LS_USER = 'gb.user'

function loadUser() {
  try {
    const raw = localStorage.getItem(LS_USER)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

export const useAuthStore = defineStore('auth', () => {
  const user = ref(loadUser())
  const loading = ref(false)
  const error = ref('')

  const isAuthenticated = computed(() => !!user.value && !!getAccess())
  const role = computed(() => user.value?.role || null)

  async function login(login, password) {
    loading.value = true
    error.value = ''
    try {
      const { data } = await authApi.login(login.trim(), password)
      setTokens({ access: data.access_token, refresh: data.refresh_token })
      user.value = { login: login.trim(), role: data.role, name: data.name || login.trim() }
      localStorage.setItem(LS_USER, JSON.stringify(user.value))
      // Привязываем телефон к ЭТОМУ аккаунту: на одном устройстве могли входить
      // разные люди, и уведомления должны идти последнему вошедшему.
      registerToken()
      // Язык интерфейса аккаунта. Человек мог выбрать его на ДРУГОМ устройстве, и
      // заставлять выставлять заново — ровно та мелочь, из-за которой настройкой
      // перестают пользоваться. Локальный выбор при этом не теряется: если на сервере
      // языка нет, остаётся тот, что выбран на экране входа (см. stores/locale.js).
      import('@/stores/locale')
        .then(({ useLocaleStore }) => useLocaleStore().loadFromAccount())
        .catch(() => { /* язык — не условие входа */ })
      // Виджет расписания на рабочем столе Android наполняем ИМЕННО ЗДЕСЬ, а не на
      // странице «Расписание»: туда человек может не заходить неделями, а виджет всё
      // это время показывал бы данные с прошлого захода. Вход — единственный момент,
      // который случается гарантированно и однозначно определяет, ЧЬЁ расписание брать.
      // Ошибку глотаем: виджет — дополнение, из-за него вход падать не должен.
      // Адрес сервера — ОБЯЗАТЕЛЬНО рядом со снимком: без него нативная часть не знает,
      // куда ходить, и виджет живёт ровно тем, что положили при входе. Человек может не
      // открывать приложение неделями, а расписание за это время правят — и виджет
      // уверенно показывает не то. Зашить адрес в нативный код нельзя: сервер задаётся
      // в рантайме (свой сервер колледжа), и зашитый указывал бы не туда.
      saveWidgetEndpoint()
      refreshWidgetSchedule(data.role).catch(() => {})
      // Очередь оценок принадлежит логину и пережила выход из аккаунта. Перечитываем
      // её под нового вошедшего и сразу пробуем отправить: сеть только что была —
      // вход по ней и произошёл, лучшего момента не будет.
      reloadOutbox()
      flushOutbox().catch(() => {})
      return user.value
    } catch (e) {
      const status = e.response?.status
      if (status === 401) error.value = 'Неверный логин или пароль'
      else if (status === 403) error.value = e.response?.data?.detail || 'Устройство не подтверждено администратором'
      else if (status === 429) error.value = e.response?.data?.detail || 'Слишком много попыток входа. Подождите.'
      else error.value = 'Не удалось войти. Проверьте соединение с сервером.'
      throw e
    } finally {
      loading.value = false
    }
  }

  // Вход по passkey (Face ID / отпечаток) — без пароля. Токены и «визитку» ставим так
  // же, как при обычном входе; логин приходит в ответе (клиент его не вводил).
  async function loginPasskey() {
    loading.value = true
    error.value = ''
    try {
      const data = await loginWithPasskey('')
      setTokens({ access: data.access_token, refresh: data.refresh_token })
      user.value = { login: data.login || '', role: data.role, name: data.name || data.login || '' }
      localStorage.setItem(LS_USER, JSON.stringify(user.value))
      // ⚠️ То же, что и в парольном входе, — и раньше этого здесь НЕ БЫЛО: у того, кто
      // заходит по биометрии, виджет не наполнялся вовсе и молча оставался пустым.
      // Вход есть вход, каким бы способом он ни произошёл.
      saveWidgetEndpoint()
      refreshWidgetSchedule(data.role).catch(() => {})
      // Очередь оценок принадлежит логину и пережила выход из аккаунта. Перечитываем
      // её под нового вошедшего и сразу пробуем отправить: сеть только что была —
      // вход по ней и произошёл, лучшего момента не будет.
      reloadOutbox()
      flushOutbox().catch(() => {})
      return user.value
    } catch (e) {
      // Отмена пользователем (NotAllowedError/AbortError) — не ошибка, пробрасываем молча.
      if (e?.name === 'NotAllowedError' || e?.name === 'AbortError') throw e
      error.value = e.response?.data?.detail || 'Не удалось войти по биометрии. Войдите паролем.'
      throw e
    } finally {
      loading.value = false
    }
  }

  async function logout() {
    // Отписываем устройство ДО гашения токена: после clearTokens запрос уже не пройдёт,
    // и бывший владелец телефона продолжал бы получать чужие уведомления.
    await unregisterToken()
    // Гасим токен и на сервере (чёрный список), а не только локально — безопасный выход.
    try { await authApi.logout() } catch { /* офлайн — всё равно чистим локально */ }
    clearTokens()
    localStorage.removeItem(LS_USER)
    clearCache()   // стираем оффлайн-кэш — чтобы данные не показались другому юзеру
    // ⚠️ И НЕДОПИСАННЫЕ сообщения. Раньше эта строка отсутствовала, а карта черновиков
    // ключевалась только id беседы — то есть следующий вошедший на этом телефоне видел
    // чужой текст в поле ввода общего канала. Ключ теперь с логином (utils/drafts.js),
    // но уборка всё равно обязательна: выход — это момент, когда устройство меняет
    // владельца. Держит web/tests/drafts.test.mjs.
    clearDrafts()
    useMessengerStore().reset()   // и переписку в памяти — тем же соображением
    useVectorStore().reset()      // и диалог с Вектором: он тоже жил в памяти store
    useProfileStore().reset()     // и профиль (аватар/«о себе»/цвет/шрифт) — та же причина
    // Активность живёт ВНЕ страницы (плавающее окно поверх RouterView) и переживает смену
    // пользователя в той же вкладке: без сброса следующий вошедший увидел бы чужую
    // викторину поверх своего кабинета.
    useActivityStore().reset()
    // Виджет на рабочем столе Android живёт ВНЕ страницы и переживает выход: без этой
    // строки он продолжал бы показывать группу предыдущего владельца сессии тому, кто
    // войдёт следом (на телефоне в колледже это норма, а не редкость).
    clearScheduleWidget()
    // Отсчёт суточного окна офлайна начинаем с нуля: оно принадлежит сессии, а не
    // устройству. Иначе следующий вошедший унаследовал бы чужой почти истёкший счётчик
    // и получил бы «войдите заново» через десять минут после входа.
    // ⚠️ Очередь неотправленных оценок (outbox) при этом НЕ трогаем — она привязана к
    // логину автора и обязана пережить выход: иначе преподаватель, вышедший из
    // аккаунта до появления сети, потеряет всё, что выставил.
    resetOfflineSession()
    user.value = null
  }

  // Локальная очистка сессии без обращения к серверу (напр. при протухшем refresh).
  function clearSession() {
    clearTokens()
    localStorage.removeItem(LS_USER)
    clearCache()
    clearDrafts()      //та же причина, что в logout — см. комментарий выше
    useMessengerStore().reset()
    useVectorStore().reset()
    useProfileStore().reset()
    useActivityStore().reset()
    clearScheduleWidget()
    // Отсчёт суточного окна офлайна начинаем с нуля: оно принадлежит сессии, а не
    // устройству. Иначе следующий вошедший унаследовал бы чужой почти истёкший счётчик
    // и получил бы «войдите заново» через десять минут после входа.
    // ⚠️ Очередь неотправленных оценок (outbox) при этом НЕ трогаем — она привязана к
    // логину автора и обязана пережить выход: иначе преподаватель, вышедший из
    // аккаунта до появления сети, потеряет всё, что выставил.
    resetOfflineSession()
    user.value = null
  }

  return { user, loading, error, isAuthenticated, role, login, loginPasskey, logout, clearSession }
})
