<script setup>
// ChatThread — правая колонка: переписка активной беседы (пузыри в стиле Telegram) +
// действия над сообщением (Фаза 3): оверлей по тапу, плашка закреплённого, режим
// выделения, ответ/пересылка/удаление(у себя|у всех)/жалоба. ⚙-чат модерации — Фаза 4.
import { ref, computed, watch, nextTick, onMounted } from 'vue'
import { storeToRefs } from 'pinia'
import {
  Send, ArrowLeft, Pin, X, Reply as ReplyIcon, Forward, Trash2, Settings, Bell, BellOff,
  Bold, Italic, Underline, Strikethrough, Code, Quote, ChevronDown, History,
  Search, Zap, MessageSquare, Eye, Plus, ScrollText, Check, CheckCheck, PieChart,
} from '@lucide/vue'
import { messengerApi } from '@/api/endpoints'
import { useMessengerStore } from '@/stores/messenger'
import { useAuthStore } from '@/stores/auth'
import { renderMarkdownLite } from '@/utils/markdownLite'
import { formatSystemMessage } from '@/utils/messagePreview'
import { copyText } from '@/utils/clipboard'
import MessageActionsOverlay from './MessageActionsOverlay.vue'
import ReportDialog from './ReportDialog.vue'
import ForwardPicker from './ForwardPicker.vue'
import ConversationInfo from './ConversationInfo.vue'
import MascotCooldown from './MascotCooldown.vue'
import ReminderDialog from './ReminderDialog.vue'
import CuratorReportOverlay from './CuratorReportOverlay.vue'
import Avatar from '@/components/ui/Avatar.vue'
import { profilePlate } from '@/theme/palette'

const m = useMessengerStore()
const auth = useAuthStore()
const { activeId, activePeer, messages, sending, replyTo, pinned, selectionMode, selectedIds, isModeration, activeInfo, peerTyping, notice, activeChat, activeKind, mascotCooldown, templates, activeThread, searchResults, searching, searchExpanded } = storeToRefs(m)
const canManageTemplates = computed(() => ['teacher', 'admin'].includes(auth.role))
// Админ САМ и есть модерация — кнопка «Написать модерации» ему не нужна (и сервер её закрыл).
const isAdmin = computed(() => auth.role === 'admin')
// Замьючена ли текущая беседа у меня (без пушей). Кнопка-колокольчик — в шапке.
const muted = computed(() => !!activeChat.value?.muted)

// Тип беседы и права (для шапки/композера групп и каналов).
//Тип беседы берём из стора (activeKind): он известен ещё до ответа /chats/{id}, иначе
//«Избранное» и группы на долю секунды рисовались как личный чат («был(а) недавно»).
const kind = computed(() => activeKind.value)
const isGroupOrChannel = computed(() => kind.value === 'group' || kind.value === 'channel')
const canPost = computed(() => {
  if (kind.value !== 'channel') return true
  return ['owner', 'admin', 'writer'].includes(activeInfo.value?.my_role)
})
// §D1: заголовки # / ## разрешены только в каналах (в личных чатах/группах — просто текст).
const isChannel = computed(() => kind.value === 'channel')

const draft = ref('')
const scroller = ref(null)
const composer = ref(null)

// Оверлей действий, модалки.
const overlay = ref({ open: false, message: null, x: 0, y: 0 })
const reportMsg = ref(null)                 // сообщение, на которое жалуемся
const openReportOverlay = ref(null)         // §12: id открытого отчёта куратора (или null)
const forwardState = ref({ open: false, ids: [] })
const deleteTargets = ref(null)             // [message,…] для выбора «у себя/у всех» (все свои)
const copied = ref(false)
const showInfo = ref(false)                 // панель «О беседе» (участники/владелец)
// Все ли видимые сообщения уже выделены — для кнопки «Выбрать всё / Снять всё».
const allSelected = computed(() => messages.value.length > 0 && selectedIds.value.length === messages.value.length)

async function scrollDown() {
  await nextTick()
  scroller.value?.scrollTo({ top: scroller.value.scrollHeight })
  showScrollBtn.value = false
}

// §D5: плавающая кнопка «↓ N новых» — видна, когда пользователь прокрутил вверх (читает
// историю); новые сообщения тогда НЕ дёргают его вниз силой (кроме своих же исходящих).
const showScrollBtn = ref(false)
function onScrollerScroll() {
  const el = scroller.value
  if (!el) return
  showScrollBtn.value = (el.scrollHeight - el.scrollTop - el.clientHeight) > 200
}

watch(() => messages.value.length, async () => {
  const wasNearBottom = !showScrollBtn.value
  const lastMsg = messages.value[messages.value.length - 1]
  if (wasNearBottom || lastMsg?.mine) scrollDown()
  else await nextTick().then(onScrollerScroll)
})

// §D5: разделитель «Новые сообщения» — первое сообщение позже метки прочтения ДО открытия
// чата (activeInfo.my_last_read_at снимается в сторе ДО markReadActive, см. messenger.js).
const firstUnreadId = computed(() => {
  const lastRead = activeInfo.value?.my_last_read_at
  if (!lastRead) return null
  const found = messages.value.find(x => x.created_at > lastRead)
  return found ? found.id : null
})

// Разделитель по датам (как в Telegram): «Сегодня» / «Вчера» / число — граница СУТОК по
// часовому поясу УСТРОЙСТВА (Date у клиента), а не сервера. Наступление 00:00 у пользователя
// само переносит вчерашний ярлык в дату — computed пересчитывается при каждом новом сообщении.
function _dayKey(iso) {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toDateString()
}
function _dayLabel(iso) {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const now = new Date()
  const yesterday = new Date(now)
  yesterday.setDate(now.getDate() - 1)
  const key = d.toDateString()
  if (key === now.toDateString()) return 'Сегодня'
  if (key === yesterday.toDateString()) return 'Вчера'
  return d.toLocaleDateString('ru-RU', d.getFullYear() === now.getFullYear()
    ? { day: 'numeric', month: 'long' } : { day: 'numeric', month: 'long', year: 'numeric' })
}
const dateBreaks = computed(() => {
  const map = new Map()   // msg.id → подпись (первое сообщение НОВЫХ суток)
  let prevKey = null
  for (const msg of messages.value) {
    const key = _dayKey(msg.created_at)
    if (key && key !== prevKey) {
      map.set(msg.id, _dayLabel(msg.created_at))
      prevKey = key
    }
  }
  return map
})

watch(activeId, async (newId, oldId) => {
  // Черновики (клиент-only, docs/MESSENGER-ADDON-PLAN-GPT.md «Черновики»): сохраняем
  // недописанное перед уходом из чата и восстанавливаем при возврате в него.
  if (oldId) m.saveDraft(oldId, draft.value)
  draft.value = newId ? m.draftFor(newId) : ''
  closeSearchPanel()
  if (!newId) return
  // Ждём, пока стор подгрузит и сообщения, и activeInfo (для позиции разделителя), но не
  // дольше секунды — иначе просто скроллим вниз как обычно (не хуже прежнего поведения).
  for (let i = 0; i < 20 && (!messages.value.length || activeInfo.value === null); i++) {
    await new Promise((r) => setTimeout(r, 50))
  }
  await nextTick()
  if (firstUnreadId.value) {
    const el = document.getElementById(`gb-msg-${firstUnreadId.value}`)
    if (el) { el.scrollIntoView({ behavior: 'instant', block: 'center' }); onScrollerScroll(); return }
  }
  scrollDown()
})

