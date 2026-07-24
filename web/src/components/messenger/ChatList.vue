<script setup>
// ChatList — левая колонка навигации (стиль Telegram): поиск по ФИО, вкладки
// «Чаты / Преподаватели / Студенты / Каналы», кнопка «+» (новая группа/канал). Клик по
// чату открывает переписку; по человеку — личный чат; по каналу — вступление/открытие.
import { ref, computed, watch, onMounted } from 'vue'
import { storeToRefs } from 'pinia'
import { Search, Plus, Users, Radio } from '@lucide/vue'
import { useMessengerStore } from '@/stores/messenger'
import CreateChatDialog from './CreateChatDialog.vue'

const m = useMessengerStore()
const { chats, dir, channels, activeId, loadingChats } = storeToRefs(m)

const tab = ref('chats')            // chats | teacher | student | channels
const q = ref('')
const showNew = ref(false)
const createKind = ref('')          // '' | group | channel
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

const shownChats = computed(() => {
  const ql = q.value.trim().toLowerCase()
  return ql ? chats.value.filter(c => (c.title || '').toLowerCase().includes(ql)) : chats.value
})

function refresh() {
  if (tab.value === 'teacher' || tab.value === 'student') m.searchUsers(tab.value, q.value)
  else if (tab.value === 'channels') m.loadChannels(q.value)
}
watch(tab, refresh)
watch(q, () => {
  if (tab.value === 'chats') return
  clearTimeout(debounce)
  debounce = setTimeout(refresh, 300)
})

function startCreate(kind) { showNew.value = false; createKind.value = kind }
async function onCreate(payload) {
  const kind = createKind.value
  createKind.value = ''
  if (kind === 'group') await m.createGroup(payload.title, payload.ids, payload.about)
  else await m.createChannel(payload.title, payload.ids, payload.isPublic, payload.about)
}

onMounted(() => { m.loadChats() })
</script>

<template>
  <aside class="flex h-full w-full flex-col border-r border-border bg-card sm:w-80 sm:shrink-0">
    <!-- Поиск + «Новый» -->
    <div class="shrink-0 border-b border-border p-2.5">
      <div class="flex items-center gap-2">
        <div class="flex flex-1 items-center gap-2 rounded-lg border border-border2 bg-card2 px-3">
          <Search class="size-4 shrink-0 text-text3" />
          <input v-model="q" placeholder="Поиск по ФИО…"
                 class="h-9 min-w-0 flex-1 bg-transparent text-sm text-text outline-none" />
        </div>
        <div class="relative">
          <button type="button" @click="showNew = !showNew" aria-label="Создать"
                  class="grid size-9 place-items-center rounded-lg bg-accent text-white hover:bg-accent2"><Plus class="size-5" /></button>
          <div v-if="showNew" class="absolute right-0 top-full z-20 mt-1 w-44 overflow-hidden rounded-lg border border-border2 bg-card py-1 shadow-card">
            <button type="button" @click="startCreate('group')" class="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-text hover:bg-bg2"><Users class="size-4 text-text3" />Новая группа</button>
            <button type="button" @click="startCreate('channel')" class="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-text hover:bg-bg2"><Radio class="size-4 text-text3" />Новый канал</button>
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
    </div>

    <div class="min-h-0 flex-1 overflow-y-auto">
      <!-- Чаты -->
      <template v-if="tab === 'chats'">
        <p v-if="!loadingChats && !shownChats.length" class="p-4 text-center text-sm text-text3">
          Пока нет переписок. Найдите человека или создайте группу/канал кнопкой «+».
        </p>
        <button v-for="c in shownChats" :key="c.conversation_id" type="button" @click="m.selectChat(c)"
                class="flex w-full items-center gap-3 border-b border-border/50 px-3 py-2.5 text-left transition-colors"
                :class="activeId === c.conversation_id ? 'bg-accent-glow' : 'hover:bg-bg2'">
          <div class="relative shrink-0">
            <div class="grid size-10 place-items-center rounded-full text-sm font-bold text-white"
                 :class="c.kind === 'channel' ? 'bg-accent2' : c.kind === 'group' ? 'bg-blue' : 'bg-accent'">
              {{ initials(c.title) }}
            </div>
            <span v-if="c.peer && c.peer.online" title="в сети"
                  class="absolute bottom-0 right-0 size-3 rounded-full border-2 border-card" style="background:#2e9e5b"></span>
          </div>
          <div class="min-w-0 flex-1">
            <div class="flex items-center justify-between gap-2">
              <span class="truncate text-sm font-semibold text-text">{{ c.title || 'Диалог' }}</span>
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
      </template>

      <!-- Каталог людей -->
      <template v-else-if="tab === 'teacher' || tab === 'student'">
        <p v-if="dir.loading" class="p-4 text-center text-sm text-text3">Поиск…</p>
        <p v-else-if="!dir.users.length" class="p-4 text-center text-sm text-text3">Никого не найдено.</p>
        <button v-for="u in dir.users" :key="u.id" type="button" @click="m.openWith(u)"
                class="flex w-full items-center gap-3 border-b border-border/50 px-3 py-2.5 text-left transition-colors hover:bg-bg2">
          <div class="relative shrink-0">
            <div class="grid size-10 place-items-center rounded-full bg-accent2 text-sm font-bold text-white">{{ initials(u.full_name) }}</div>
            <span v-if="u.online" title="в сети" class="absolute bottom-0 right-0 size-3 rounded-full border-2 border-card" style="background:#2e9e5b"></span>
          </div>
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
