<script setup>
// ChatThread — правая колонка: переписка активной беседы (пузыри в стиле Telegram) +
// действия над сообщением (Фаза 3): оверлей по тапу, плашка закреплённого, режим
// выделения, ответ/пересылка/удаление(у себя|у всех)/жалоба. ⚙-чат модерации — Фаза 4.
import { ref, computed, watch, nextTick } from 'vue'
import { storeToRefs } from 'pinia'
import { Send, ArrowLeft, Pin, X, Reply as ReplyIcon, Forward, Trash2, Settings, Bell, BellOff } from '@lucide/vue'
import { useMessengerStore } from '@/stores/messenger'
import { useAuthStore } from '@/stores/auth'
import MessageActionsOverlay from './MessageActionsOverlay.vue'
import ReportDialog from './ReportDialog.vue'
import ForwardPicker from './ForwardPicker.vue'
import ConversationInfo from './ConversationInfo.vue'
import Avatar from '@/components/ui/Avatar.vue'
import { profilePlate } from '@/theme/palette'

const m = useMessengerStore()
const auth = useAuthStore()
const { activeId, activePeer, messages, sending, replyTo, pinned, selectionMode, selectedIds, isModeration, activeInfo, peerTyping, notice, activeChat } = storeToRefs(m)
// Админ САМ и есть модерация — кнопка «Написать модерации» ему не нужна (и сервер её закрыл).
const isAdmin = computed(() => auth.role === 'admin')
// Замьючена ли текущая беседа у меня (без пушей). Кнопка-колокольчик — в шапке.
const muted = computed(() => !!activeChat.value?.muted)

// Тип беседы и права (для шапки/композера групп и каналов).
const kind = computed(() => activeInfo.value?.kind || 'direct')
const isGroupOrChannel = computed(() => kind.value === 'group' || kind.value === 'channel')
const canPost = computed(() => {
  if (kind.value !== 'channel') return true
  return ['owner', 'admin', 'writer'].includes(activeInfo.value?.my_role)
})

const draft = ref('')
const scroller = ref(null)
const composer = ref(null)

// Оверлей действий, модалки.
const overlay = ref({ open: false, message: null, x: 0, y: 0 })
const reportMsg = ref(null)                 // сообщение, на которое жалуемся
const forwardState = ref({ open: false, ids: [] })
const deleteTargets = ref(null)             // [message,…] для выбора «у себя/у всех» (все свои)
const copied = ref(false)
const showInfo = ref(false)                 // панель «О беседе» (участники/владелец)
// Все ли видимые сообщения уже выделены — для кнопки «Выбрать всё / Снять всё».
const allSelected = computed(() => messages.value.length > 0 && selectedIds.value.length === messages.value.length)

async function scrollDown() {
  await nextTick()
  scroller.value?.scrollTo({ top: scroller.value.scrollHeight })
}
watch(() => messages.value.length, scrollDown)
watch(activeId, scrollDown)

function fmtTime(iso) {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
}
function quoted(id) {
  const src = messages.value.find(x => x.id === id)
  return src ? (src.deleted ? 'Сообщение удалено' : src.body) : ''
}

// ── Жесты над сообщением (как в Telegram) ────────────────────────────────────────────
// ПК: меню действий — по ПРАВОЙ кнопке (ЛКМ ничего не открывает, чтобы не мешать выделению
// текста). Мобилка: по ДОЛГОМУ нажатию; свайп вправо по сообщению — быстрый ответ.
const LONG_PRESS_MS = 450     // сколько держать палец до появления меню
const SWIPE_REPLY_PX = 60     // насколько сдвинуть сообщение, чтобы сработал ответ
const swipe = ref({ id: 0, dx: 0 })   // визуальный сдвиг пузыря во время свайпа

let pressTimer = null
let touchStart = null         // {x, y, msg} — начало касания
let touchMoved = false        // был ли жест (тогда не считаем его тапом)

