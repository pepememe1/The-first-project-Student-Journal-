<script setup>
// App — корень: только <RouterView>. Регистрируем обработчик «сессия истекла»
// (его дёргает axios-клиент, когда refresh не удался) → уводим на экран входа.
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { setAuthExpiredHandler } from '@/api/client'
import { setOfflineExpiredHandler, startOfflineWatch } from '@/api/offlineSession'
import { flushOutbox, startOutboxWatch } from '@/api/outbox'
import { useAuthStore } from '@/stores/auth'
import ToastHost from '@/components/ui/ToastHost.vue'
import ConfirmDialog from '@/components/ui/ConfirmDialog.vue'
import { useToast } from '@/composables/useToast'

const router = useRouter()
const auth = useAuthStore()
const toast = useToast()

function toLogin() {
  auth.clearSession()
  if (router.currentRoute.value.path !== '/login') router.push('/login')
}

onMounted(() => {
  setAuthExpiredHandler(toLogin)

  // Сутки без единого ответа сервера — локальные данные стираем и просим войти
  // заново (см. offlineSession.js о том, зачем это нужно). Очередь неотправленных
  // оценок при этом остаётся: работа преподавателя не должна пропадать из-за того,
  // что он сутки был вне сети.
  setOfflineExpiredHandler(() => {
    toast.error('Работа без сети больше суток — войдите заново')
    toLogin()
  })
  startOfflineWatch()

  // Как только связь вернулась — отправляем накопленное. Не по таймеру: пока сети
  // нет, попытки только жгут батарею.
  startOutboxWatch()
  // И одна попытка на старте: приложение могли закрыть офлайн, а открыть уже в сети,
  // и перехода «офлайн -> онлайн» в этом запуске не случится вовсе.
  if (auth.isAuthenticated) flushOutbox().catch(() => {})
})
</script>

<template>
  <RouterView />
  <ToastHost />
  <ConfirmDialog />
</template>
