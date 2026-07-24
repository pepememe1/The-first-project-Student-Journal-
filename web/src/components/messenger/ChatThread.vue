<script setup>
// ChatThread — правая колонка: переписка активной беседы (пузыри в стиле Telegram) +
// действия над сообщением (Фаза 3): оверлей по тапу, плашка закреплённого, режим
// выделения, ответ/пересылка/удаление(у себя|у всех)/жалоба. ⚙-чат модерации — Фаза 4.
import { ref, computed, watch, nextTick } from 'vue'
import { storeToRefs } from 'pinia'
import { Send, ArrowLeft, Pin, X, Reply as ReplyIcon, Forward, Trash2, Settings } from '@lucide/vue'
import { useMessengerStore } from '@/stores/messenger'
import MessageActionsOverlay from './MessageActionsOverlay.vue'
import ReportDialog from './ReportDialog.vue'
import ForwardPicker from './ForwardPicker.vue'

const m = useMessengerStore()
const { activeId, activePeer, messages, sending, replyTo, pinned, selectionMode, selectedIds, isModeration, activeInfo, peerTyping } = storeToRefs(m)

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

// Тап по сообщению: в режиме выделения — отметить; иначе — открыть оверлей действий.
function onMessageClick(msg, e) {
  if (selectionMode.value) { m.toggleSelect(msg.id); return }
  overlay.value = { open: true, message: msg, x: e.clientX, y: e.clientY }
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
  await m.send(t)
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
</script>

<template>
  <section class="flex min-w-0 flex-1 flex-col bg-bg" :class="{ 'hidden sm:flex': !activeId }">
    <div v-if="!activeId" class="grid flex-1 place-items-center p-6 text-center text-sm text-text3">
      Выберите чат слева или найдите человека через поиск.
    </div>

    <template v-else>
      <!-- Верхняя полоска / панель выделения -->
      <div v-if="!selectionMode" class="flex h-14 shrink-0 items-center gap-3 border-b border-border bg-card px-3">
        <button type="button" @click="m.clearActive()" aria-label="Назад"
                class="grid size-8 place-items-center rounded-md text-text2 hover:bg-bg2 sm:hidden">
          <ArrowLeft class="size-5" />
        </button>
        <div class="min-w-0 flex-1">
          <div class="truncate font-title text-base font-bold text-text">{{ peerName }}</div>
          <div class="text-xs text-text3">{{ subtitle }}</div>
        </div>
        <!-- ⚙ — открыть чат с модерацией (см. MESSENGER-PLAN.md §6) -->
        <button v-if="!isModeration" type="button" @click="m.openModeration()"
                aria-label="Модерация" title="Написать модерации"
                class="grid size-8 shrink-0 place-items-center rounded-md text-text3 hover:bg-bg2 hover:text-text">
          <Settings class="size-5" />
        </button>
      </div>
      <div v-else class="flex h-14 shrink-0 items-center gap-3 border-b border-border bg-card px-3">
        <button type="button" @click="m.clearSelection()" aria-label="Отмена"
                class="grid size-8 place-items-center rounded-md text-text2 hover:bg-bg2"><X class="size-5" /></button>
        <span class="flex-1 text-sm font-semibold text-text">Выбрано: {{ selectedIds.length }}</span>
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
      <div ref="scroller" class="min-h-0 flex-1 space-y-1.5 overflow-y-auto px-3 py-4">
        <div v-for="msg in messages" :id="`gb-msg-${msg.id}`" :key="msg.id"
             class="flex items-center gap-2" :class="msg.mine ? 'justify-end' : 'justify-start'">
          <input v-if="selectionMode" type="checkbox" :checked="selectedIds.includes(msg.id)"
                 @change="m.toggleSelect(msg.id)" class="order-first accent-[var(--gb-accent)]" />
          <button type="button" @click="onMessageClick(msg, $event)"
                  class="max-w-[75%] rounded-2xl px-3 py-1.5 text-left text-sm shadow-sm transition-shadow hover:shadow"
                  :class="msg.mine ? 'bg-accent text-white' : 'bg-card text-text'">
            <div v-if="isGroupOrChannel && !msg.mine && msg.sender_name"
                 class="mb-0.5 text-[11px] font-semibold text-accent">{{ msg.sender_name }}</div>
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
        <h3 class="font-title text-base font-bold text-text">Удалить {{ deleteTargets.length > 1 ? `(${deleteTargets.length})` : 'сообщение' }}?</h3>
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