onMounted(() => {
  if (activeId.value) draft.value = m.draftFor(activeId.value)
  m.loadTemplates()
})

function fmtTime(iso) {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
}
function quoted(id) {
  const src = messages.value.find(x => x.id === id)
  return src ? (src.deleted ? 'Сообщение удалено' : src.body) : ''
}

// §D6: системные сообщения (вступил/вышел/переименовано/закреп) — сервер шлёт шаблон
// "событие\x1fаргументы". Разбор общий с левым списком чатов (utils/messagePreview):
// две копии разбора уже разъезжались — в ленте текст был человеческий, а в списке сырой.

// §D1: рендер тела сообщения (Markdown-lite → безопасный HTML для v-html).
// §D8: подсветка @Фамилия/@!Фамилия — визуальная, ПОСЛЕ Markdown (безопасно: результат
// markdownLite уже экранирован, «@Слово» — обычный текст ни в одном из вставленных тегов).
function renderBody(msg) {
  const html = renderMarkdownLite(msg.body, isChannel.value)
  //Подсвечиваем ВСЕ формы отметки, включая «/@» и «/@!» — иначе тихий и громкий пинги
  //в ленте выглядели обычным текстом со слэшем. Набор форм — как у сервера (_MENTION_RE).
  return html.replace(/\/?(?:@!?|!@)[A-Za-zА-Яа-яЁё]+/g,
                      (hit) => `<span class="mention">${hit}</span>`)
}

// §D3: клик по реакции — поставить/снять свою.
function onReactionClick(msg, emoji) { m.toggleReaction(msg.id, emoji) }
function onReact(emoji) {
  const msg = overlay.value.message
  if (msg) m.toggleReaction(msg.id, emoji)
}

// §D11: попап «История изменений» у отредактированного сообщения.
const historyPopup = ref({ open: false, versions: [] })
async function openHistory(msg) {
  historyPopup.value = { open: true, versions: await m.messageHistory(msg.id) }
}
function fmtFull(iso) {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' })
}

// §D1: тулбар форматирования — оборачивает ВЫДЕЛЕНИЕ в textarea нужными символами
// (или вставляет пару символов на позицию курсора, если ничего не выделено).
function wrapSelection(before, after = before) {
  const el = composer.value
  if (!el) return
  const start = el.selectionStart ?? draft.value.length
  const end = el.selectionEnd ?? draft.value.length
  const sel = draft.value.slice(start, end)
  draft.value = draft.value.slice(0, start) + before + sel + after + draft.value.slice(end)
  nextTick(() => {
    el.focus()
    const pos = sel ? end + before.length + after.length : start + before.length
    el.setSelectionRange(pos, pos)
  })
}
function onComposerKeydown(e) {
  if (e.ctrlKey || e.metaKey) {
    if (e.key === 'b') { e.preventDefault(); wrapSelection('**'); return }
    if (e.key === 'i') { e.preventDefault(); wrapSelection('*'); return }
    if (e.key === 'u') { e.preventDefault(); wrapSelection('__'); return }
  }
  if (mentionCandidates.value.length && e.key === 'Escape') { mentionQuery.value = null; return }
  if (slashCandidates.value.length && e.key === 'Escape') { slashQuery.value = null; return }
  onKey(e)
}

// ── Автодополнение слэш-команд «/» (как в Telegram) ─────────────────────────────────────
// Команда доступна только если это ВЕСЬ текст от начала сообщения до курсора (без
// пробела) — как только начат аргумент («/vector когда…»), подсказка сама пропадает.
// §12: /отчет доступен куратору (и администрации) в ЛЮБОЙ беседе, где он пишет: «/отчет
// К75/1» публикует отчёт СРАЗУ сюда — например в чат родителей. В канале «Отчёты · Группа»
// группу называть не нужно, она известна из самого канала.
const reportGroups = ref([])
onMounted(async () => {
  if (!['teacher', 'admin'].includes(auth.role)) return
  try {
    const all = (await messengerApi.myGroups()).data.groups || []
    reportGroups.value = (auth.role === 'admin' ? all : all.filter(g => g.curated)).map(g => g.name)
  } catch { /* не куратор — команды просто не будет */ }
})
const inReportsChannel = computed(() => activeInfo.value?.system_kind === 'curator_reports')
const canReport = computed(() => reportGroups.value.length > 0)
// §ролей: доступность /mute и /clear решает my_permissions из conversation_info — то же
// поле, что гейтит кнопки «Выгнать»/«Выдать роль» в ConversationInfo.vue.
const myPermissions = computed(() => new Set(activeInfo.value?.my_permissions || []))
const canMute = computed(() => myPermissions.value.has('cmd_mute'))
const canClear = computed(() => myPermissions.value.has('cmd_clear'))
// §ролей: игнор — по клику раскрывается ЛОКАЛЬНО (revealedIds), снова прячется повторным
// кликом; сервер тут не участвует, это личное удобство, а не приватность (как в Discord).
const myIgnoredIds = computed(() => new Set(activeInfo.value?.my_ignored_user_ids || []))
const revealedIds = ref(new Set())
function isHiddenByIgnore(msg) {
  return myIgnoredIds.value.has(msg.sender_id) && !revealedIds.value.has(msg.id)
}
function toggleReveal(id) {
  const next = new Set(revealedIds.value)
  if (next.has(id)) next.delete(id); else next.add(id)
  revealedIds.value = next
}
// По «/» показываем ВСЕ команды мессенджера, а не только годные здесь: иначе в обычном
// чате список выходил пустым, и выглядело так, будто команд нет вовсе. Недоступные
// показываем блёклыми и с причиной — сразу видно, где команда сработает.
const SLASH_COMMANDS = computed(() => [
  {
    cmd: '/vector',
    hint: 'Спросить ИИ-помощника — например: /vector когда экзамен по физике? '
      + 'Дальше отвечайте на его сообщения — префикс больше не нужен.',
    ok: isSaved.value,
    why: 'Работает в «Избранном» — это ваши личные заметки',
  },
  {
    cmd: '/отчет',
    hint: inReportsChannel.value
      ? 'Отчёт по успеваемости группы этого канала'
      : `Отчёт по успеваемости для родителей — например: /отчет ${reportGroups.value[0] || 'К74/1'}`,
    ok: canReport.value,
    why: 'Отчёт по группе выпускает её куратор или администрация',
  },
  //Отметки — тоже «команды с /»: иначе про них никто не узнает. Доступны всегда, где
  //есть кого отмечать (в «Избранном» человек один — ты сам, отмечать некого).
  {
    cmd: '/@',
    hint: 'Тихо отметить участника — например: /@Иванов (только значок «@» у него в списке)',
    ok: !isSaved.value,
    why: 'В личных заметках отмечать некого',
  },
  {
    cmd: '/@!',
    hint: 'Громко отметить — звук у собеседника и письмо во вкладку «Уведомления»',
    ok: !isSaved.value,
    why: 'В личных заметках отмечать некого',
  },
  {
    cmd: '/mute',
    hint: 'Заглушить участника в этой беседе — например: /mute @Иванов (повтор снимает)',
    ok: canMute.value,
    why: 'Право есть у владельца/админа беседы или роли с ним',
  },
  {
    cmd: '/clear',
    hint: 'Удалить последние N сообщений беседы — например: /clear 20',
    ok: canClear.value,
    why: 'Право есть у владельца/админа беседы или роли с ним',
  },
])
const slashQuery = ref(null)     // null — закрыто; иначе введённое после «/»
const slashCandidates = computed(() => {
  if (slashQuery.value === null) return []
  const q = slashQuery.value.toLowerCase()
  return SLASH_COMMANDS.value.filter((c) => c.cmd.slice(1).toLowerCase().startsWith(q))
})
function insertSlashCommand(c) {
  if (!c.ok) return          //недоступную здесь команду не подставляем — сервер её отклонит
  //Отметка склеена с именем («/@Иванов»), пробел после префикса её бы разорвал — сразу
  //за подстановкой открываем список участников, чтобы имя выбиралось, а не набиралось.
  const isMention = c.cmd.includes('@')
  draft.value = isMention ? c.cmd : c.cmd + ' '
  slashQuery.value = null
  nextTick(() => {
    composer.value?.focus()
    if (isMention) onComposerInput()
  })
}

