<script setup>
// ChatList — левая колонка навигации (стиль Telegram): поиск по ФИО, вкладки
// «Чаты / Преподаватели / Студенты / Каналы», кнопка «+» (новая группа/канал). Клик по
// чату открывает переписку; по человеку — личный чат; по каналу — вступление/открытие.
import { ref, computed, watch, onMounted } from 'vue'
import { storeToRefs } from 'pinia'
import { Search, Plus, Users, Radio, Megaphone, Star, Archive, MoreVertical, Pin, PinOff, ArchiveRestore } from '@lucide/vue'
import { useMessengerStore } from '@/stores/messenger'
import { useAuthStore } from '@/stores/auth'
import CreateChatDialog from './CreateChatDialog.vue'
import MyStatusPicker from './MyStatusPicker.vue'
import Avatar from '@/components/ui/Avatar.vue'

const m = useMessengerStore()
const auth = useAuthStore()
const { chats, dir, channels, activeId, loadingChats } = storeToRefs(m)
// Группы и каналы создают ТОЛЬКО преподаватели (и админ) — у студента кнопку «+» прячем
// (сервер тоже вернёт 403, см. create_group/create_channel). Личные чаты студенту доступны.
const canCreate = computed(() => ['teacher', 'admin'].includes(auth.role))

const tab = ref('chats')            // chats | teacher | student | channels | archive
const q = ref('')
const showNew = ref(false)
const createKind = ref('')          // '' | group | channel
const menuFor = ref('')             // conversation_id чата, у которого открыто меню ⋮
let debounce = null

function initials(name) {
  const p = (name || '').trim().split(/\s+/)
  return ((p[0]?.[0] || '') + (p[1]?.[0] || '')).toUpperCase() || '?'
}
function fmtTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const today = new Date()
  return d.toDateString() === today.toDateString()
    ? d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
    : d.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' })
}

// «Чаты» — без архивных (у них отдельная вкладка) и без «Избранного» (оно — отдельной
// закреплённой строкой сверху, как Saved Messages в Telegram, а не в общем списке).
const archivedCount = computed(() => chats.value.filter(c => c.archived).length)
const savedChat = computed(() => chats.value.find(c => c.kind === 'saved') || null)
const shownChats = computed(() => {
  const ql = q.value.trim().toLowerCase()
  const base = chats.value.filter(c => c.kind !== 'saved' &&
    (tab.value === 'archive' ? c.archived : !c.archived))
  return ql ? base.filter(c => (c.title || '').toLowerCase().includes(ql)) : base
})

function refresh() {
  if (tab.value === 'teacher' || tab.value === 'student') m.searchUsers(tab.value, q.value)
  else if (tab.value === 'channels') m.loadChannels(q.value)
}
watch(tab, refresh)
watch(q, () => {
  if (tab.value === 'chats' || tab.value === 'archive') return
  clearTimeout(debounce)
  debounce = setTimeout(refresh, 300)
})

function startCreate(kind) { showNew.value = false; createKind.value = kind }

// §D12: канал «Объявления · Группа» — существующие читатели уже подписаны (студенты
// группы), пост уходит обычным send() дальше в ChatThread. Ввод группы — простым prompt,
// пока в мессенджере нет отдельного выбора «мои группы» (см. журнал/расписание за списком).
async function openAnnouncements() {
  showNew.value = false
  const group = window.prompt('Название группы для объявлений (например, К-24):')
  if (group) await m.openAnnouncementsChannel(group)
}
async function onCreate(payload) {
  const kind = createKind.value
  createKind.value = ''
  if (kind === 'group') await m.createGroup(payload.title, payload.ids, payload.about)
  else await m.createChannel(payload.title, payload.ids, payload.isPublic, payload.about)
}

// Меню «⋮» на строке чата: закрепить/открепить, в архив/из архива. Личное состояние —
// докладов о собеседнике/канале это не требует (см. docs/MESSENGER-ADDON-PLAN-GPT*.md).
function toggleMenu(convId) { menuFor.value = menuFor.value === convId ? '' : convId }
async function onPin(chat) { menuFor.value = ''; await m.togglePinChat(chat.conversation_id, !chat.pinned) }
async function onArchive(chat) { menuFor.value = ''; await m.toggleArchiveChat(chat.conversation_id, !chat.archived) }

onMounted(() => { m.loadChats() })
</script>

