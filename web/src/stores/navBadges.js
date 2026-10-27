// navBadges.js — счётчик непрочитанных уведомлений для значков меню (23.10.2026).
//
// Раньше его опрашивало само боковое меню. На телефоне оно смонтировано, только пока
// открыта шторка, поэтому значок там не обновлялся вовсе. Теперь опрос ведёт оболочка
// (`AppShell.vue`, пока человек в кабинете), а меню и нижняя панель только читают.
// Непрочитанные сообщения считает `messenger.totalUnread`: у них свой опрос.
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { meApi } from '@/api/endpoints'

const POLL_MS = 60000

export const useNavBadgesStore = defineStore('navBadges', () => {
  const notifyUnread = ref(0)
  let timer = null
  let onVisible = null

  async function refresh() {
    try { notifyUnread.value = (await meApi.unreadCount()).data?.count || 0 }
    catch { /* нет связи — значок просто не обновится */ }
  }

  function start() {
    if (timer) return
    refresh()
    timer = setInterval(() => { if (!document.hidden) refresh() }, POLL_MS)
    onVisible = () => { if (!document.hidden) refresh() }
    document.addEventListener('visibilitychange', onVisible)
  }

  function stop() {
    if (timer) { clearInterval(timer); timer = null }
    if (onVisible) { document.removeEventListener('visibilitychange', onVisible); onVisible = null }
  }

  //Выход — смена владельца устройства: чужое число не показываем ни мгновения.
  function reset() {
    stop()
    notifyUnread.value = 0
  }

  return { notifyUnread, refresh, start, stop, reset }
})