// §D8: автодополнение отметки в композере — среди участников ЭТОЙ беседы.
// Ловим ВСЕ формы, которые понимает сервер (_parse_mentions в routers/messenger.py):
//   @Фам   — обычная (пуш есть)      /@Фам   — тихая (только значок «@»)
//   @!Фам  — тихая, старая форма     /@!Фам, /!@Фам — громкая (звук + письмо в «Систему»)
// Прежняя регулярка требовала пробел (или начало строки) ПЕРЕД «@», поэтому после «/»
// список участников не открывался вовсе — а именно так отметку и начинают набирать.
// Группа 1 — сам префикс (его сохраняем при подстановке, иначе «громко» стало бы «тихо»),
// группа 2 — уже набранные буквы имени.
const _MENTION_TOKEN_RE = /(?:^|\s)(\/?(?:@!?|!@))([A-Za-zА-Яа-яЁё]*)$/
const mentionQuery = ref(null)     // null — закрыто; иначе набранное после «@»
const mentionPrefix = ref('@')     // чем человек начал отметку — подставляем обратно как есть
const mentionStart = ref(0)        // индекс начала токена в тексте (по нему и заменяем)
let draftTimer = null
function onComposerInput() {
  m.sendTyping()
  clearTimeout(draftTimer)
  draftTimer = setTimeout(() => m.saveDraft(activeId.value, draft.value), 400)
  const el = composer.value
  if (!el) { mentionQuery.value = null; slashQuery.value = null; return }
  const pos = el.selectionStart ?? draft.value.length
  const before = draft.value.slice(0, pos)
  const at = _MENTION_TOKEN_RE.exec(before)
  if (at) {
    mentionPrefix.value = at[1]
    mentionQuery.value = at[2]
    mentionStart.value = pos - at[1].length - at[2].length
  } else {
    mentionQuery.value = null
  }
  // «/» — только пока курсор ещё в первом токене сообщения (аргумент не начат). Когда
  // «/» уже перешёл в отметку («/@…»), список команд не нужен — там своё меню.
  const slash = /^\/(\S*)$/.exec(before)
  slashQuery.value = (slash && mentionQuery.value === null) ? slash[1] : null
}
// Кого можно отметить. Раньше список показывался ТОЛЬКО в группах и каналах, и в личной
// переписке «@» просто ничего не открывал. Отмечать собеседника в ЛС осмысленно — это
// адресное «обрати внимание» в длинной ветке, и сервер такие отметки уже принимает.
// Себя из списка убираем: отметить самого себя нечем помочь (и пинг себе не уходит).
const mentionCandidates = computed(() => {
  if (mentionQuery.value === null) return []
  const q = mentionQuery.value.toLowerCase()
  const myId = activeInfo.value?.my_user_id || ''
  return (activeInfo.value?.participants || [])
    .filter(p => p.user_id !== myId)
    // Сужаем по ЛЮБОМУ слову ФИО, а не только по фамилии: человека ищут и по имени
    // («Влад…»), а раньше такой ввод давал пустой список.
    .filter(p => !q || (p.full_name || '').toLowerCase().split(/\s+/).some(w => w.startsWith(q)))
    .slice(0, 8)
})
// Что произойдёт при выбранном префиксе — та же таблица, что у сервера в _parse_mentions.
const mentionKindHint = computed(() => {
  const p = mentionPrefix.value
  if (p === '/@!' || p === '/!@') return 'Громкая отметка: звук и уведомление в «Системе»'
  if (p === '/@' || p === '@!') return 'Тихая отметка: только значок «@» в списке чатов'
  return 'Обычная отметка'
})
// Подпись справа в списке: у преподавателя — предметы, у студента — группа. Тот же
// принцип, что в карточке участника (ConversationInfo.vue::meta) — однофамильцев в
// колледже хватает, и без контекста непонятно, кого отмечаешь.
function meta(p) {
  if (p.user_role === 'teacher') return (p.subjects || []).join(', ') || 'Преподаватель'
  if (p.user_role === 'admin') return 'Администратор'
  return p.group_name || ''
}
function insertMention(p) {
  //Сервер сопоставляет отметку по ПЕРВОМУ слову ФИО — подставляем ровно его.
  const first = (p.full_name || '').trim().split(/\s+/)[0] || ''
  if (!first) return
  const el = composer.value
  const pos = el?.selectionStart ?? draft.value.length
  const start = mentionStart.value
  draft.value = draft.value.slice(0, start) + mentionPrefix.value + first + ' '
    + draft.value.slice(pos)
  mentionQuery.value = null
  slashQuery.value = null
  nextTick(() => {
    el?.focus()
    //Курсор — сразу за подставленным именем, а не в конце строки: иначе продолжение
    //фразы приходилось бы доводить мышью.
    const caret = start + mentionPrefix.value.length + first.length + 1
    el?.setSelectionRange(caret, caret)
  })
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
  //Копирование — через utils/clipboard (с фолбэком): в десктопном веб-виде и по HTTP
  //navigator.clipboard недоступен. Неудачу ПОКАЗЫВАЕМ: раньше ошибку глотал пустой
  //catch, и кнопка молча «просто нажималась».
  else if (action === 'copy') {
    if (await copyText(msg.body || '')) flashCopied()
    else m.setNotice('Не удалось скопировать: браузер не дал доступ к буферу обмена.')
  }
  else if (action === 'forward') forwardState.value = { open: true, ids: [msg.id] }
  else if (action === 'select') m.enterSelection(msg.id)
  else if (action === 'delete') requestDelete([msg])
  else if (action === 'report') reportMsg.value = msg
  else if (action === 'remind') remindMsg.value = msg
}

// §D19: напоминание о сообщении. Дату из текста разбирает сервер (детерминированно),
// диалог только показывает её и даёт поправить.
const remindMsg = ref(null)