function openMenu(msg, x, y) {
  if (selectionMode.value) return
  overlay.value = { open: true, message: msg, x, y }
}

// ЛКМ: только отметка в режиме выделения (меню сюда больше не привязано).
function onMessageClick(msg) {
  if (selectionMode.value) m.toggleSelect(msg.id)
}

// ПКМ на ПК и долгое нажатие в мобильных браузерах (они шлют contextmenu сами).
function onContextMenu(msg, e) {
  e.preventDefault()
  openMenu(msg, e.clientX, e.clientY)
}

function onTouchStart(msg, e) {
  const t = e.touches?.[0]
  if (!t) return
  touchStart = { x: t.clientX, y: t.clientY, msg }
  touchMoved = false
  clearTimeout(pressTimer)
  // Свой таймер долгого нажатия — в WebView приложения contextmenu приходит не всегда.
  pressTimer = setTimeout(() => {
    if (!touchMoved && touchStart) openMenu(msg, touchStart.x, touchStart.y)
  }, LONG_PRESS_MS)
}

function onTouchMove(e) {
  const t = e.touches?.[0]
  if (!t || !touchStart) return
  const dx = t.clientX - touchStart.x
  const dy = t.clientY - touchStart.y
  if (Math.abs(dx) > 8 || Math.abs(dy) > 8) {
    touchMoved = true
    clearTimeout(pressTimer)
  }
  // Горизонтальный жест вправо — тянем пузырь за пальцем (вертикальную прокрутку не трогаем).
  if (Math.abs(dx) > Math.abs(dy) && dx > 0 && !touchStart.msg.deleted) {
    swipe.value = { id: touchStart.msg.id, dx: Math.min(dx, 90) }
  }
}

function onTouchEnd() {
  clearTimeout(pressTimer)
  const s = swipe.value
  const msg = touchStart?.msg
  swipe.value = { id: 0, dx: 0 }
  touchStart = null
  if (msg && s.id === msg.id && s.dx >= SWIPE_REPLY_PX && !msg.deleted) {
    m.setReply(msg)                       // свайп вправо = ответить
    nextTick(() => composer.value?.focus())
  }
}

async function onPick(action) {
  const msg = overlay.value.message
  if (!msg) return
  if (action === 'reply') { m.setReply(msg); await nextTick(); composer.value?.focus() }
  else if (action === 'pin') await m.setPinned(msg.id, true)
  else if (action === 'unpin') await m.setPinned(msg.id, false)
  else if (action === 'copy') { try { await navigator.clipboard.writeText(msg.body || '') ; flashCopied() } catch { /* нет доступа к буферу */ } }
  else if (action === 'forward') forwardState.value = { open: true, ids: [msg.id] }
  else if (action === 'select') m.enterSelection(msg.id)
  else if (action === 'delete') requestDelete([msg])
  else if (action === 'report') reportMsg.value = msg
}

function flashCopied() { copied.value = true; setTimeout(() => { copied.value = false }, 1200) }

// Удаление: если ВСЕ цели свои — предлагаем «у себя / у всех»; иначе (есть чужие) — только у себя.
function requestDelete(msgs) {
  if (msgs.length && msgs.every(x => x.mine)) { deleteTargets.value = msgs; return }
  msgs.forEach(x => m.removeMessage(x.id, 'self'))
  m.clearSelection()
}
async function applyDelete(scope) {
  const targets = deleteTargets.value || []
  deleteTargets.value = null
  for (const x of targets) await m.removeMessage(x.id, scope)
  m.clearSelection()
}

async function onReportSubmit(reason, description) {
  const msg = reportMsg.value
  reportMsg.value = null
  if (msg) await m.reportMessage(msg.id, reason, description)
}

async function onForwardSubmit(convIds) {
  const ids = forwardState.value.ids
  forwardState.value = { open: false, ids: [] }
  await m.forwardMessages(ids, convIds)
  m.clearSelection()
}

