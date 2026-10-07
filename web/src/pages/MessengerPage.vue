<script setup>
// MessengerPage — вкладка «Сообщения». Трёхколоночный каркас в стиле Telegram:
//   A — навигация (поиск + вкладки + список чатов/каталог)  [ChatList]
//   B — карточка собеседника СЛЕВА от чата (портфолио)       [ProfilePanel]  (виден с xl)
//   C — переписка СПРАВА (лента + композер)                  [ChatThread]
// Транспорт Фазы 2 — опрос (store.startPolling); WebSocket добавим отдельной фазой.
import { onMounted, onBeforeUnmount, watch, shallowRef } from 'vue'
import { useRoute } from 'vue-router'
import { useEasterStore } from '@/stores/easterEggs'
import { useMessengerStore } from '@/stores/messenger'
import { useLocaleStore } from '@/stores/locale'
import { useToast } from '@/composables/useToast'
import { linkAction } from '@/utils/deepLinks'
import { reloadOnceForChunk } from '@/utils/appVersion'
import ChatList from '@/components/messenger/ChatList.vue'
import ProfilePanel from '@/components/messenger/ProfilePanel.vue'
import ChatThread from '@/components/messenger/ChatThread.vue'
import { useTrackerStore } from '@/stores/tracker'

const m = useMessengerStore()
const tracker = useTrackerStore()
const locale = useLocaleStore()
const toast = useToast()

// ⚡ ОКНО ТРЕКЕРА — ОТДЕЛЬНЫМ ЧАНКОМ (06.10.2026). Трекер включён в немногих беседах, а
// его экраны (доска, список, сроки, сводка, окна задачи и работы) весили пятую часть
// страницы сообщений — и грузились каждому, кто просто открыл чат. Теперь код приезжает
// при первом открытии окна; данные доски стор запрашивает в тот же миг, так что ждать
// дольше прежнего не приходится. В программе и в приложении чанк лежит на диске.
//
// 🔥 ЗАГРУЗКУ ВЕДЁМ САМИ, БЕЗ ГОТОВОЙ ОБЁРТКИ ЛЕНИВОГО КОМПОНЕНТА (живой прогон
// 07.10.2026). Чанк может не доехать, и причин две: нет связи — либо вкладка старше
// выкладки и файла с таким именем на сервере уже нет (жалоба «после деплоя нажал — и
// ничего», см. `utils/appVersion.js`). Браузер ПОМНИТ неудачную загрузку модуля до
// перезагрузки страницы: повторный `import()` в том же документе отклоняется сразу, без
// похода в сеть (замерено: три попытки — один запрос). Обёртка Vue вдобавок запоминает
// отказ у себя: окно не открылось бы уже никогда, а `tracker.open` оставалось бы истиной
// — кнопка переставала отвечать вовсе. Поэтому отказ здесь закрывает трекер и идёт той
// же дорогой, что недоехавшая страница: одна перезагрузка на вкладку, а если она уже
// была — человеку сказано, что делать.
const TrackerOverlay = shallowRef(null)
async function loadTrackerOverlay() {
  if (TrackerOverlay.value) return
  try {
    TrackerOverlay.value = (await import('@/components/tracker/TrackerOverlay.vue')).default
  } catch (e) {
    tracker.close()
    //`needLock`: трекер открывается и сам — по ссылке из письма (`?tracker=1`). Без
    //записанного замка перезагрузка по такой ссылке повторялась бы без конца.
    if (!reloadOnceForChunk(e, { needLock: true })) {
      toast.error(locale.t('tracker.codeFailed', 'Не удалось открыть трекер. Обновите страницу.'))
    }
  }
}
watch(() => tracker.open, (open) => { if (open) loadTrackerOverlay() }, { immediate: true })

// В embed (десктоп-веб-view) шапка и заголовок SPA скрыты, поэтому вычитать их высоту
// (calc(100dvh-8rem)) нельзя — иначе снизу остаётся пустая полоса. Тогда тянемся на всю
// высоту родителя (AppShell в embed даёт контенту h-full).
const embed = (() => {
  try {
    return new URLSearchParams(location.search).get('embed') === '1'
      || localStorage.getItem('gb.embed') === '1'
  } catch { return false }
})()