// §D18: сводка переписки. Запускается ТОЛЬКО кнопкой — автоматический пересказ при каждом
// открытии чата стоил бы запроса к модели на каждый вход, а прочитали бы его единицы.
const summary = ref({ open: false, text: '', loading: false, note: '' })
async function openSummary() {
  summary.value = { open: true, text: '', loading: true, note: '' }
  try {
    const { data } = await messengerApi.chatSummary(activeId.value)
    if (data.summary) summary.value = { open: true, text: data.summary, loading: false, note: '' }
    else summary.value = {
      open: true, text: '', loading: false,
      // Честно говорим, ЧТО не так, вместо выдуманного пересказа.
      note: data.reason === 'too_short'
        ? 'В переписке пока слишком мало сообщений, чтобы было что пересказывать.'
        : 'ИИ-модель сейчас недоступна — сводку сделать не удалось. Настройки модели у администратора.',
    }
  } catch (e) {
    summary.value = { open: true, text: '', loading: false, note: 'Не удалось получить сводку.' }
  }
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
  m.clearDraft(activeId.value)
  const ok = await m.send(t)
  if (!ok) { draft.value = t; m.saveDraft(activeId.value, t) }   //отклонили — вернуть текст и черновик
}
function onKey(e) { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit() } }

// ── Быстрые ответы и шаблоны преподавателя (docs/MESSENGER-ADDON-PLAN-GPT.md) ───────────
// Фиксированный универсальный набор — клиент-only, без AI: короткая типовая реплика одним
// кликом, отправляется СРАЗУ (как бот-команды в Slack/Teams), а не просто вставляется.
const FIXED_QUICK_REPLIES = ['👍 Принято', 'Спасибо!', 'Хорошо', 'Понял(а)', 'Уточню и отвечу']
const showQuickReplies = ref(false)
const newTemplateText = ref('')
async function sendQuickReply(text) {
  showQuickReplies.value = false
  await m.send(text)
}
async function addTemplateFromInput() {
  const t = newTemplateText.value.trim()
  if (!t) return
  newTemplateText.value = ''
  await m.addTemplate(t)
}

// ── Треды: ответы на сообщение (переиспользует reply_to_id, см. messenger.js) ───────────
const threadParent = computed(() => messages.value.find(x => x.id === activeThread.value?.parentId) || null)
function replyInThread() {
  if (threadParent.value) m.setReply(threadParent.value)
  m.closeThread()
  nextTick(() => composer.value?.focus())
}

// ── Поиск внутри чата ────────────────────────────────────────────────────────────────
const showSearch = ref(false)
const searchQ = ref('')
let searchTimer = null
function toggleSearchPanel() {
  showSearch.value = !showSearch.value
  if (!showSearch.value) closeSearchPanel()
}
function closeSearchPanel() { showSearch.value = false; searchQ.value = ''; m.clearSearch() }
function onSearchInput() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => m.searchInActive(searchQ.value), 300)
}
function jumpToSearchResult(msg) {
  closeSearchPanel()
  jumpTo(msg.id)
}

// ── Кто прочитал сообщение (по клику, popup) — переиспользует last_read_at участников ───
const readByPopup = ref({ open: false, names: [] })
async function showReadBy(msg) {
  const users = await m.readBy(msg.id)
  readByPopup.value = { open: true, names: users.map(u => u.full_name) }
}

// ── Галочки отправлено/прочитано в ЛС (как в Telegram) ──────────────────────────────────
// В группах/каналах читателей несколько — там смысла в одной галочке нет, оставляем
// попап «Кто прочитал» (см. выше). В ЛС читатель ровно один — сравниваем время своего
// сообщения с last_read_at собеседника, которое уже приходит в activeInfo.participants
// (см. server/app/routers/messenger.py::conversation_info) — без похода на сервер за каждым тиком.
const peerLastReadAt = computed(() => {
  if (kind.value !== 'direct' || !activePeer.value?.id) return ''
  const p = (activeInfo.value?.participants || []).find(x => x.user_id === activePeer.value.id)
  return p?.last_read_at || ''
})
function isReadByPeer(msg) {
  return !!(peerLastReadAt.value && msg.created_at <= peerLastReadAt.value)
}

function jumpTo(id) {
  const el = document.getElementById(`gb-msg-${id}`)
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' })
}

// ── Отметки: перемотка к сообщению, где меня упомянули ────────────────────────────────
// Само сообщение приходит в строке списка чатов (mention_message_id) — сервер уже нашёл
// самое РАННЕЕ непрочитанное упоминание, второй раз искать его на клиенте незачем.
const mentionMessageId = computed(() => activeChat.value?.mention_message_id || 0)
const mentionLoud = computed(() => !!activeChat.value?.mention_loud)
const flashMentionId = ref(0)
function jumpToMention() {
  const id = mentionMessageId.value
  if (!id) return
  jumpTo(id)
  // Подсветка на пару секунд: без неё после прокрутки непонятно, какое именно сообщение
  // искали — в плотной переписке центр экрана ни на что не указывает.
  flashMentionId.value = id
  setTimeout(() => { if (flashMentionId.value === id) flashMentionId.value = 0 }, 2500)
}

