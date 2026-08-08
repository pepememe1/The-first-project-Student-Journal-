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
import { registerToken, unregisterToken } from '@/services/push'
import { clear as clearScheduleWidget, refreshFromServer as refreshWidgetSchedule }
  from '@/services/scheduleWidget'
import { loginWithPasskey } from '@/api/webauthn'
import { useMessengerStore } from '@/stores/messenger'
import { useVectorStore } from '@/stores/vector'
import { useProfileStore } from '@/stores/profile'

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
      refreshWidgetSchedule(data.role).catch(() => {})
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
    useMessengerStore().reset()   // и переписку в памяти — тем же соображением
    useVectorStore().reset()      // и диалог с Вектором: он тоже жил в памяти store
    useProfileStore().reset()     // и профиль (аватар/«о себе»/цвет/шрифт) — та же причина
    // Виджет на рабочем столе Android живёт ВНЕ страницы и переживает выход: без этой
    // строки он продолжал бы показывать группу предыдущего владельца сессии тому, кто
    // войдёт следом (на телефоне в колледже это норма, а не редкость).
    clearScheduleWidget()
    user.value = null
  }

  // Локальная очистка сессии без обращения к серверу (напр. при протухшем refresh).
  function clearSession() {
    clearTokens()
    localStorage.removeItem(LS_USER)
    clearCache()
    useMessengerStore().reset()
    useVectorStore().reset()
    useProfileStore().reset()
    clearScheduleWidget()
    user.value = null
  }

  return { user, loading, error, isAuthenticated, role, login, loginPasskey, logout, clearSession }
})