// Ссылка на сообщение (`?chat=…&msg=…`) — пункт «Копировать ссылку на сообщение» в меню
// по выделению. Открываем беседу и просим ленту перемотаться к строке.
//
// ⚠️ Ссылка ОТНОСИТЕЛЬНАЯ и ведёт внутрь кабинета: беседа всё равно откроется только
// участнику, а неучастнику сервер ответит 403. То есть ссылка — удобство навигации, а
// не способ поделиться перепиской.
//
// ⚠️ Сначала СПИСОК чатов, потом переход: `openById` берёт из него заголовок, чтобы шапка
// не мигнула пустой. Отказ загрузки списка переходу не мешает.
const route = useRoute()
// Ссылка на ЧЕЛОВЕКА (`?peer=<id>`, «Поделиться контактом», F-18) — открыть или завести
// личный чат с ним. Права проверяет сервер (`openDirect`): ссылка — навигация, а не пропуск.
async function openFromQuery() {
  const act = linkAction(route.query)
  if (act?.kind === 'chat') {
    await m.openById(act.id, act.msg)
    openTrackerFromQuery()
    return
  }
  if (act?.kind === 'peer') return m.openWith({ id: act.id })
}
// Ссылка из письма «Вам дали задание» (`?chat=…&tracker=1&work=…&task=…`): беседа открыта —
// показываем трекер и саму задачу. Права проверит сервер: неучастнику трекер не откроется
// так же, как не открылась бы беседа.
// ⚠️ Запрос читается ЗДЕСЬ, а не до `await` выше: пока беседа открывалась, человек мог уйти
// по другой ссылке, и трекер прежней поверх новой страницы был бы уже не к месту.
function openTrackerFromQuery() {
  const act = linkAction(route.query)
  if (act?.kind !== 'chat' || !route.query.tracker) return
  tracker.openFor(act.id, {
    projectId: String(route.query.work || ''), taskId: String(route.query.task || ''),
  })
}
onMounted(async () => {
  await m.loadChats().catch(() => {})
  m.startPolling()
  openFromQuery()
})
//Ссылку открыли, уже находясь в сообщениях: страница не пересоздаётся, меняется запрос.
watch(() => [route.query.chat, route.query.peer], () => { openFromQuery() })
//Письмо о ДРУГОЙ задаче той же беседы: меняется только задача. Беседа уже открыта —
//переоткрывать её незачем (лента мигнула бы и перемоталась), сразу показываем трекер.
//Сменилась и беседа — этим занят наблюдатель выше: он откроет трекер, когда она готова.
watch(() => [route.query.chat, route.query.tracker, route.query.work, route.query.task],
  (now, was) => { if (now[0] === was[0]) openTrackerFromQuery() })
// Ушли со страницы сообщений — трекер закрываем: он живёт поверх беседы, а не сам по себе.
onBeforeUnmount(() => { m.stopPolling(); tracker.close() })
// Hotline Miami при входе во вкладку «Сообщения». Бросок серверный, как и везде.
const easter = useEasterStore()
onMounted(() => easter.roll('hotline_miami'))

</script>

<template>
  <!-- Высота — от ОДНОЙ переменной оболочки (--gb-page-offset в style.css), а не от
       собственного набора чисел: свой набор устарел молча после перекомпоновки 3.5.6, и
       снизу осталась мёртвая полоса в полторы сотни пикселей.
       ⚠️ `gb-fullbleed` (3.7) действует ТОЛЬКО ниже sm и делает две вещи разом: убирает
       боковую рамку контейнера и пересчитывает высоту под свой, уже без отступов, хром
       (см. комментарий у класса в style.css). Классы Tailwind ниже он перебивает не
       «по случайности» — правило вне @layer всегда сильнее утилит внутри слоя. -->
  <div class="flex overflow-hidden rounded-lg border border-border bg-card shadow-card"
       :class="embed ? 'h-full' : 'gb-fullbleed h-[calc(100dvh-var(--gb-page-offset))]'">
    <ChatList />
    <ProfilePanel />
    <ChatThread />
    <!-- Трекер задач беседы — на весь экран, поверх страницы сообщений.
         ⚠️ ВНУТРИ корневого блока, а не рядом с ним (06.10.2026). Страницы живут в
         `<transition>` оболочки, а он умеет анимировать только ОДИН корневой элемент: со
         вторым корнем Vue пишет «non-element root node that cannot be animated» и молча
         отключает странице переход. Окно `fixed`, поэтому ни в раскладке строки, ни в
         обрезке по скруглению оно не участвует — так же, как окна внутри ChatThread. -->
    <TrackerOverlay v-if="tracker.open && TrackerOverlay" />
  </div>
</template>
