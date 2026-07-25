/**
 * messenger.js — состояние мессенджера (Фаза 2: личные чаты).
 *
 * Отдельная онлайн-подсистема (см. docs/MESSENGER-PLAN.md): истина на сервере, здесь —
 * кэш активной переписки + список чатов + каталог людей. Транспорт Фазы 2 — ОПРОС
 * (poll ?after=<id> раз в несколько секунд); WebSocket добавим отдельной фазой, интерфейс
 * стора менять не придётся. `mine` (своё ли сообщение) считает сервер — клиент своего id
 * не знает (в JWT/сторе только логин+роль).
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { messengerApi } from '@/api/endpoints'
import { getAccess } from '@/api/tokens'
import { getApiBase } from '@/api/server'

const POLL_MS = 3500

// Параметры WebSocket-канала: та же база, что у REST, но схема ws/wss. Токен передаём
// сабпротоколом (['bearer', <jwt>]) — так он НЕ попадает в URL и, значит, в access-логи
// прокси. Сервер эхом вернёт 'bearer'. Пусто, если нет токена.
function _wsConn() {
  const token = getAccess()
  if (!token) return null
  const base = (getApiBase() || window.location.origin).replace(/^http/, 'ws')
  return { url: `${base}/web/messenger/ws`, protocols: ['bearer', token] }
}

export const useMessengerStore = defineStore('messenger', () => {
  const chats = ref([])                 // список бесед (см. /chats)
  const activeId = ref('')              // id активной беседы
  const activePeer = ref(null)          // карточка собеседника активной беседы
  const messages = ref([])             // сообщения активной беседы (хронология)
  const loadingChats = ref(false)
  const loadingMessages = ref(false)
  const sending = ref(false)
  const replyTo = ref(null)             // сообщение, на которое отвечаем (или null)
  const pinned = ref([])                // закреплённые сообщения активной беседы
  const selectionMode = ref(false)      // режим множественного выбора («Выделить»)
  const selectedIds = ref([])           // id выбранных сообщений
  const isModeration = ref(false)       // открыт чат с модерацией (кнопка ⚙)?
  const activeInfo = ref(null)          // инфо о группе/канале (участники, роли, моя роль)
  const channels = ref([])              // каталог публичных каналов

  const peerTyping = ref(false)         // собеседник печатает (по WS)
  const notice = ref('')                // сервисное уведомление (анти-флуд/мьют) — плашка в UI
  const totalUnread = computed(() => chats.value.reduce((s, c) => s + (c.unread || 0), 0))
  // Элемент активной беседы в списке чатов — источник её состояния (в т.ч. muted).
  const activeChat = computed(() => chats.value.find(c => c.conversation_id === activeId.value) || null)

  let noticeTimer = null
  function setNotice(text) {
    notice.value = text || ''
    clearTimeout(noticeTimer)
    if (text) noticeTimer = setTimeout(() => { notice.value = '' }, 4000)
  }

  // Каталог/поиск людей.
  const dir = ref({ role: 'student', q: '', users: [], loading: false })

  let pollTimer = null
  let ws = null
  let typingTimer = null
  let lastTypingSent = 0

  function _lastId() {
    return messages.value.length ? messages.value[messages.value.length - 1].id : 0
  }

  async function loadChats() {
    loadingChats.value = true
    try {
      const { data } = await messengerApi.chats()
      chats.value = data.chats || []
    } catch { /* сервер ещё не поднят / оффлайн — пустой список */ }
    finally { loadingChats.value = false }
  }

  async function loadMessages(convId) {
    loadingMessages.value = true
    try {
      const { data } = await messengerApi.messages(convId)
      messages.value = data.messages || []
    } catch { messages.value = [] }
    finally { loadingMessages.value = false }
  }

  async function _enterChat(convId, peer) {
    activeId.value = convId
    activePeer.value = peer
    isModeration.value = false
    peerTyping.value = false
    replyTo.value = null
    clearSelection()
    await loadMessages(convId)
    await loadPinned()
    await loadConvInfo()
    // Модерационную беседу распознаём по ТИПУ, а не только по кнопке ⚙: иначе при открытии
    // из списка/после перезагрузки она рендерится как обычный личный чат с ролью-заглушкой
    // «Студент» (см. ProfilePanel). Тип приходит из convInfo (kind='moderation').
    if (activeInfo.value?.kind === 'moderation') isModeration.value = true
    await markReadActive()
    await loadChats()                    // обновить счётчик непрочитанного в списке
  }

  async function loadConvInfo() {
    activeInfo.value = null
    if (!activeId.value) return
    try { const { data } = await messengerApi.convInfo(activeId.value); activeInfo.value = data }
    catch { /* личный чат может не отдавать расширенное инфо — не критично */ }
  }

  // Открыть беседу из СПИСКА чатов (peer уже в элементе списка).
  async function selectChat(chat) {
    await _enterChat(chat.conversation_id, chat.peer || { full_name: chat.title || '' })
  }

  // Открыть/создать личный чат с пользователем (из каталога/поиска).
  async function openWith(user) {
    try {
      const { data } = await messengerApi.openDirect(user.id)
      await _enterChat(data.conversation_id, data.peer || user)
    } catch { /* нет доступа/сервера — тихо */ }
  }

  async function loadPinned() {
    if (!activeId.value) { pinned.value = []; return }
    try {
      const { data } = await messengerApi.pinned(activeId.value)
      pinned.value = data.pinned || []
    } catch { pinned.value = [] }
  }

  // Открыть чат с модерацией (кнопка ⚙). Слева покажем правила вместо карточки собеседника.
  async function openModeration() {
    try {
      const { data } = await messengerApi.moderation()
      await _enterChat(data.conversation_id, { full_name: 'Модерация', role: 'moderation' })
      isModeration.value = true
    } catch { /* сервер не готов — тихо */ }
  }

  // Возвращает true при успехе; false — если сервер отклонил (анти-флуд 429 / мьют 403 и пр.),
  // чтобы вызывающий вернул текст в поле ввода. Причину показываем плашкой (notice).
  async function send(text) {
    const body = (text || '').trim()
    if (!body || !activeId.value || sending.value) return false
    sending.value = true
    try {
      const { data } = await messengerApi.send(activeId.value, body, replyTo.value?.id || 0)
      messages.value.push(data)
      replyTo.value = null
      setNotice('')
      await loadChats()
      return true
    } catch (e) {
      const st = e?.response?.status
      if (st === 429 || st === 403) setNotice(e?.response?.data?.detail || 'Сообщение не отправлено.')
      return false
    } finally { sending.value = false }
  }

  // Замьютить/размьютить активную беседу у себя (без пушей по ней).
  async function muteConversation(muted) {
    if (!activeId.value) return
    try { await messengerApi.muteChat(activeId.value, muted); await loadChats() } catch { /* noop */ }
  }

  // Удалить переписку У СЕБЯ (clearOnly — только очистить историю, чат остаётся в списке).
  // У собеседника переписка сохраняется — это личное действие.
  async function deleteConversation(clearOnly = false) {
    if (!activeId.value) return false
    try {
      await messengerApi.deleteChat(activeId.value, clearOnly)
      if (clearOnly) { messages.value = []; pinned.value = [] }
      else clearActive()
      await loadChats()
      return true
    } catch { return false }
  }

  async function markReadActive() {
    if (!activeId.value) return
    try { await messengerApi.read(activeId.value, _lastId()) } catch { /* noop */ }
  }

  // Опрос новых сообщений активной беседы + обновление списка чатов.
  async function pollOnce() {
    if (activeId.value) {
      try {
        const { data } = await messengerApi.messages(activeId.value, { after: _lastId() })
        const fresh = data.messages || []
        if (fresh.length) {
          const have = new Set(messages.value.map(m => m.id))
          for (const m of fresh) if (!have.has(m.id)) messages.value.push(m)
          await markReadActive()
        }
      } catch { /* noop */ }
    }
    await loadChats()
  }

  // ── WebSocket: живые события (Фаза 7) — опрос остаётся страховкой ───────────────────
  function _connectWS() {
    const conn = _wsConn()
    if (!conn || ws) return
    try {
      ws = new WebSocket(conn.url, conn.protocols)
      ws.onmessage = (e) => {
        let ev
        try { ev = JSON.parse(e.data) } catch { return }
        if (ev.type === 'changed') {
          if (ev.conversation_id === activeId.value) pollOnce()
          else loadChats()
        } else if (ev.type === 'typing' && ev.conversation_id === activeId.value) {
          peerTyping.value = true
          clearTimeout(typingTimer)
          typingTimer = setTimeout(() => { peerTyping.value = false }, 4000)
        }
      }
      ws.onclose = () => { ws = null }
      ws.onerror = () => { try { ws.close() } catch { /* noop */ } ws = null }
    } catch { ws = null }
  }
  function _disconnectWS() {
    if (ws) { try { ws.close() } catch { /* noop */ } ws = null }
  }
  // Сообщить собеседнику, что печатаю (не чаще раза в 2 c).
  function sendTyping() {
    if (!ws || ws.readyState !== 1 || !activeId.value) return
    const now = Date.now()
    if (now - lastTypingSent < 2000) return
    lastTypingSent = now
    try { ws.send(JSON.stringify({ type: 'typing', conversation_id: activeId.value })) } catch { /* noop */ }
  }

  function startPolling() {
    stopPolling()
    pollTimer = setInterval(pollOnce, POLL_MS)
    _connectWS()
  }
  function stopPolling() {
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
    _disconnectWS()
  }

  async function searchUsers(role, q) {
    dir.value.role = role
    dir.value.q = q
    dir.value.loading = true
    try {
      const { data } = await messengerApi.users(role, q)
      dir.value.users = data.users || []
    } catch { dir.value.users = [] }
    finally { dir.value.loading = false }
  }

  function setReply(msg) { replyTo.value = msg }
  function clearReply() { replyTo.value = null }
  function clearActive() {
    activeId.value = ''; activePeer.value = null; messages.value = []
    replyTo.value = null; pinned.value = []; activeInfo.value = null
    isModeration.value = false; clearSelection(); setNotice('')
  }

  // Полный сброс стора — при выходе/смене аккаунта. Иначе список чатов, активная беседа и
  // её сообщения остаются от прошлого юзера (чужой канал «как будто создал ты», чужое
  // сообщение с mine=true «как будто написал ты»). Пара к clearCache() в auth.logout().
  function reset() {
    stopPolling()
    clearActive()
    chats.value = []
    channels.value = []
    peerTyping.value = false
    dir.value = { role: 'student', q: '', users: [], loading: false }
  }

  // ── Группы и каналы (Фазы 5–6) ──────────────────────────────────────────────────────
  async function createGroup(title, memberIds = [], about = '') {
    try {
      const { data } = await messengerApi.createGroup(title, memberIds, about)
      await loadChats()
      await _enterChat(data.conversation_id, { full_name: data.title, role: 'group' })
      return true
    } catch { return false }
  }
  async function createChannel(title, writerIds = [], isPublic = true, about = '') {
    try {
      const { data } = await messengerApi.createChannel(title, writerIds, isPublic, about)
      await loadChats()
      await _enterChat(data.conversation_id, { full_name: data.title, role: 'channel' })
      return true
    } catch { return false }
  }
  async function loadChannels(q = '') {
    try { const { data } = await messengerApi.channels(q); channels.value = data.channels || [] }
    catch { channels.value = [] }
  }
  async function joinChannel(convId) {
    try {
      const { data } = await messengerApi.join(convId)
      await loadChats()
      await loadChannels(dir.value.q)
      await _enterChat(data.conversation_id, { full_name: '', role: 'channel' })
    } catch { /* noop */ }
  }
  async function leaveActive() {
    if (!activeId.value) return
    try { await messengerApi.leave(activeId.value); clearActive(); await loadChats() } catch { /* noop */ }
  }

  // ── Действия над сообщением (Фаза 3) ────────────────────────────────────────────────
  function _replaceMsg(updated) {
    const i = messages.value.findIndex(x => x.id === updated.id)
    if (i >= 0) messages.value[i] = updated
  }

  async function editMessage(id, body) {
    const t = (body || '').trim()
    if (!t) return
    try { const { data } = await messengerApi.edit(id, t); _replaceMsg(data) } catch { /* noop */ }
  }

  async function setPinned(id, on) {
    try {
      if (on) { const { data } = await messengerApi.pin(id); _replaceMsg(data) }
      else { await messengerApi.unpin(id); const m = messages.value.find(x => x.id === id); if (m) m.pinned = false }
      await loadPinned()
    } catch { /* noop */ }
  }

  async function removeMessage(id, scope = 'self') {
    try {
      await messengerApi.deleteMessage(id, scope)
      if (scope === 'all') {
        const m = messages.value.find(x => x.id === id)
        if (m) { m.deleted = true; m.body = ''; m.pinned = false }
      } else {
        messages.value = messages.value.filter(x => x.id !== id)
      }
      await loadPinned()
      await loadChats()
    } catch { /* noop */ }
  }

  async function forwardMessages(ids, toConvIds) {
    if (!ids.length || !toConvIds.length) return
    try { await messengerApi.forward(ids, toConvIds); await loadChats() } catch { /* noop */ }
  }

  async function reportMessage(id, reasonCode, description = '') {
    try { await messengerApi.report(id, reasonCode, description); return true } catch { return false }
  }

  // ── Множественный выбор («Выделить») ────────────────────────────────────────────────
  function enterSelection(firstId = 0) {
    selectionMode.value = true
    selectedIds.value = firstId ? [firstId] : []
  }
  function toggleSelect(id) {
    const i = selectedIds.value.indexOf(id)
    if (i >= 0) selectedIds.value.splice(i, 1)
    else selectedIds.value.push(id)
  }
  function clearSelection() { selectionMode.value = false; selectedIds.value = [] }
  // «Выбрать всё / снять всё» — по видимым сообщениям беседы.
  function selectAll() { selectedIds.value = messages.value.map(x => x.id) }
  function selectNone() { selectedIds.value = [] }

  return {
    chats, activeId, activePeer, messages, loadingChats, loadingMessages, sending,
    replyTo, pinned, selectionMode, selectedIds, isModeration, activeInfo, channels, dir,
    peerTyping, totalUnread, notice, activeChat,
    loadChats, loadMessages, selectChat, openWith, send, markReadActive, loadPinned,
    openModeration, pollOnce, startPolling, stopPolling, searchUsers, sendTyping,
    setReply, clearReply, clearActive, reset, loadConvInfo, muteConversation,
    deleteConversation, selectAll, selectNone,
    editMessage, setPinned, removeMessage, forwardMessages, reportMessage,
    enterSelection, toggleSelect, clearSelection,
    createGroup, createChannel, loadChannels, joinChannel, leaveActive,
  }
})
