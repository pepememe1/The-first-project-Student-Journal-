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
import { useActivityStore } from '@/stores/activity'
import { getAccess } from '@/api/tokens'
import { getApiBase } from '@/api/server'
import { playMentionPing } from '@/utils/pingSound'

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
  // Тип беседы (direct | group | channel | saved | moderation), известный СРАЗУ — не
  // дожидаясь ответа /chats/{id}. Раньше и лента, и боковая панель читали тип только из
  // activeInfo, а пока он не приехал, подставляли 'direct': «Избранное» на долю секунды
  // показывалось как переписка с человеком («был(а) недавно»), группа — как личный чат.
  // Тип берём по порядку надёжности: подробности беседы → строка списка чатов →
  // детерминированный префикс id («saved:<user>», см. _saved_conv_id на сервере).
  const activeKind = computed(() =>
    activeInfo.value?.kind || activeChat.value?.kind
    || (activeId.value.startsWith('saved:') ? 'saved' : '')
    || (activeId.value.startsWith('mod:') ? 'moderation' : '')
    || 'direct')

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

  // Громкие отметки (`/@!Фамилия`), по которым уже звонили. Держим id САМИХ СООБЩЕНИЙ, а
  // не бесед: иначе вторая отметка в том же чате прошла бы молча. Сбрасывается вместе со
  // стором при выходе (reset) — новому аккаунту чужие «уже звонили» не нужны.
  const _pinged = new Set()

  async function loadChats() {
    loadingChats.value = true
    try {
      const { data } = await messengerApi.chats()
      chats.value = data.chats || []
      _refreshActivePeer()
      _ringLoudMentions()
    } catch { /* сервер ещё не поднят / оффлайн — пустой список */ }
    finally { loadingChats.value = false }
  }

  // Карточка собеседника бралась ОДИН раз при входе в чат и дальше не обновлялась: смена
  // статуса («не беспокоить», «отошёл») или уход в оффлайн доезжали только после
  // повторного открытия переписки — со стороны это и выглядело как «статус не работает».
  // Свежие данные и так приходят в списке чатов на каждом тике — берём их оттуда, без
  // отдельного запроса.
  function _refreshActivePeer() {
    if (!activeId.value || !activePeer.value) return
    const fresh = chats.value.find(c => c.conversation_id === activeId.value)?.peer
    if (fresh) activePeer.value = fresh
  }

  // Звук громкой отметки. Живёт в СТОРЕ, а не в компоненте чата: список чатов обновляется
  // на всех страницах (AppShell держит фоновый опрос), и «вас позвали» должно быть слышно
  // из журнала или расписания — иначе смысл громкого пинга теряется.
  // Замьюченные беседы сервер сюда не присылает как loud (см. _notify_loud_mentions).
  function _ringLoudMentions() {
    for (const c of chats.value) {
      if (!c.mention_loud || !c.mention_message_id) continue
      if (_pinged.has(c.mention_message_id)) continue
      //Отметку считаем показанной ВСЕГДА, даже когда звук приглушён: иначе, сняв
      //«не беспокоить», человек получил бы очередь накопившихся сигналов разом.
      _pinged.add(c.mention_message_id)
      //🔕 «Не беспокоить» глушит именно ЗВУК. Само письмо и значок остаются: статус
      //отключает то, что дёргает, а не факт события — тот же принцип, что у категорий
      //уведомлений на сервере (rustore_push.notify_login).
      if (myStatus.value.kind === 'dnd') continue
      playMentionPing()
    }
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

  // reset=true — вход в ДРУГУЮ беседу (старую карточку показывать нельзя, чистим сразу).
  // reset=false — обновление на тике опроса: карточку НЕ гасим.
  // Раньше гасили всегда, и на каждом опросе (раз в 3.5 с) панель на время сетевого
  // запроса оставалась без activeInfo — группа/канал «моргали» и подменялись карточкой
  // собеседника. Пустое значение показываем только когда правда не знаем, что за беседа.
  async function loadConvInfo(reset = true) {
    if (!activeId.value) { activeInfo.value = null; return }
    if (reset) activeInfo.value = null
    const convId = activeId.value
    try {
      const { data } = await messengerApi.convInfo(convId)
      //Ответ мог прийти уже после перехода в другой чат — тогда он не про эту беседу.
      if (activeId.value === convId) activeInfo.value = data
    } catch { /* личный чат может не отдавать расширенное инфо — не критично */ }
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
  // §D10: UUID для идемпотентности — ретрай с тем же nonce (обрыв сети/двойной клик по
  // «Отправить») не создаст на сервере дубль сообщения.
  function _nonce() {
    if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID()
    return `${Date.now()}-${Math.random().toString(36).slice(2)}`
  }

  // §D2: «маскот-замедление» — сервер шлёт 429 с {mascot:true, cooldown_seconds}. Вместо
  // холодной плашки-ошибки показываем Вектора с фразой и на cooldown.seconds блокируем
  // композер (обратный отсчёт — remaining).
  const mascotCooldown = ref({ active: false, seconds: 0, remaining: 0 })
  let cooldownTimer = null
  function _startCooldown(seconds) {
    clearInterval(cooldownTimer)
    mascotCooldown.value = { active: true, seconds, remaining: seconds }
    cooldownTimer = setInterval(() => {
      mascotCooldown.value.remaining -= 1
      if (mascotCooldown.value.remaining <= 0) {
        clearInterval(cooldownTimer)
        mascotCooldown.value = { active: false, seconds: 0, remaining: 0 }
      }
    }, 1000)
  }

  // Добавить сообщение в ленту, если его там ещё нет. Дедуп обязателен: сервер шлёт
  // WS-сигнал «changed» ДО того, как вернёт ответ на POST /send, и тик опроса успевает
  // притащить наше же сообщение раньше, чем resolve'нется этот await. Ярче всего это
  // видно на «/vector»: ответ ИИ считается ПОСЛЕ отправки, POST висит секунды, и
  // сообщение гарантированно приезжает опросом первым — в ленте появлялся дубль.
  function _appendUnique(msg) {
    if (!msg || messages.value.some(x => x.id === msg.id)) return
    messages.value.push(msg)
  }

  // Общий хвост и для текста, и для GIF (см. sendGif ниже) — анти-флуд/мьют отвечают
  // ОДИНАКОВО независимо от вида сообщения, дублировать разбор ошибки незачем.
  function _handleSendError(e) {
    const st = e?.response?.status
    const detail = e?.response?.data?.detail
    if (st === 429 && detail && typeof detail === 'object' && detail.mascot) {
      _startCooldown(detail.cooldown_seconds || 8)
    } else if ([400, 403, 429].includes(st)) {
      //400 сюда попал не для полноты: так отвечает разбор команд («/отчет чужая-группа»),
      //и без плашки человек видел ровно ничего — сообщение исчезало без объяснений.
      setNotice((typeof detail === 'string' && detail) || 'Сообщение не отправлено.')
    }
  }

  async function send(text) {
    const body = (text || '').trim()
    if (!body || !activeId.value || sending.value) return false
    sending.value = true
    try {
      const { data } = await messengerApi.send(activeId.value, body, replyTo.value?.id || 0, _nonce())
      // `/активность` — команда, а не сообщение: сервер вообще не создаёт строку в ленте
      // и отвечает указанием открыть выбор категории. Проверяем ДО _appendUnique: иначе
      // объект-команда лёг бы в ленту пузырём без текста.
      if (data?.command === 'open_activity_launcher') {
        useActivityStore().openLauncher(data.conversation_id || activeId.value)
        replyTo.value = null
        setNotice('')
        return true
      }
      _appendUnique(data)
      replyTo.value = null
      setNotice('')
      await loadChats()
      return true
    } catch (e) {
      _handleSendError(e)
      return false
    } finally { sending.value = false }
  }

  // GIF-пикер (Klipy) — отправляется СРАЗУ по клику на превью (как в Discord), а не
  // вставляется в поле ввода: тело сообщения — прямая ссылка, редактировать её незачем.
  async function sendGif(item) {
    if (!item?.url || !activeId.value || sending.value) return false
    sending.value = true
    try {
      const { data } = await messengerApi.send(
        activeId.value, item.url, replyTo.value?.id || 0, _nonce(),
        { kind: 'gif', gif_slug: item.slug || '' })
      _appendUnique(data)
      replyTo.value = null
      setNotice('')
      await loadChats()
      return true
    } catch (e) {
      _handleSendError(e)
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
          for (const msg of fresh) _appendUnique(msg)
          await markReadActive()
        }
      } catch { /* noop */ }
      // Галочки «прочитано» в ЛС читают last_read_at собеседника из activeInfo — держим
      // его свежим на каждый тик опроса/WS-сигнала, иначе галочка сменится только при
      // повторном входе в чат (см. ChatThread.vue::peerLastReadAt). Без сброса (reset=false):
      // иначе панель справа моргает на каждом тике.
      await loadConvInfo(false)
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
        } else if (ev.type && ev.type.startsWith('activity.')) {
          // Активности (docs/PLAN-ACTIVITIES.md §7) — своего канала у них нет, кадры
          // идут этим же сокетом. Разбор — в сторе активности: тут только маршрутизация.
          const act = useActivityStore()
          if (ev.type === 'activity.started') act.onStarted(ev, activeId.value)
          else if (ev.type === 'activity.state') act.applyFrame(ev)
          else if (ev.type === 'activity.finished') act.onFinished(ev)
          if (ev.conversation_id === activeId.value) pollOnce()   // карточка в ленте
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
    isModeration.value = false; clearSelection(); closeThread(); clearSearch()
    setNotice('')
  }

  // Полный сброс стора — при выходе/смене аккаунта. Иначе список чатов, активная беседа и
  // её сообщения остаются от прошлого юзера (чужой канал «как будто создал ты», чужое
  // сообщение с mine=true «как будто написал ты»). Пара к clearCache() в auth.logout().
  function reset() {
    stopPolling()
    stopIdleWatch()          //иначе авто-«отошёл» продолжил бы жить от прошлого аккаунта
    clearActive()
    chats.value = []
    channels.value = []
    peerTyping.value = false
    _pinged.clear()          //чужие «уже звонили» новому аккаунту не наследуем
    dir.value = { role: 'student', q: '', users: [], loading: false }
  }

  // ── Группы и каналы (Фазы 5–6) ──────────────────────────────────────────────────────
  async function createGroup(title, memberIds = [], about = '', classGroups = []) {
    try {
      const { data } = await messengerApi.createGroup(title, memberIds, about, classGroups)
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
  // §D12: открыть/создать канал «Объявления · Группа» (teacher/admin) и перейти в него —
  // дальше публикация обычным send(), отдельного «отправить объявление» не нужно.
  async function openAnnouncementsChannel(groupName) {
    const g = (groupName || '').trim()
    if (!g) return 'Выберите группу'
    try {
      const { data } = await messengerApi.ensureAnnouncementsChannel(g)
      await loadChats()
      await _enterChat(data.conversation_id, { full_name: data.title, role: 'channel' })
      return ''
    } catch (e) { return _errText(e, 'Не удалось открыть канал объявлений') }
  }
  // §12: найти/создать канал «Отчёты · Группа» и вернуть его id (только куратор этой
  // группы и только если у группы есть активный родитель — сервер проверяет обе границы).
  // Нужен диалогу отчёта: канал — один из возможных адресатов, наравне с личными чатами.
  async function ensureReportsChannel(groupName) {
    const g = (groupName || '').trim()
    if (!g) return { id: '', error: 'Выберите группу' }
    try {
      const { data } = await messengerApi.ensureCuratorReportsChannel(g)
      return { id: data.conversation_id, error: '' }
    } catch (e) { return { id: '', error: _errText(e, 'Не удалось открыть канал отчётов') } }
  }
  // §12: создать отчёт по группе и отправить его сообщением (в ЛС родителям и/или в
  // выбранные беседы; без адресатов — себе в «Избранное»). Возвращает текст ошибки или ''.
  // Ошибку ОБЯЗАТЕЛЬНО показываем: молчание в ответ на «Создать» и читалось как «не работает».
  async function createReport(group, userIds = [], convIds = []) {
    try {
      const { data } = await messengerApi.createReport(group, userIds, convIds)
      await loadChats()
      await _enterChat(data.conversation_id, { full_name: '', role: '' })
      return ''
    } catch (e) { return _errText(e, 'Не удалось создать отчёт') }
  }
  //Текст ошибки от сервера (detail) — он написан для человека, а не «Request failed 400».
  function _errText(e, fallback) {
    const d = e?.response?.data?.detail
    return (typeof d === 'string' && d) ? d : fallback
  }

  async function leaveActive() {
    if (!activeId.value) return
    try { await messengerApi.leave(activeId.value); clearActive(); await loadChats() } catch { /* noop */ }
  }
  // §D6: переименовать активную группу/канал (owner/admin) — сервер сам допишет системное
  // сообщение "title_changed:…" в ленту.
  async function renameActive(title, about) {
    if (!activeId.value) return false
    try {
      await messengerApi.renameChat(activeId.value, title, about)
      await loadConvInfo()
      await loadChats()
      return true
    } catch { return false }
  }

  // §ролей: выгнать/выдать роль/игнор — действуют на АКТИВНУЮ беседу, перегружают
  // activeInfo (там же лежат my_permissions/participants[].custom_role_id).
  async function kickMember(userId) {
    if (!activeId.value) return false
    try { await messengerApi.removeMember(activeId.value, userId); await loadConvInfo(); return true }
    catch { return false }
  }
  async function setMemberRole(userId, opts) {
    if (!activeId.value) return false
    try { await messengerApi.setMemberRole(activeId.value, userId, opts); await loadConvInfo(); return true }
    catch { return false }
  }
  async function toggleIgnore(userId, ignored) {
    if (!activeId.value) return false
    try {
      if (ignored) await messengerApi.unignoreMember(activeId.value, userId)
      else await messengerApi.ignoreMember(activeId.value, userId)
      await loadConvInfo()
      return true
    } catch { return false }
  }

  // §D7: мой статус (поверх presence) — dnd/studying/away + текст (только у преподавателя).
  const myStatus = ref({ kind: '', custom_text: '' })
  async function loadMyStatus() {
    try { const { data } = await messengerApi.getStatus(); myStatus.value = data } catch { /* noop */ }
  }
  // ── Авто-«отошёл» по бездействию (как в Discord) ─────────────────────────────────
  // Человек оставил вкладку открытой и ушёл — собеседник не должен думать, что ему
  // просто не отвечают. Ставим «отошёл» САМИ и снимаем при первом же действии.
  //
  // ⚠️ Возвращаем ровно тот статус, что был ДО отлучки, а не «обычный»: иначе выбранное
  // человеком «не беспокоить» тихо слетало бы после каждой отлучки, и он получал бы
  // звуки, от которых как раз отписался. И по той же причине авто-режим НЕ трогает
  // статусы, выставленные вручную сейчас, — только запоминает их на время отсутствия.
  const AWAY_AFTER_MS = 10 * 60 * 1000     //как в Discord — десять минут тишины
  let _idleTimer = null
  let _statusBeforeAway = null             //не null → «отошёл» поставили мы, а не человек

  async function _goAway() {
    if (_statusBeforeAway !== null || myStatus.value.kind === 'away') return
    _statusBeforeAway = { ...myStatus.value }
    await setMyStatus('away', myStatus.value.custom_text || '', true)
  }

  async function _comeBack() {
    if (_statusBeforeAway === null) return
    const prev = _statusBeforeAway
    _statusBeforeAway = null
    await setMyStatus(prev.kind, prev.custom_text || '', true)
  }

  function _resetIdle() {
    if (_idleTimer) clearTimeout(_idleTimer)
    _idleTimer = setTimeout(_goAway, AWAY_AFTER_MS)
    _comeBack()
  }

  const _IDLE_EVENTS = ['pointerdown', 'keydown', 'wheel', 'touchstart']
  function startIdleWatch() {
    if (_idleTimer) return                 //уже следим — второй раз не подписываемся
    for (const e of _IDLE_EVENTS) window.addEventListener(e, _resetIdle, { passive: true })
    //Сворачивание вкладки — тоже отсутствие, и узнаём мы о нём сразу, не дожидаясь таймера.
    document.addEventListener('visibilitychange', _onVisibility)
    _resetIdle()
  }
  function stopIdleWatch() {
    for (const e of _IDLE_EVENTS) window.removeEventListener(e, _resetIdle)
    document.removeEventListener('visibilitychange', _onVisibility)
    if (_idleTimer) { clearTimeout(_idleTimer); _idleTimer = null }
    _statusBeforeAway = null
  }
  function _onVisibility() {
    if (document.visibilityState === 'hidden') _goAway()
    else _resetIdle()
  }

  //auto=true — статус меняем МЫ (авто-отошёл), а не человек: такой вызов не должен
  //затирать память о прежнем статусе, иначе возвращаться будет некуда.
  async function setMyStatus(kind, customText = '', auto = false) {
    if (!auto) _statusBeforeAway = null
    try {
      const { data } = await messengerApi.setStatus(kind, customText)
      myStatus.value = { kind: data.kind, custom_text: data.custom_text }
      return true
    } catch { return false }
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

  // §D3: поставить/снять реакцию-эмодзи. Обновляем локально ОПТИМИСТИЧНО (сервер отвечает
  // просто {ok:true}, без свежего списка реакций) — лишний перезапрос истории не нужен.
  async function toggleReaction(mid, emoji) {
    const msg = messages.value.find(x => x.id === mid)
    if (!msg) return
    const list = msg.reactions || []
    const cell = list.find(r => r.emoji === emoji)
    const wasMine = !!cell?.mine
    try {
      if (wasMine) await messengerApi.removeReaction(mid, emoji)
      else await messengerApi.addReaction(mid, emoji)
    } catch { return }
    if (wasMine) {
      cell.count -= 1
      msg.reactions = list.filter(r => r.count > 0)
    } else if (cell) {
      cell.count += 1; cell.mine = true
    } else {
      msg.reactions = [...list, { emoji, count: 1, mine: true }]
    }
  }

  // §D11: история редактирования сообщения (для попапа «(ред.)» → версии).
  async function messageHistory(mid) {
    try { const { data } = await messengerApi.messageHistory(mid); return data.versions || [] }
    catch { return [] }
  }

  // ── Организация списка чатов: закреп/архив/избранное (docs/MESSENGER-ADDON-PLAN-GPT*.md) ─
  async function togglePinChat(convId, on) {
    try {
      if (on) await messengerApi.pinChat(convId); else await messengerApi.unpinChat(convId)
      await loadChats()
      return true
    } catch { return false }
  }
  async function toggleArchiveChat(convId, on) {
    try {
      if (on) await messengerApi.archiveChat(convId); else await messengerApi.unarchiveChat(convId)
      if (on && activeId.value === convId) clearActive()   //ушли в архив — закрыть открытый тред
      await loadChats()
      return true
    } catch { return false }
  }
  // «Избранное» (Saved Messages) — личный чат с самим собой: заметки/ссылки/код себе, без
  // отдельной сущности заметок (переиспользуем всю инфраструктуру сообщений). Ленивое
  // создание на сервере при первом входе, закреплён по умолчанию (см. openSaved на сервере).
  async function openSaved() {
    try {
      const { data } = await messengerApi.openSaved()
      await loadChats()
      await _enterChat(data.conversation_id, { full_name: 'Избранное', role: 'saved' })
      return true
    } catch { return false }
  }

  // ── Черновики (клиент-only, docs/MESSENGER-ADDON-PLAN-GPT.md «Черновики») ──────────────
  // Мессенджер и так не синкует состояние между устройствами (см. §5.4 CLAUDE.md) —
  // серверное хранилище черновика было бы лишней сущностью ради того же эффекта.
  const _DRAFTS_KEY = 'gb_msg_drafts'
  function _loadDraftsMap() {
    try { return JSON.parse(localStorage.getItem(_DRAFTS_KEY) || '{}') } catch { return {} }
  }
  function draftFor(convId) {
    return convId ? (_loadDraftsMap()[convId] || '') : ''
  }
  function saveDraft(convId, text) {
    if (!convId) return
    const map = _loadDraftsMap()
    const t = (text || '')
    if (t.trim()) map[convId] = t; else delete map[convId]
    try { localStorage.setItem(_DRAFTS_KEY, JSON.stringify(map)) } catch { /* приватный режим — не критично */ }
  }
  function clearDraft(convId) { saveDraft(convId, '') }

  // ── Шаблоны быстрых ответов преподавателя ───────────────────────────────────────────
  const templates = ref([])
  async function loadTemplates() {
    try { const { data } = await messengerApi.templates(); templates.value = data.templates || [] }
    catch { templates.value = [] }
  }
  async function addTemplate(body) {
    const t = (body || '').trim()
    if (!t) return false
    try { const { data } = await messengerApi.createTemplate(t); templates.value.push(data); return true }
    catch { return false }
  }
  async function removeTemplate(id) {
    try { await messengerApi.deleteTemplate(id); templates.value = templates.value.filter(x => x.id !== id) }
    catch { /* noop */ }
  }

  // ── Треды: просмотр ответов на сообщение (переиспользует reply_to_id, без нового
  // «тредового» состояния на сервере — см. docs/MESSENGER-ADDON-PLAN-GPT-SMART.md §3.3) ────
  const activeThread = ref(null)   // { parentId, messages: [] } | null
  async function openThread(messageId) {
    if (!activeId.value) return
    try {
      const { data } = await messengerApi.thread(activeId.value, messageId)
      activeThread.value = { parentId: messageId, messages: data.messages || [] }
    } catch { activeThread.value = { parentId: messageId, messages: [] } }
  }
  function closeThread() { activeThread.value = null }

  // ── Поиск внутри активного чата ──────────────────────────────────────────────────────
  const searchResults = ref(null)   // null — поиск закрыт; [] — открыт, но пусто
  const searching = ref(false)
  // §17: слова, которыми модель расширила запрос («домашка» → дз, задание). Показываем их
  // пользователю — иначе непонятно, почему нашлось сообщение без искомого слова.
  const searchExpanded = ref([])
  async function searchInActive(q) {
    if (!activeId.value || !(q || '').trim()) { searchResults.value = null; searchExpanded.value = []; return }
    searching.value = true
    try {
      // Умный поиск: сервер спрашивает у модели словоформы и синонимы к ЗАПРОСУ (саму
      // переписку она не видит) и ищет по всем вариантам сразу. Модель недоступна —
      // сервер вернёт то же, что обычный поиск, и expanded придёт пустым.
      const { data } = await messengerApi.aiSearchInChat(activeId.value, q)
      searchResults.value = data.messages || []
      searchExpanded.value = data.expanded || []
    } catch {
      // Умный поиск не ответил вовсе — откатываемся на обычный, а не показываем пустоту.
      searchExpanded.value = []
      try { const { data } = await messengerApi.searchInChat(activeId.value, q); searchResults.value = data.messages || [] }
      catch { searchResults.value = [] }
    } finally { searching.value = false }
  }
  function clearSearch() { searchResults.value = null; searchExpanded.value = [] }

  // Кто прочитал сообщение — по запросу (попап под сообщением), в общее состояние не кладём.
  async function readBy(mid) {
    try { const { data } = await messengerApi.readBy(mid); return data.users || [] }
    catch { return [] }
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
    replyTo, pinned, selectionMode, selectedIds, isModeration, activeInfo, activeKind,
    channels, dir,
    peerTyping, totalUnread, notice, activeChat, mascotCooldown,
    loadChats, loadMessages, selectChat, openWith, send, sendGif, markReadActive, loadPinned, setNotice,
    openModeration, pollOnce, startPolling, stopPolling, searchUsers, sendTyping,
    setReply, clearReply, clearActive, reset, loadConvInfo, muteConversation,
    deleteConversation, selectAll, selectNone,
    editMessage, setPinned, removeMessage, forwardMessages, reportMessage,
    toggleReaction, messageHistory,
    enterSelection, toggleSelect, clearSelection,
    createGroup, createChannel, loadChannels, joinChannel, leaveActive, renameActive,
    kickMember, setMemberRole, toggleIgnore,
    openAnnouncementsChannel, ensureReportsChannel, createReport,
    myStatus, loadMyStatus, setMyStatus, startIdleWatch, stopIdleWatch,
    togglePinChat, toggleArchiveChat, openSaved,
    draftFor, saveDraft, clearDraft,
    templates, loadTemplates, addTemplate, removeTemplate,
    activeThread, openThread, closeThread,
    searchResults, searching, searchExpanded, searchInActive, clearSearch,
    readBy,
  }
})