// «Избранное» — личный блокнот, а не переписка: ни собеседника, ни его статуса тут нет.
const isSaved = computed(() => kind.value === 'saved')
const peerName = computed(() => {
  if (isSaved.value) return 'Избранное'
  if (isModeration.value) return 'Модерация'
  if (isGroupOrChannel.value) return activeInfo.value?.title || activePeer.value?.full_name || 'Беседа'
  return activePeer.value?.full_name || 'Диалог'
})
// §D7: подпись статуса поверх presence (dnd/studying/away + текст преподавателя).
const STATUS_RU = { dnd: 'Не беспокоить', studying: 'Готовится/учится', away: 'Отошёл(а)' }
const subtitle = computed(() => {
  //Свой блокнот: показывать «в сети»/роль бессмысленно — это ты сам.
  if (isSaved.value) return 'Заметки только для вас'
  if (isModeration.value) return 'Официальная поддержка'
  if (peerTyping.value) return 'печатает…'
  if (kind.value === 'channel') return `${activeInfo.value?.subscribers || 0} подписчиков`
  if (kind.value === 'group') return `${activeInfo.value?.subscribers || 0} участников`
  const sk = activePeer.value?.status_kind
  if (sk) return activePeer.value?.status_text || STATUS_RU[sk] || sk
  return activePeer.value?.online ? 'в сети' : 'был(а) недавно'
})
const topPinned = computed(() => pinned.value[0] || null)
//Подсказка в поле ввода: разметку показывают кнопки тулбара, поэтому в ней только то,
//что иначе не найти — команда Вектора, и лишь в «Избранном», где она и работает.
const composerHint = computed(() => {
  if (replyingToVector.value) return 'Спросите Вектора дальше…'
  return isSaved.value ? 'Заметка… (/vector — спросить ИИ)' : 'Сообщение…'
})

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
// Ответы Вектора приходят от служебного отправителя 'system'. Его нет в справочнике
// пользователей, поэтому подпись и аватар подставлялись от СОБЕСЕДНИКА — в «Избранном»
// это ты сам, и ответ ИИ выглядел как твоё же сообщение с твоей аватаркой.
const VECTOR_SENDER = 'system'
const VECTOR_AVATAR = '/mascot/neutral-idle.png'   //арт Арины, кадрируем по голове
function isVector(msg) { return msg.sender_id === VECTOR_SENDER }
//Отвечаем на реплику Вектора → это продолжение разговора с ним, а не обычная цитата.
const replyingToVector = computed(() => isSaved.value && !!replyTo.value && isVector(replyTo.value))
function senderAvatar(msg) {
  if (isVector(msg)) return VECTOR_AVATAR
  return avatarBySender.value[msg.sender_id] ?? (msg.mine ? '' : (activePeer.value?.avatar || ''))
}
function senderName(msg) {
  if (isVector(msg)) return 'Вектор'
  return msg.sender_name || (isSaved.value ? '' : (activePeer.value?.full_name || ''))
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
        <!-- Поиск внутри чата (docs/MESSENGER-ADDON-PLAN-GPT-SMART.md §3.1). -->
        <button type="button" @click="toggleSearchPanel"
                aria-label="Поиск по чату" title="Поиск по чату"
                class="grid size-8 shrink-0 place-items-center rounded-md"
                :class="headerTint ? 'text-white/80 hover:bg-white/15 hover:text-white'
                  : (showSearch ? 'text-accent hover:bg-bg2' : 'text-text3 hover:bg-bg2 hover:text-text')">
          <Search class="size-5" />
        </button>
        <!-- §D18: сводка переписки — ТОЛЬКО по кнопке. Автоматический пересказ при каждом
             открытии чата означал бы запрос к модели на каждый вход. -->
        <button type="button" @click="openSummary"
                aria-label="Краткая сводка переписки" title="Краткая сводка переписки"
                class="grid size-8 shrink-0 place-items-center rounded-md"
                :class="headerTint ? 'text-white/80 hover:bg-white/15 hover:text-white'
                  : 'text-text3 hover:bg-bg2 hover:text-text'">
          <ScrollText class="size-5" />
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

      <!-- Поиск внутри чата: строка + результаты (без встроенного скролла к старым — если
           сообщение уже не подгружено в ленту, просто показываем его текст здесь). -->
      <div v-if="showSearch" class="shrink-0 border-b border-border bg-card">
        <div class="flex items-center gap-2 px-3 py-2">
          <Search class="size-4 shrink-0 text-text3" />
          <input v-model="searchQ" @input="onSearchInput" autofocus placeholder="Поиск по смыслу…"
                 class="h-8 min-w-0 flex-1 bg-transparent text-sm text-text outline-none" />
          <button type="button" @click="closeSearchPanel" aria-label="Закрыть поиск"
                  class="grid size-7 shrink-0 place-items-center rounded-md text-text3 hover:bg-bg2"><X class="size-4" /></button>
        </div>
        <!-- Показываем, чем модель дополнила запрос: иначе непонятно, почему нашлось
             сообщение, в котором искомого слова нет. -->
        <p v-if="searchExpanded.length && searchQ.trim()"
           class="border-t border-border px-3 py-1.5 text-[11px] text-text3">
          Ищем также: {{ searchExpanded.join(', ') }}
        </p>
        <div v-if="searchQ.trim()" class="max-h-56 overflow-y-auto border-t border-border">
          <p v-if="searching" class="p-3 text-center text-xs text-text3">Ищем…</p>
          <p v-else-if="!searchResults?.length" class="p-3 text-center text-xs text-text3">Ничего не найдено.</p>
          <button v-for="r in searchResults" :key="r.id" type="button" @click="jumpToSearchResult(r)"
                  class="flex w-full flex-col items-start gap-0.5 border-b border-border/50 px-3 py-2 text-left hover:bg-bg2">
            <span class="text-[11px] font-semibold text-accent">{{ r.sender_name || (r.mine ? 'Вы' : '') }} · {{ fmtTime(r.created_at) }}</span>
            <span class="line-clamp-2 text-sm text-text">{{ r.body }}</span>
          </button>
        </div>
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
      <!-- Обёртка relative — плавающая кнопка «вниз» позиционируется absolute ОТНОСИТЕЛЬНО
           этой области (а не всей секции чата, где съезжала бы на композер). -->
      <div class="relative min-h-0 flex-1">
      <div ref="scroller" class="h-full overflow-y-auto px-3 py-4" @scroll="onScrollerScroll">
        <template v-for="msg in messages" :key="msg.id">
          <!-- Разделитель по датам — над «Новые сообщения», если оба совпали на одном msg. -->
          <div v-if="dateBreaks.has(msg.id)" class="my-3 flex justify-center">
            <span class="rounded-full bg-card2 px-3 py-1 text-[11px] font-semibold text-text3">{{ dateBreaks.get(msg.id) }}</span>
          </div>
          <!-- §D5: разделитель «Новые сообщения» — перед первым непрочитанным на момент открытия. -->
          <div v-if="msg.id === firstUnreadId" class="my-3 flex items-center gap-3 text-xs font-semibold text-accent">
            <span class="h-px flex-1 bg-accent/40" /> Новые сообщения <span class="h-px flex-1 bg-accent/40" />
          </div>

          <!-- §D6: системное сообщение — центрированная строка, не пузырь. -->
          <div v-if="msg.kind === 'system'" :id="`gb-msg-${msg.id}`" class="my-1.5 text-center text-xs text-text3">
            {{ formatSystemMessage(msg.body) }}
          </div>

          <!-- §12: кнопка «Отчёт №N» куратора. Группу и дату границы пишем НА кнопке:
               без них подряд лежащие отчёты неразличимы, и непонятно, сработала ли
               команда — куратор жал «/отчет» ещё раз и плодил дубли. -->
          <div v-else-if="msg.kind === 'report' && msg.report" :id="`gb-msg-${msg.id}`"
               class="my-1 flex" :class="msg.mine ? 'justify-end' : 'justify-start'">
            <button type="button" @click="openReportOverlay = msg.report.id"
                    class="flex items-center gap-2 rounded-2xl border border-border2 bg-card px-4 py-2 text-sm font-semibold text-accent shadow-sm hover:bg-bg2">
              <PieChart class="size-4 shrink-0" />
              <span class="flex flex-col items-start leading-tight">
                <span>Отчёт №{{ msg.report.seq }}<span v-if="msg.report.group" class="text-text2"> · {{ msg.report.group }}</span></span>
                <span class="text-[11px] font-medium text-text3">
                  {{ msg.report.cutoff_date ? `на ${msg.report.cutoff_date}` : 'успеваемость группы' }}
                  · {{ fmtTime(msg.created_at) }}
                </span>
              </span>
              <span v-if="msg.report.archived" class="rounded-full bg-bg2 px-1.5 py-0.5 text-[10px] font-medium text-text3">Архив</span>
            </button>
          </div>

          <div v-else :id="`gb-msg-${msg.id}`"
               class="flex items-end gap-2"
               :class="[msg.mine ? 'justify-end' : 'justify-start',
                        runStarts.has(msg.id) ? 'mt-4 first:mt-0' : 'mt-0.5']">
            <input v-if="selectionMode" type="checkbox" :checked="selectedIds.includes(msg.id)"
                   @change="m.toggleSelect(msg.id)" class="order-first accent-[var(--gb-accent)]" />
            <!-- Аватарка собеседника — только у верхнего сообщения пачки; ниже держим отступ. -->
            <div v-if="!msg.mine" class="w-8 shrink-0">
              <Avatar v-if="runStarts.has(msg.id)" :src="senderAvatar(msg)"
                      :name="senderName(msg)" :size="32"
                      :position="isVector(msg) ? 'top' : 'center'" />
            </div>
            <!-- div, а не button: внутри есть свои интерактивные элементы (реакции) —
                 кнопка-в-кнопке невалидна. Жесты (клик/ПКМ/тач) не завязаны на семантику тега. -->
            <div role="button" tabindex="0" @click="onMessageClick(msg)"
                 @keydown.enter="onMessageClick(msg)"
                 @contextmenu="onContextMenu(msg, $event)"
                 @touchstart.passive="onTouchStart(msg, $event)"
                 @touchmove.passive="onTouchMove($event)"
                 @touchend="onTouchEnd" @touchcancel="onTouchEnd"
                 class="max-w-[75%] select-none rounded-2xl px-3 py-1.5 text-left text-sm shadow-sm outline-none transition-shadow hover:shadow"
                 :class="[msg.mine ? 'bg-accent text-white' : 'bg-card text-text',
                          flashMentionId === msg.id ? 'ring-2 ring-accent' : '']"
                 :style="swipe.id === msg.id ? `transform: translateX(${swipe.dx}px)` : ''">
              <!-- ФИО автора — у верхнего сообщения пачки (в своих не нужно). -->
              <div v-if="!msg.mine && runStarts.has(msg.id) && senderName(msg)"
                   class="mb-0.5 text-[11px] font-semibold text-accent">
                {{ senderName(msg) }}
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
              <!-- §ролей: игнор — ЛИЧНОЕ, не модерация; сервер текст отдаёт как обычно,
                   прячем и раскрываем на клиенте (клик по плейсхолдеру). -->
              <button v-else-if="isHiddenByIgnore(msg)" type="button" @click.stop="toggleReveal(msg.id)"
                      class="italic opacity-70 underline decoration-dotted">Скрыто (игнор) — показать</button>
              <!-- §D1: Markdown-lite (текст экранирован ДО рендера — см. utils/markdownLite). -->
              <div v-else class="msg-body whitespace-pre-wrap break-words" v-html="renderBody(msg)" />
              <span class="ml-2 align-bottom text-[10px]" :class="msg.mine ? 'text-white/70' : 'text-text3'">
                <Pin v-if="msg.pinned" class="mr-0.5 inline size-2.5" />
                <!-- §D11: «изм.» кликабельно — открывает историю версий. -->
                <button v-if="msg.edited_at" type="button" @click.stop="openHistory(msg)"
                        class="underline decoration-dotted hover:opacity-80">изм.</button>
                {{ fmtTime(msg.created_at) }}
                <!-- ЛС: галочки отправлено/прочитано (как в Telegram). -->
                <template v-if="msg.mine && kind === 'direct'">
                  <CheckCheck v-if="isReadByPeer(msg)" title="Прочитано" class="ml-0.5 inline size-3" />
                  <Check v-else title="Отправлено" class="ml-0.5 inline size-3 opacity-70" />
                </template>
                <!-- Группа/канал: читателей несколько — попап со списком (см. showReadBy). -->
                <button v-else-if="msg.mine" type="button" @click.stop="showReadBy(msg)" title="Кто прочитал"
                        class="ml-0.5 inline-flex align-middle hover:opacity-80"><Eye class="size-2.5" /></button>
              </span>

              <!-- §D3: пилюли реакций — клик по своей снимает её, по чужой добавляет ту же. -->
              <div v-if="msg.reactions?.length" class="mt-1 flex flex-wrap gap-1">
                <button v-for="r in msg.reactions" :key="r.emoji" type="button"
                        @click.stop="onReactionClick(msg, r.emoji)"
                        class="flex items-center gap-1 rounded-full border px-1.5 py-0.5 text-xs transition-colors"
                        :class="r.mine
                          ? (msg.mine ? 'border-white/50 bg-white/20' : 'border-accent bg-accent-glow text-accent')
                          : (msg.mine ? 'border-white/30 hover:bg-white/10' : 'border-border2 hover:bg-bg2')">
                  {{ r.emoji }} {{ r.count }}
                </button>
              </div>

              <!-- Треды: «N ответов» — открывает панель с ответами (reply_to_id), не
                   загромождая основную ленту (docs/MESSENGER-ADDON-PLAN-GPT-SMART.md §3.3). -->
              <button v-if="msg.reply_count" type="button" @click.stop="m.openThread(msg.id)"
                      class="mt-1 flex items-center gap-1 text-xs font-semibold hover:underline"
                      :class="msg.mine ? 'text-white/90' : 'text-accent'">
                <MessageSquare class="size-3" />{{ msg.reply_count }} {{ msg.reply_count === 1 ? 'ответ' : 'ответа' }}
              </button>
            </div>
          </div>
        </template>
      </div>

      <!-- Кнопка «@» — НАД стрелкой вниз: перематывает к сообщению, где вас отметили.
           Нужна именно отдельная кнопка: отметка легко теряется в переписке, а «вниз»
           уводит в конец — то есть мимо неё. Видна, пока отметка не прочитана. -->
      <transition name="fade">
        <button v-if="mentionMessageId" type="button" @click="jumpToMention"
                aria-label="К сообщению, где вас отметили" title="Вас отметили — перейти"
                class="absolute bottom-16 right-3 grid size-10 place-items-center rounded-full border text-lg font-bold shadow-card"
                :class="mentionLoud
                  ? 'border-red/50 bg-red text-white hover:opacity-90'
                  : 'border-border2 bg-card text-accent hover:bg-bg2'">
          @
        </button>
      </transition>

      <!-- §D5: плавающая кнопка «вниз» с числом непрочитанных — видна, когда прокручено вверх.
           Вне scroller (в relative-обёртке) — не уезжает вместе с содержимым при скролле. -->
      <transition name="fade">
        <button v-if="showScrollBtn" type="button" @click="scrollDown"
                aria-label="К последним сообщениям"
                class="absolute bottom-3 right-3 grid size-10 place-items-center rounded-full border border-border2 bg-card shadow-card hover:bg-bg2">
          <ChevronDown class="size-5 text-text2" />
          <span v-if="activeChat?.unread" class="absolute -top-1.5 -right-1.5 grid h-5 min-w-5 place-items-center rounded-full bg-accent px-1 text-[10px] font-bold text-white">
            {{ activeChat.unread }}
          </span>
        </button>
      </transition>
      </div>

      <!-- §D2: Вектор с репликой вместо холодного 429 — композер блокируется на remaining c. -->
      <MascotCooldown v-if="mascotCooldown.active" :cooldown="mascotCooldown" />

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
              <!-- Ответ на реплику Вектора — это следующий вопрос ему же (сервер разберёт
                   его без префикса «/vector», см. _handle_vector_command). Подписываем
                   явно: иначе непонятно, что цепочка продолжится, и человек снова пишет
                   «/vector». -->
              <div class="text-[11px] font-semibold text-accent">
                {{ replyingToVector ? 'Вопрос Вектору — можно без «/vector»' : 'Ответ' }}
              </div>
              <div class="truncate text-xs text-text3">{{ replyTo.deleted ? 'Сообщение удалено' : replyTo.body }}</div>
            </div>
            <button type="button" @click="m.clearReply()" aria-label="Отменить ответ"
                    class="grid size-6 place-items-center rounded-md text-text3 hover:bg-bg2"><X class="size-4" /></button>
          </div>
          <!-- §D1: тулбар форматирования — оборачивает выделение в поле ввода. На мобиле
               (узкий экран) прячем, чтобы не съедал место — там достаточно ручного синтаксиса. -->
          <div class="hidden items-center gap-0.5 border-b border-border px-2 py-1 sm:flex">
            <button type="button" title="Жирный (Ctrl+B)" @click="wrapSelection('**')"
                    class="grid size-7 place-items-center rounded-md text-text3 hover:bg-bg2 hover:text-text"><Bold class="size-4" /></button>
            <button type="button" title="Курсив (Ctrl+I)" @click="wrapSelection('*')"
                    class="grid size-7 place-items-center rounded-md text-text3 hover:bg-bg2 hover:text-text"><Italic class="size-4" /></button>
            <button type="button" title="Подчёркнутый (Ctrl+U)" @click="wrapSelection('__')"
                    class="grid size-7 place-items-center rounded-md text-text3 hover:bg-bg2 hover:text-text"><Underline class="size-4" /></button>
            <button type="button" title="Зачёркнутый" @click="wrapSelection('~~')"
                    class="grid size-7 place-items-center rounded-md text-text3 hover:bg-bg2 hover:text-text"><Strikethrough class="size-4" /></button>
            <button type="button" title="Код" @click="wrapSelection('`')"
                    class="grid size-7 place-items-center rounded-md text-text3 hover:bg-bg2 hover:text-text"><Code class="size-4" /></button>
            <button type="button" title="Цитата" @click="wrapSelection('> ', '')"
                    class="grid size-7 place-items-center rounded-md text-text3 hover:bg-bg2 hover:text-text"><Quote class="size-4" /></button>
            <span class="mx-1 h-4 w-px bg-border2" />
            <!-- Быстрые ответы/шаблоны (docs/MESSENGER-ADDON-PLAN-GPT.md) — канонические
                 фразы одним кликом, отправляются СРАЗУ. -->
            <button type="button" title="Быстрые ответы" @click="showQuickReplies = !showQuickReplies"
                    class="grid size-7 place-items-center rounded-md text-text3 hover:bg-bg2 hover:text-text"
                    :class="{ 'bg-bg2 text-accent': showQuickReplies }"><Zap class="size-4" /></button>
          </div>
          <!-- Автодополнение слэш-команд (как в Telegram) — список + краткое пояснение. -->
          <div v-if="slashCandidates.length" class="border-b border-border p-1.5">
            <button v-for="c in slashCandidates" :key="c.cmd" type="button"
                    @mousedown.prevent="insertSlashCommand(c)"
                    class="flex w-full flex-col items-start gap-0.5 rounded-md px-2 py-1.5 text-left"
                    :class="c.ok ? 'hover:bg-bg2' : 'cursor-default opacity-50'">
              <span class="text-sm font-semibold" :class="c.ok ? 'text-accent' : 'text-text3'">{{ c.cmd }}</span>
              <span class="text-xs text-text3">{{ c.ok ? c.hint : c.why }}</span>
            </button>
          </div>
          <!-- §D8: подсказки отметки — участники ЭТОЙ беседы (в ЛС это вы и собеседник). -->
          <div v-if="mentionCandidates.length" class="border-b border-border p-1.5">
            <!-- Подпись «какой это будет пинг»: по одному «!» в наборе понять нельзя,
                 а разница слышимая — громкий звонит человеку и пишет ему в «Систему». -->
            <p class="px-2 pb-1 text-[11px] text-text3">{{ mentionKindHint }}</p>
            <button v-for="p in mentionCandidates" :key="p.user_id" type="button"
                    @mousedown.prevent="insertMention(p)"
                    class="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm text-text hover:bg-bg2">
              <Avatar :src="p.avatar" :name="p.full_name" :size="24" />
              <span class="min-w-0 flex-1 truncate">{{ p.full_name }}</span>
              <span class="shrink-0 text-[11px] text-text3">{{ meta(p) }}</span>
            </button>
          </div>
          <!-- Панель быстрых ответов: фиксированный универсальный набор + (препод/админ)
               личные шаблоны с возможностью добавить/удалить свой. -->
          <div v-if="showQuickReplies" class="border-b border-border p-2">
            <div class="flex flex-wrap gap-1.5">
              <button v-for="txt in FIXED_QUICK_REPLIES" :key="txt" type="button" @click="sendQuickReply(txt)"
                      class="rounded-full border border-border2 px-2.5 py-1 text-xs text-text hover:bg-bg2">{{ txt }}</button>
              <button v-for="t in templates" :key="t.id" type="button" @click="sendQuickReply(t.body)"
                      class="group flex items-center gap-1 rounded-full border border-border2 px-2.5 py-1 text-xs text-text hover:bg-bg2">
                {{ t.body }}
                <span v-if="canManageTemplates" role="button" tabindex="0" @click.stop="m.removeTemplate(t.id)"
                      class="text-text3 opacity-0 hover:text-red group-hover:opacity-100">×</span>
              </button>
            </div>
            <form v-if="canManageTemplates" class="mt-1.5 flex items-center gap-1.5" @submit.prevent="addTemplateFromInput">
              <input v-model="newTemplateText" placeholder="Свой шаблон (напр. «Работа принята»)…"
                     class="h-7 min-w-0 flex-1 rounded-md border border-border2 bg-card2 px-2 text-xs text-text outline-none focus:border-accent" />
              <button type="submit" :disabled="!newTemplateText.trim()" aria-label="Добавить шаблон"
                      class="grid size-7 shrink-0 place-items-center rounded-md bg-accent text-white disabled:opacity-40"><Plus class="size-3.5" /></button>
            </form>
          </div>
          <form class="flex items-end gap-2 p-2.5" @submit.prevent="submit">
            <!-- Разметку подсказывать не нужно: над полем есть кнопки B/I/U/S/код/цитата.
               Про /vector говорим только там, где команда работает — в «Избранном». -->
          <textarea ref="composer" v-model="draft" rows="1" :placeholder="composerHint"
                      @keydown="onComposerKeydown" @input="onComposerInput" :disabled="mascotCooldown.active"
                      class="max-h-32 min-h-[40px] min-w-0 flex-1 resize-none rounded-lg border border-border2 bg-card2 px-3 py-2 text-sm text-text outline-none focus:border-accent focus:bg-card disabled:opacity-60" />
            <button type="submit" :disabled="!draft.trim() || sending || mascotCooldown.active" aria-label="Отправить"
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

    <!-- Треды: ответы на сообщение (docs/MESSENGER-ADDON-PLAN-GPT-SMART.md §3.3) -->
    <div v-if="activeThread" class="fixed inset-0 z-50 grid place-items-center p-4"
         style="background: var(--gb-overlay)" @click.self="m.closeThread()">
      <div class="flex max-h-[80vh] w-full max-w-sm flex-col rounded-xl border border-border2 bg-card p-4 shadow-card">
        <div class="mb-2 flex items-center gap-2">
          <MessageSquare class="size-4 text-accent" />
          <h3 class="flex-1 font-title text-sm font-bold text-text">Ответы</h3>
          <button type="button" @click="m.closeThread()" aria-label="Закрыть"
                  class="grid size-7 place-items-center rounded-md text-text3 hover:bg-bg2"><X class="size-4" /></button>
        </div>
        <div v-if="threadParent" class="mb-2 rounded-md border-l-2 border-accent bg-bg2 px-3 py-2 text-xs text-text2">
          {{ threadParent.deleted ? 'Сообщение удалено' : threadParent.body }}
        </div>
        <div class="min-h-0 flex-1 space-y-2 overflow-y-auto">
          <div v-for="r in activeThread.messages" :key="r.id" class="rounded-md bg-bg2 px-3 py-2 text-sm">
            <div class="mb-0.5 text-[11px] font-semibold text-accent">{{ r.sender_name || (r.mine ? 'Вы' : '') }} · {{ fmtTime(r.created_at) }}</div>
            <div class="text-text">{{ r.deleted ? 'Сообщение удалено' : r.body }}</div>
          </div>
          <p v-if="!activeThread.messages.length" class="p-2 text-center text-xs text-text3">Пока нет ответов.</p>
        </div>
        <button type="button" @click="replyInThread"
                class="mt-3 w-full rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white hover:bg-accent2">Ответить</button>
      </div>
    </div>

    <!-- §D18: сводка переписки -->
    <div v-if="summary.open" class="fixed inset-0 z-50 grid place-items-center p-4"
         style="background: var(--gb-overlay)" @click.self="summary.open = false">
      <div class="flex max-h-[80vh] w-full max-w-md flex-col rounded-xl border border-border2 bg-card p-4 shadow-card">
        <div class="mb-2 flex items-center gap-2">
          <ScrollText class="size-4 text-accent" />
          <h3 class="flex-1 font-title text-sm font-bold text-text">Краткая сводка</h3>
          <button type="button" @click="summary.open = false" aria-label="Закрыть"
                  class="grid size-7 place-items-center rounded-md text-text3 hover:bg-bg2"><X class="size-4" /></button>
        </div>
        <p v-if="summary.loading" class="py-6 text-center text-sm text-text3">Читаем переписку…</p>
        <p v-else-if="summary.note" class="py-4 text-sm text-text3">{{ summary.note }}</p>
        <div v-else class="min-h-0 flex-1 overflow-y-auto whitespace-pre-line text-sm leading-relaxed text-text">
          {{ summary.text }}
        </div>
        <p v-if="summary.text" class="mt-3 border-t border-border pt-2 text-[11px] text-text3">
          Составлено ИИ по переписке. Имена обезличены перед отправкой в модель.
        </p>
      </div>
    </div>

    <!-- §D19: напоминание о сообщении -->
    <ReminderDialog v-if="remindMsg" :message="remindMsg" @close="remindMsg = null" />

    <!-- Кто прочитал сообщение -->
    <div v-if="readByPopup.open" class="fixed inset-0 z-50 grid place-items-center p-4"
         style="background: var(--gb-overlay)" @click.self="readByPopup.open = false">
      <div class="w-full max-w-xs rounded-xl border border-border2 bg-card p-4 shadow-card">
        <div class="mb-2 flex items-center gap-2">
          <Eye class="size-4 text-accent" />
          <h3 class="font-title text-sm font-bold text-text">Прочитали</h3>
        </div>
        <p v-if="!readByPopup.names.length" class="text-sm text-text3">Пока никто не прочитал.</p>
        <ul v-else class="space-y-1 text-sm text-text">
          <li v-for="(n, i) in readByPopup.names" :key="i">{{ n }}</li>
        </ul>
        <button type="button" @click="readByPopup.open = false"
                class="mt-3 w-full rounded-lg border border-border2 px-4 py-2 text-sm text-text2 hover:bg-bg2">Закрыть</button>
      </div>
    </div>

    <!-- Оверлей действий -->
    <MessageActionsOverlay v-if="overlay.open" :message="overlay.message" :x="overlay.x" :y="overlay.y"
                           @pick="onPick" @react="onReact" @close="overlay.open = false" />

    <!-- §D11: история редактирования сообщения -->
    <div v-if="historyPopup.open" class="fixed inset-0 z-50 grid place-items-center p-4"
         style="background: var(--gb-overlay)" @click.self="historyPopup.open = false">
      <div class="w-full max-w-sm rounded-xl border border-border2 bg-card p-4 shadow-card">
        <div class="mb-2 flex items-center gap-2">
          <History class="size-4 text-accent" />
          <h3 class="font-title text-sm font-bold text-text">История изменений</h3>
        </div>
        <div class="max-h-72 space-y-2 overflow-y-auto">
          <div v-for="(v, i) in historyPopup.versions" :key="i"
               class="rounded-md border border-border bg-bg2 px-3 py-2 text-sm">
            <div class="mb-0.5 text-[11px] text-text3">
              {{ fmtFull(v.at) }}{{ v.current ? ' · текущая версия' : '' }}
            </div>
            <div class="text-text">{{ v.body }}</div>
          </div>
        </div>
        <button type="button" @click="historyPopup.open = false"
                class="mt-3 w-full rounded-lg border border-border2 px-4 py-2 text-sm text-text2 hover:bg-bg2">Закрыть</button>
      </div>
    </div>

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
    <!-- §12: оверлей отчёта куратора (круговая + плоские по предметам + дрилл-даун). -->
    <CuratorReportOverlay v-if="openReportOverlay" :report-id="openReportOverlay" @close="openReportOverlay = null" />
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