// Панель выделения.
const selectedMsgs = computed(() => messages.value.filter(x => selectedIds.value.includes(x.id)))
function bulkForward() {
  if (selectedIds.value.length) forwardState.value = { open: true, ids: [...selectedIds.value] }
}
function bulkDelete() { requestDelete(selectedMsgs.value) }

async function submit() {
  const t = draft.value.trim()
  if (!t) return
  draft.value = ''
  const ok = await m.send(t)
  if (!ok) draft.value = t          // сервер отклонил (анти-флуд/мьют) — вернуть текст
}
function onKey(e) { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit() } }

function jumpTo(id) {
  const el = document.getElementById(`gb-msg-${id}`)
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' })
}

const peerName = computed(() => {
  if (isModeration.value) return 'Модерация'
  if (isGroupOrChannel.value) return activeInfo.value?.title || activePeer.value?.full_name || 'Беседа'
  return activePeer.value?.full_name || 'Диалог'
})
const subtitle = computed(() => {
  if (isModeration.value) return 'Официальная поддержка'
  if (peerTyping.value) return 'печатает…'
  if (kind.value === 'channel') return `${activeInfo.value?.subscribers || 0} подписчиков`
  if (kind.value === 'group') return `${activeInfo.value?.subscribers || 0} участников`
  return activePeer.value?.online ? 'в сети' : 'был(а) недавно'
})
const topPinned = computed(() => pinned.value[0] || null)

// ── Оформление ленты (как в Telegram) ────────────────────────────────────────────────
// Свои сообщения — справа, чужие — слева с аватаркой и ФИО. Если человек пишет НЕСКОЛЬКО
// подряд, шапка (ава + имя) рисуется только у ВЕРХНЕГО сообщения пачки — лента не рябит.
const runStarts = computed(() => {
  const starts = new Set()
  let prev = null
  for (const msg of messages.value) {
    if (msg.sender_id !== prev) starts.add(msg.id)
    prev = msg.sender_id
  }
  return starts
})

// Аватарки отправителей: в группе/канале — из состава беседы, в личном чате — собеседника.
const avatarBySender = computed(() => {
  const map = {}
  for (const p of activeInfo.value?.participants || []) map[p.user_id] = p.avatar || ''
  return map
})
function senderAvatar(msg) {
  return avatarBySender.value[msg.sender_id] ?? (msg.mine ? '' : (activePeer.value?.avatar || ''))
}

// Шапка чата — в цвет плашки, которую собеседник выбрал в своём профиле.
const headerTint = computed(() =>
  (!isGroupOrChannel.value && !isModeration.value && activePeer.value?.profile_color)
    ? profilePlate(activePeer.value.profile_color) : '')
</script>

