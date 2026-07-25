<script setup>
// MessengerPage — вкладка «Сообщения». Трёхколоночный каркас в стиле Telegram:
//   A — навигация (поиск + вкладки + список чатов/каталог)  [ChatList]
//   B — карточка собеседника СЛЕВА от чата (портфолио)       [ProfilePanel]  (виден с xl)
//   C — переписка СПРАВА (лента + композер)                  [ChatThread]
// Транспорт Фазы 2 — опрос (store.startPolling); WebSocket добавим отдельной фазой.
import { onMounted, onBeforeUnmount } from 'vue'
import { useMessengerStore } from '@/stores/messenger'
import ChatList from '@/components/messenger/ChatList.vue'
import ProfilePanel from '@/components/messenger/ProfilePanel.vue'
import ChatThread from '@/components/messenger/ChatThread.vue'

const m = useMessengerStore()

// В embed (десктоп-веб-view) шапка и заголовок SPA скрыты, поэтому вычитать их высоту
// (calc(100dvh-8rem)) нельзя — иначе снизу остаётся пустая полоса. Тогда тянемся на всю
// высоту родителя (AppShell в embed даёт контенту h-full).
const embed = (() => {
  try {
    return new URLSearchParams(location.search).get('embed') === '1'
      || localStorage.getItem('gb.embed') === '1'
  } catch { return false }
})()

onMounted(() => { m.loadChats(); m.startPolling() })
onBeforeUnmount(() => { m.stopPolling() })
</script>

<template>
  <div class="flex overflow-hidden rounded-lg border border-border bg-card shadow-card"
       :class="embed ? 'h-full' : 'h-[calc(100dvh-8rem)] sm:h-[calc(100dvh-9.5rem)] lg:h-[calc(100vh-11rem)]'">
    <ChatList />
    <ProfilePanel />
    <ChatThread />
  </div>
</template>