/* §D1: оформление Markdown-lite внутри пузыря сообщения (см. utils/markdownLite.js). */
.msg-body :deep(strong) { font-weight: 700; }
.msg-body :deep(em) { font-style: italic; }
.msg-body :deep(u) { text-decoration: underline; }
.msg-body :deep(s) { text-decoration: line-through; opacity: 0.75; }
.msg-body :deep(code) {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  background: rgba(0, 0, 0, 0.12);
  padding: 1px 5px; border-radius: 4px; font-size: 0.88em;
}
.msg-body :deep(pre) {
  background: rgba(0, 0, 0, 0.12);
  padding: 8px 12px; border-radius: 8px; overflow-x: auto;
  margin: 4px 0; font-size: 0.85em;
}
.msg-body :deep(pre code) { background: none; padding: 0; }
.msg-body :deep(blockquote) {
  border-left: 3px solid currentColor;
  margin: 4px 0; padding: 2px 10px; opacity: 0.85;
}
.msg-body :deep(h1) { font-size: 1.3em; font-weight: 800; margin: 4px 0 2px; }
.msg-body :deep(h2) { font-size: 1.15em; font-weight: 700; margin: 4px 0 2px; }
.msg-body :deep(ul) { margin: 2px 0 2px 1.1em; list-style: disc; }
/* §D8: подсветка упоминаний — заметно, но не спорит с цветом текста своих/чужих пузырей. */
.msg-body :deep(.mention) { font-weight: 700; text-decoration: underline; text-underline-offset: 2px; }
</style>