<template>
  <section class="flex min-w-0 flex-1 flex-col bg-bg" :class="{ 'hidden sm:flex': !activeId }">
    <div v-if="!activeId" class="grid flex-1 place-items-center p-6 text-center text-sm text-text3">
      Выберите чат слева или найдите человека через поиск.
    </div>

    <template v-else>
      <!-- Верхняя полоска / панель выделения -->
      <!-- Шапка — в цвет плашки собеседника (её выбирает он сам в профиле). -->
      <div v-if="!selectionMode" class="flex h-14 shrink-0 items-center gap-3 border-b border-border px-3"
           :class="headerTint ? '' : 'bg-card'" :style="headerTint ? { background: headerTint } : {}">
        <button type="button" @click="m.clearActive()" aria-label="Назад"
                class="grid size-8 place-items-center rounded-md hover:bg-black/10 sm:hidden"
                :class="headerTint ? 'text-white' : 'text-text2'">
          <ArrowLeft class="size-5" />
        </button>
        <!-- Клик по шапке — профиль собеседника / состав беседы (как в Telegram). -->
        <button type="button" @click="showInfo = true"
                class="min-w-0 flex-1 rounded-md px-1 py-0.5 text-left transition-colors"
                :class="headerTint ? 'hover:bg-white/10' : 'hover:bg-bg2'"
                title="Открыть профиль">
          <div class="truncate font-title text-base font-bold"
               :class="headerTint ? 'text-white' : 'text-text'">{{ peerName }}</div>
          <div class="text-xs" :class="headerTint ? 'text-white/75' : 'text-text3'">{{ subtitle }}</div>
        </button>
        <!-- 🔔 — мьют беседы у себя (без пушей). В чате модерации не показываем. -->
        <button v-if="!isModeration" type="button" @click="m.muteConversation(!muted)"
                :aria-label="muted ? 'Включить уведомления' : 'Отключить уведомления'"
                :title="muted ? 'Уведомления выключены' : 'Отключить уведомления'"
                class="grid size-8 shrink-0 place-items-center rounded-md"
                :class="headerTint ? 'text-white/80 hover:bg-white/15 hover:text-white'
                  : (muted ? 'text-accent hover:bg-bg2' : 'text-text3 hover:bg-bg2 hover:text-text')">
          <BellOff v-if="muted" class="size-5" />
          <Bell v-else class="size-5" />
        </button>
        <!-- ⚙ — открыть чат с модерацией (см. MESSENGER-PLAN.md §6) -->
        <button v-if="!isModeration && !isAdmin" type="button" @click="m.openModeration()"
                aria-label="Модерация" title="Написать модерации"
                class="grid size-8 shrink-0 place-items-center rounded-md"
                :class="headerTint ? 'text-white/80 hover:bg-white/15 hover:text-white'
                  : 'text-text3 hover:bg-bg2 hover:text-text'">
          <Settings class="size-5" />
        </button>
      </div>
      <div v-else class="flex h-14 shrink-0 items-center gap-3 border-b border-border bg-card px-3">
        <button type="button" @click="m.clearSelection()" aria-label="Отмена"
                class="grid size-8 place-items-center rounded-md text-text2 hover:bg-bg2"><X class="size-5" /></button>
        <span class="flex-1 text-sm font-semibold text-text">Выбрано: {{ selectedIds.length }}</span>
        <!-- «Выбрать всё / Снять всё» — иначе выделять пачку приходилось по одному. -->
        <button type="button" @click="allSelected ? m.selectNone() : m.selectAll()"
                class="shrink-0 rounded-md border border-border2 px-2.5 py-1.5 text-xs text-text2 hover:bg-bg2">
          {{ allSelected ? 'Снять всё' : 'Выбрать всё' }}
        </button>
        <button type="button" @click="bulkForward" :disabled="!selectedIds.length" aria-label="Переслать"
                class="grid size-9 place-items-center rounded-md text-text2 hover:bg-bg2 disabled:opacity-40"><Forward class="size-5" /></button>
        <button type="button" @click="bulkDelete" :disabled="!selectedIds.length" aria-label="Удалить"
                class="grid size-9 place-items-center rounded-md text-red hover:bg-bg2 disabled:opacity-40"><Trash2 class="size-5" /></button>
      </div>

      <!-- Плашка закреплённого -->
      <button v-if="topPinned" type="button" @click="jumpTo(topPinned.id)"
              class="flex shrink-0 items-center gap-2 border-b border-border bg-card px-3 py-1.5 text-left">
        <Pin class="size-4 shrink-0 text-accent" />
        <div class="min-w-0">
          <div class="text-[11px] font-semibold text-accent">Закреплённое{{ pinned.length > 1 ? ` · ${pinned.length}` : '' }}</div>
          <div class="truncate text-xs text-text2">{{ topPinned.body }}</div>
        </div>
      </button>

      <!-- Лента -->
      <!-- Отступы задаём НА САМОМ сообщении (mt-*), а не через space-y на контейнере:
           селектор space-y перебивал бы mt-* по специфичности, и пачки склеивались бы
           с соседними — визуальной группировки не получалось. -->
      <div ref="scroller" class="min-h-0 flex-1 overflow-y-auto px-3 py-4">
        <div v-for="msg in messages" :id="`gb-msg-${msg.id}`" :key="msg.id"
             class="flex items-end gap-2"
             :class="[msg.mine ? 'justify-end' : 'justify-start',
                      runStarts.has(msg.id) ? 'mt-4 first:mt-0' : 'mt-0.5']">
          <input v-if="selectionMode" type="checkbox" :checked="selectedIds.includes(msg.id)"
                 @change="m.toggleSelect(msg.id)" class="order-first accent-[var(--gb-accent)]" />
          <!-- Аватарка собеседника — только у верхнего сообщения пачки; ниже держим отступ. -->
          <div v-if="!msg.mine" class="w-8 shrink-0">
            <Avatar v-if="runStarts.has(msg.id)" :src="senderAvatar(msg)"
                    :name="msg.sender_name || activePeer?.full_name || ''" :size="32" />
          </div>
          <button type="button" @click="onMessageClick(msg)"
                  @contextmenu="onContextMenu(msg, $event)"
                  @touchstart.passive="onTouchStart(msg, $event)"
                  @touchmove.passive="onTouchMove($event)"
                  @touchend="onTouchEnd" @touchcancel="onTouchEnd"
                  class="max-w-[75%] select-none rounded-2xl px-3 py-1.5 text-left text-sm shadow-sm transition-shadow hover:shadow"
                  :class="msg.mine ? 'bg-accent text-white' : 'bg-card text-text'"
                  :style="swipe.id === msg.id ? `transform: translateX(${swipe.dx}px)` : ''">
            <!-- ФИО автора — у верхнего сообщения пачки (в своих не нужно). -->
            <div v-if="!msg.mine && runStarts.has(msg.id) && (msg.sender_name || activePeer?.full_name)"
                 class="mb-0.5 text-[11px] font-semibold text-accent">
              {{ msg.sender_name || activePeer?.full_name }}
            </div>
            <div v-if="msg.forwarded_from" class="mb-0.5 text-[11px] italic opacity-80">
              Переслано от {{ msg.forwarded_from }}
            </div>
            <div v-if="msg.reply_to_id && quoted(msg.reply_to_id)"
                 class="mb-1 border-l-2 pl-2 text-xs opacity-80"
                 :class="msg.mine ? 'border-white/60' : 'border-accent'">
              {{ quoted(msg.reply_to_id) }}
            </div>
            <span v-if="msg.deleted" class="italic opacity-70">Сообщение удалено</span>
            <span v-else class="whitespace-pre-wrap break-words">{{ msg.body }}</span>
            <span class="ml-2 align-bottom text-[10px]" :class="msg.mine ? 'text-white/70' : 'text-text3'">
              <Pin v-if="msg.pinned" class="mr-0.5 inline size-2.5" />{{ msg.edited_at ? 'изм. ' : '' }}{{ fmtTime(msg.created_at) }}
            </span>
          </button>
        </div>
      </div>

      <!-- Плашка анти-флуда/мьюта: «не отправляйте так часто» / «вы ограничены модерацией» -->
      <div v-if="notice" class="shrink-0 border-t border-border bg-red/10 px-3 py-2 text-center text-xs font-semibold text-red">
        {{ notice }}
      </div>

      <!-- Композер с превью ответа (или плашка для читателя канала) -->
      <div class="shrink-0 border-t border-border bg-card">
        <template v-if="canPost">
          <div v-if="replyTo" class="flex items-center gap-2 border-b border-border px-3 py-1.5">
            <ReplyIcon class="size-4 shrink-0 text-accent" />
            <div class="min-w-0 flex-1">
              <div class="text-[11px] font-semibold text-accent">Ответ</div>
              <div class="truncate text-xs text-text3">{{ replyTo.deleted ? 'Сообщение удалено' : replyTo.body }}</div>
            </div>
            <button type="button" @click="m.clearReply()" aria-label="Отменить ответ"
                    class="grid size-6 place-items-center rounded-md text-text3 hover:bg-bg2"><X class="size-4" /></button>
          </div>
          <form class="flex items-end gap-2 p-2.5" @submit.prevent="submit">
            <textarea ref="composer" v-model="draft" rows="1" placeholder="Сообщение…"
                      @keydown="onKey" @input="m.sendTyping()"
                      class="max-h-32 min-h-[40px] min-w-0 flex-1 resize-none rounded-lg border border-border2 bg-card2 px-3 py-2 text-sm text-text outline-none focus:border-accent focus:bg-card" />
            <button type="submit" :disabled="!draft.trim() || sending" aria-label="Отправить"
                    class="grid size-10 shrink-0 place-items-center rounded-lg bg-accent text-white transition-colors hover:bg-accent2 disabled:opacity-50">
              <Send class="size-5" />
            </button>
          </form>
        </template>
        <!-- Читатель канала: писать нельзя, только подписка -->
        <div v-else class="flex items-center justify-between gap-2 p-3 text-sm text-text3">
          <span>Вы подписаны на канал</span>
          <button type="button" @click="m.leaveActive()"
                  class="rounded-lg border border-border2 px-3 py-1.5 text-text2 hover:bg-bg2">Покинуть</button>
        </div>
      </div>
    </template>

    <!-- Оверлей действий -->
    <MessageActionsOverlay v-if="overlay.open" :message="overlay.message" :x="overlay.x" :y="overlay.y"
                           @pick="onPick" @close="overlay.open = false" />

    <!-- Выбор режима удаления своего сообщения(-й) -->
    <div v-if="deleteTargets" class="fixed inset-0 z-50 grid place-items-center p-4"
         style="background: var(--gb-overlay)" @click.self="deleteTargets = null">
      <div class="w-full max-w-xs rounded-xl border border-border2 bg-card p-5 shadow-card">
        <h3 class="font-title text-base font-bold text-text">
          Удалить {{ deleteTargets.length > 1 ? `${deleteTargets.length} сообщений` : 'сообщение' }}?
        </h3>
        <p class="mt-1 text-xs text-text3">«У всех» сотрёт текст у собеседника, «у себя» — скроет только у вас.</p>
        <div class="mt-4 space-y-2">
          <button type="button" @click="applyDelete('all')"
                  class="w-full rounded-lg bg-red px-4 py-2 text-sm font-semibold text-white hover:opacity-90">Удалить у всех</button>
          <button type="button" @click="applyDelete('self')"
                  class="w-full rounded-lg border border-border2 px-4 py-2 text-sm text-text hover:bg-bg2">Удалить у себя</button>
          <button type="button" @click="deleteTargets = null"
                  class="w-full rounded-lg px-4 py-2 text-sm text-text3 hover:bg-bg2">Отмена</button>
        </div>
      </div>
    </div>

    <!-- «О беседе»: профиль собеседника / участники группы с владельцем -->
    <ConversationInfo v-if="showInfo" @close="showInfo = false" />

    <ReportDialog v-if="reportMsg" :message="reportMsg" @submit="onReportSubmit" @close="reportMsg = null" />
    <ForwardPicker v-if="forwardState.open" :count="forwardState.ids.length"
                   @submit="onForwardSubmit" @close="forwardState = { open: false, ids: [] }" />

    <!-- Тост «скопировано» -->
    <transition name="fade">
      <div v-if="copied" class="pointer-events-none fixed bottom-24 left-1/2 z-50 -translate-x-1/2 rounded-lg bg-text px-3 py-1.5 text-xs text-card shadow-card">
        Скопировано
      </div>
    </transition>
  </section>
</template>

<style scoped>
.fade-enter-active, .fade-leave-active { transition: opacity 0.2s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
