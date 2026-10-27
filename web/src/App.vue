<script setup>
// App — корень: только <RouterView>. Регистрируем обработчик «сессия истекла»
// (его дёргает axios-клиент, когда refresh не удался) → уводим на экран входа.
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { setAuthExpiredHandler, setMfaSetupHandler } from '@/api/client'
import { setOfflineExpiredHandler, startOfflineWatch } from '@/api/offlineSession'
import { flushOutbox, startOutboxWatch } from '@/api/outbox'
import { initDurableOutbox } from '@/services/durableOutbox'
import { useAuthStore } from '@/stores/auth'
import ToastHost from '@/components/ui/ToastHost.vue'
import ForceUpdate from '@/components/ui/ForceUpdate.vue'
import ConfirmDialog from '@/components/ui/ConfirmDialog.vue'
import { useToast } from '@/composables/useToast'
import { rememberResume } from '@/utils/sessionResume'

const router = useRouter()
const auth = useAuthStore()
const toast = useToast()

/**
 * Сессия кончилась не по воле человека — ведём на вход и ОБЪЯСНЯЕМ почему.
 *
 * 🔥 Раньше форма входа появлялась без единого слова, а после входа открывалась
 * главная (13.10.2026). Преподаватель, ставивший оценки, видел это как «журнал меня
 * выкинул и всё пропало». Теперь на форме стоит причина (`auth.notice`), а после входа
 * ТОТ ЖЕ человек возвращается на ту же страницу (`utils/sessionResume.js`).
 * ⚠️ Адрес запоминаем ДО `clearSession()`: после неё логина уже нет, и отличить
 * «тот же человек» от «следующий за общим компьютером» было бы нечем.
 */
function toLogin(reason = 'expired') {
  const at = router.currentRoute.value
  //Объяснять «почему вы на форме входа» есть смысл тому, кто был в системе. Без входа
  //401 получает любой запрос (регистрация пуш-токена на старте после выхода), и плашка
  //«время работы вышло» стояла у человека, который вышел сам (23.10.2026).
  const hadUser = !!auth.user
  if (!at.meta?.public) rememberResume(auth.user?.login, at.fullPath)
  auth.clearSession()
  auth.setNotice(hadUser ? reason : '')
  if (at.path !== '/login') router.push('/login')
}

onMounted(() => {
  setAuthExpiredHandler(() => toLogin('expired'))

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
  //Причину показывает сама форма входа и держит её, пока человек не войдёт: всплывающее
  //сообщение гасло через шесть секунд — раньше, чем его успевали прочитать.
  setOfflineExpiredHandler(() => toLogin('offline'))
  startOfflineWatch()

  // Как только связь вернулась — отправляем накопленное. Не по таймеру: пока сети
  // нет, попытки только жгут батарею.
  startOutboxWatch()
  // И одна попытка на старте: приложение могли закрыть офлайн, а открыть уже в сети,
  // и перехода «офлайн -> онлайн» в этом запуске не случится вовсе.
  // ⚠️ Сначала — надёжное зеркало очереди (W-13в): если ОС освободила localStorage,
  // неотправленные оценки вернутся из него раньше, чем выгрузка решит, что слать нечего.
  initDurableOutbox()
    .catch(() => {})
    .finally(() => { if (auth.isAuthenticated) flushOutbox().catch(() => {}) })
})
</script>

<template>
  <RouterView />
  <ToastHost />
  <ForceUpdate />
  <ConfirmDialog />
</template>