<template>
  <!-- На мобилке при открытом чате прячем список — иначе он (w-full) перекрывает тред, и
       по тапу «ничего не происходит». С sm — обе колонки видны рядом. -->
  <aside class="h-full w-full flex-col border-r border-border bg-card sm:w-80 sm:shrink-0"
         :class="activeId ? 'hidden sm:flex' : 'flex'">
    <!-- Поиск + «Новый» -->
    <div class="shrink-0 border-b border-border p-2.5">
      <div class="flex items-center gap-2">
        <div class="flex flex-1 items-center gap-2 rounded-lg border border-border2 bg-card2 px-3">
          <Search class="size-4 shrink-0 text-text3" />
          <input v-model="q" placeholder="Поиск по ФИО…"
                 class="h-9 min-w-0 flex-1 bg-transparent text-sm text-text outline-none" />
        </div>
        <div v-if="canCreate" class="relative">
          <button type="button" @click="showNew = !showNew" aria-label="Создать"
                  class="grid size-9 place-items-center rounded-lg bg-accent text-white hover:bg-accent2"><Plus class="size-5" /></button>
          <div v-if="showNew" class="absolute right-0 top-full z-20 mt-1 w-44 overflow-hidden rounded-lg border border-border2 bg-card py-1 shadow-card">
            <button type="button" @click="startCreate('group')" class="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-text hover:bg-bg2"><Users class="size-4 text-text3" />Новая группа</button>
            <button type="button" @click="startCreate('channel')" class="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-text hover:bg-bg2"><Radio class="size-4 text-text3" />Новый канал</button>
            <!-- §D12: авто-канал «Объявления · Группа» — студенты группы уже читатели. -->
            <button type="button" @click="openAnnouncements" class="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-text hover:bg-bg2"><Megaphone class="size-4 text-text3" />Объявления группы</button>
          </div>
        </div>
      </div>
      <div class="mt-2 flex gap-1">
        <button v-for="t in [['chats','Чаты'],['teacher','Препод.'],['student','Студенты'],['channels','Каналы']]"
                :key="t[0]" type="button" @click="tab = t[0]"
                class="flex-1 rounded-md px-1.5 py-1.5 text-[11px] font-semibold transition-colors"
                :class="tab === t[0] ? 'bg-accent-glow text-accent' : 'text-text3 hover:bg-bg2 hover:text-text'">
          {{ t[1] }}
        </button>
      </div>
      <!-- §D7: мой статус (поверх presence) — виден другим в каталоге/карточке участника. -->
      <MyStatusPicker class="mt-1" />
    </div>

    <div class="min-h-0 flex-1 overflow-y-auto">
      <!-- Чаты (+ архив той же вёрсткой, отдельным «режимом» той же вкладки) -->
      <template v-if="tab === 'chats' || tab === 'archive'">
        <!-- «Избранное» — личный чат с самим собой, как Saved Messages в Telegram: всегда
             сверху, отдельно от общего списка (докладов не бывает). -->
        <button v-if="tab === 'chats'" type="button" @click="m.openSaved()"
                class="flex w-full items-center gap-3 border-b border-border/50 px-3 py-2.5 text-left transition-colors"
                :class="savedChat && activeId === savedChat.conversation_id ? 'bg-accent-glow' : 'hover:bg-bg2'">
          <div class="grid size-10 shrink-0 place-items-center rounded-full bg-accent2 text-white"><Star class="size-5" /></div>
          <div class="min-w-0 flex-1">
            <div class="text-sm font-semibold text-text">Избранное</div>
            <div class="truncate text-xs text-text3">{{ savedChat?.last_message ? (savedChat.last_message.deleted ? 'Сообщение удалено' : savedChat.last_message.body) : 'Заметки, ссылки, код себе' }}</div>
          </div>
        </button>
        <button v-if="tab === 'chats' && archivedCount" type="button" @click="tab = 'archive'"
                class="flex w-full items-center gap-3 border-b border-border/50 px-3 py-2.5 text-left transition-colors hover:bg-bg2">
          <div class="grid size-10 shrink-0 place-items-center rounded-full bg-bg2 text-text3"><Archive class="size-5" /></div>
          <div class="min-w-0 flex-1 text-sm font-semibold text-text">Архив</div>
          <span class="shrink-0 rounded-full bg-bg2 px-2 py-0.5 text-[11px] font-semibold text-text3">{{ archivedCount }}</span>
        </button>
        <div v-if="tab === 'archive'" class="flex items-center gap-2 border-b border-border/50 px-3 py-2">
          <button type="button" @click="tab = 'chats'" class="text-xs font-semibold text-accent hover:underline">← Назад к чатам</button>
        </div>

        <p v-if="!loadingChats && !shownChats.length" class="p-4 text-center text-sm text-text3">
          {{ tab === 'archive' ? 'В архиве пусто.' : 'Пока нет переписок. Найдите человека через поиск' }}<span v-if="canCreate && tab === 'chats'"> или создайте группу/канал кнопкой «+»</span>.
        </p>
        <div v-for="c in shownChats" :key="c.conversation_id"
             class="group relative flex w-full items-center gap-3 border-b border-border/50 px-3 py-2.5 transition-colors"
             :class="activeId === c.conversation_id ? 'bg-accent-glow' : 'hover:bg-bg2'">
          <button type="button" @click="m.selectChat(c)" class="flex min-w-0 flex-1 items-center gap-3 text-left">
            <!-- Личный чат — аватар собеседника; группа/канал — цветной кружок с инициалами. -->
            <Avatar v-if="c.kind === 'direct'" :src="c.peer?.avatar" :name="c.title"
                    :online="!!c.peer?.online" :size="40" />
            <div v-else class="grid size-10 shrink-0 place-items-center rounded-full text-sm font-bold text-white"
                 :class="c.kind === 'channel' ? 'bg-accent2' : 'bg-blue'">
              {{ initials(c.title) }}
            </div>
            <div class="min-w-0 flex-1">
              <div class="flex items-center justify-between gap-2">
                <span class="flex items-center gap-1 truncate text-sm font-semibold text-text">
                  <Pin v-if="c.pinned" class="size-3 shrink-0 text-text3" />{{ c.title || 'Диалог' }}
                </span>
                <span class="shrink-0 text-[11px] text-text3">{{ fmtTime(c.last_at) }}</span>
              </div>
              <div class="flex items-center justify-between gap-2">
                <span class="truncate text-xs text-text3">
                  {{ c.last_message ? (c.last_message.deleted ? 'Сообщение удалено' : c.last_message.body) : 'Нет сообщений' }}
                </span>
                <span v-if="c.unread" class="grid h-5 min-w-5 shrink-0 place-items-center rounded-full bg-accent px-1.5 text-[11px] font-bold text-white">{{ c.unread }}</span>
              </div>
            </div>
          </button>
          <div class="relative shrink-0">
            <button type="button" @click.stop="toggleMenu(c.conversation_id)" aria-label="Действия"
                    class="grid size-7 place-items-center rounded-md text-text3 opacity-0 hover:bg-bg2 hover:text-text group-hover:opacity-100"
                    :class="{ 'opacity-100 bg-bg2': menuFor === c.conversation_id }">
              <MoreVertical class="size-4" />
            </button>
            <div v-if="menuFor === c.conversation_id"
                 class="absolute right-0 top-full z-20 mt-1 w-44 overflow-hidden rounded-lg border border-border2 bg-card py-1 shadow-card">
              <button type="button" @click.stop="onPin(c)" class="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-text hover:bg-bg2">
                <component :is="c.pinned ? PinOff : Pin" class="size-4 text-text3" />{{ c.pinned ? 'Открепить' : 'Закрепить' }}
              </button>
              <button type="button" @click.stop="onArchive(c)" class="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-text hover:bg-bg2">
                <component :is="c.archived ? ArchiveRestore : Archive" class="size-4 text-text3" />{{ c.archived ? 'Из архива' : 'В архив' }}
              </button>
            </div>
          </div>
        </div>
      </template>

      <!-- Каталог людей -->
      <template v-else-if="tab === 'teacher' || tab === 'student'">
        <p v-if="dir.loading" class="p-4 text-center text-sm text-text3">Поиск…</p>
        <p v-else-if="!dir.users.length" class="p-4 text-center text-sm text-text3">Никого не найдено.</p>
        <button v-for="u in dir.users" :key="u.id" type="button" @click="m.openWith(u)"
                class="flex w-full items-center gap-3 border-b border-border/50 px-3 py-2.5 text-left transition-colors hover:bg-bg2">
          <Avatar :src="u.avatar" :name="u.full_name" :online="!!u.online" :size="40" />
          <div class="min-w-0 flex-1">
            <div class="truncate text-sm font-semibold text-text">{{ u.full_name }}</div>
            <div class="truncate text-xs text-text3">{{ u.role === 'teacher' ? ((u.subjects || []).join(', ') || 'Преподаватель') : ('Группа ' + (u.group_name || '—')) }}</div>
          </div>
        </button>
      </template>

      <!-- Каталог каналов -->
      <template v-else>
        <p v-if="!channels.length" class="p-4 text-center text-sm text-text3">Публичных каналов пока нет.</p>
        <button v-for="ch in channels" :key="ch.conversation_id" type="button" @click="m.joinChannel(ch.conversation_id)"
                class="flex w-full items-center gap-3 border-b border-border/50 px-3 py-2.5 text-left transition-colors hover:bg-bg2">
          <div class="grid size-10 shrink-0 place-items-center rounded-full bg-accent2 text-sm font-bold text-white">{{ initials(ch.title) }}</div>
          <div class="min-w-0 flex-1">
            <div class="truncate text-sm font-semibold text-text">{{ ch.title }}</div>
            <div class="truncate text-xs text-text3">{{ ch.subscribers }} подписчиков · {{ ch.about || 'канал' }}</div>
          </div>
          <span class="shrink-0 rounded-full px-2 py-0.5 text-[11px] font-semibold"
                :class="ch.joined ? 'bg-bg2 text-text3' : 'bg-accent-glow text-accent'">
            {{ ch.joined ? 'Открыть' : 'Присоединиться' }}
          </span>
        </button>
      </template>
    </div>

    <CreateChatDialog v-if="createKind" :kind="createKind" @create="onCreate" @close="createKind = ''" />
  </aside>
</template>
