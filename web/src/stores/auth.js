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
      const { loginWithPasskey } = await import('@/api/webauthn')
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
    // Гасим токен и на сервере (чёрный список), а не только локально — безопасный выход.
    try { await authApi.logout() } catch { /* офлайн — всё равно чистим локально */ }
    clearTokens()
    localStorage.removeItem(LS_USER)
    user.value = null
  }

  // Локальная очистка сессии без обращения к серверу (напр. при протухшем refresh).
  function clearSession() {
    clearTokens()
    localStorage.removeItem(LS_USER)
    user.value = null
  }

  return { user, loading, error, isAuthenticated, role, login, loginPasskey, logout, clearSession }
})
