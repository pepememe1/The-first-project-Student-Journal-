<script setup>
// App — корень: только <RouterView>. Регистрируем обработчик «сессия истекла»
// (его дёргает axios-клиент, когда refresh не удался) → уводим на экран входа.
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { setAuthExpiredHandler, setMfaSetupHandler } from '@/api/client'
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

  // Администратору нужен второй фактор: сервер закрыл ВСЁ, кроме его настройки.
  // Ведём человека прямо туда и объясняем причину, вместо россыпи «нет прав» на
  // исправных страницах. Сообщение показываем ОДИН раз: закрытых запросов на
  // странице бывает десяток, и десять одинаковых плашек — это шум, а не помощь.
  let mfaNoticeShown = false
  setMfaSetupHandler((detail) => {
    if (mfaNoticeShown) return
    mfaNoticeShown = true
    toast.error(detail || 'Настройте второй фактор входа — без него разделы закрыты')
    //⚠️ Путь настроек ВЛОЖЕН под роль (`/admin/settings`), голого `/settings`
    //не существует — переход по нему улетел бы в обработчик промаха по адресу.
    const target = `/${auth.user?.role || 'admin'}/settings`
    if (router.currentRoute.value.path !== target) router.push(target)
    //Разрешаем показать снова через минуту: человек мог уйти со страницы и
    //вернуться, и вечное молчание было бы хуже повтора.
    setTimeout(() => { mfaNoticeShown = false }, 60000)
  })

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
