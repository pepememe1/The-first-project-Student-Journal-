<script setup>
// ConversationInfo — модалка «О беседе»: описание, ВЛАДЕЛЕЦ и список участников с
// аватарками и ролями. Открывается кликом по шапке чата (как в Telegram), поэтому
// доступна на ЛЮБОЙ ширине — боковая ProfilePanel показывается только с xl и на
// десктопе/телефоне была не видна.
// Здесь же — выход из группы/канала и удаление переписки у себя.
import { ref, computed } from 'vue'
import { storeToRefs } from 'pinia'
import { X, Crown, Trash2, LogOut, Users, Radio, ShieldCheck, Pencil, Check } from '@lucide/vue'
import { useMessengerStore } from '@/stores/messenger'
import { profilePlate } from '@/theme/palette'
import Avatar from '@/components/ui/Avatar.vue'

// Цвет плашки профиля выбирает сам человек (id пресета) — см. palette.profilePlate.
function plate(u) {
  return profilePlate(u?.profile_color)
}

const emit = defineEmits(['close'])
const m = useMessengerStore()
const { activeInfo, activePeer, isModeration, activeKind } = storeToRefs(m)

const kind = computed(() => activeKind.value)
const isGroupOrChannel = computed(() => ['group', 'channel'].includes(kind.value))
const isSaved = computed(() => kind.value === 'saved')
const people = computed(() => activeInfo.value?.participants || [])
const ownerId = computed(() => activeInfo.value?.owner_id || '')

const KIND_RU = { group: 'Группа', channel: 'Канал', moderation: 'Модерация', direct: 'Личный чат' }
const ROLE_RU = { owner: 'владелец', admin: 'админ', writer: 'автор', member: 'участник', reader: 'читатель' }

// Подпись под именем: у преподавателя — предметы, у студента — группа.
function meta(p) {
  if (p.user_role === 'teacher') return (p.subjects || []).join(', ') || 'Преподаватель'
  if (p.user_role === 'student') return p.group_name ? `Группа ${p.group_name}` : 'Студент'
  return p.user_role === 'admin' ? 'Администратор' : ''
}

// Та же подпись, но для activePeer (личный чат) — там роль лежит в поле `role`, а не
// `user_role` (см. _safe_user на сервере vs. participants[] в conversation_info). Раньше
// админ падал в "иначе" инлайн-тернарника и подписывался «Студент».
function peerMeta(p) {
  if (p?.role === 'teacher') return (p.subjects || []).join(', ') || 'Преподаватель'
  if (p?.role === 'admin') return 'Администратор'
  if (p?.role === 'parent') return 'Родитель'
  return p?.group_name ? `Группа ${p.group_name}` : 'Студент'
}

const title = computed(() => {
  if (isSaved.value) return 'Избранное'
  if (isModeration.value) return 'Модерация'
  if (isGroupOrChannel.value) return activeInfo.value?.title || 'Беседа'
  return activePeer.value?.full_name || 'Диалог'
})

// §D6: переименование группы/канала — только owner/admin.
const canRename = computed(() => isGroupOrChannel.value && ['owner', 'admin'].includes(activeInfo.value?.my_role))
const editing = ref(false)
const titleDraft = ref('')
const aboutDraft = ref('')
function startEdit() {
  titleDraft.value = activeInfo.value?.title || ''
  aboutDraft.value = activeInfo.value?.about || ''
  editing.value = true
}
async function saveEdit() {
  const t = titleDraft.value.trim()
  if (!t) return
  if (await m.renameActive(t, aboutDraft.value.trim())) editing.value = false
}

async function leave() {
  if (!window.confirm(`Выйти из ${kind.value === 'channel' ? 'канала' : 'группы'}?`)) return
  await m.leaveActive()
  emit('close')
}

async function removeChat() {
  const what = isGroupOrChannel.value
    ? 'Удалить беседу у себя? Вы также выйдете из неё.'
    : 'Удалить переписку у себя? У собеседника она сохранится.'
  if (!window.confirm(what)) return
  await m.deleteConversation(false)
  emit('close')
}

async function clearHistory() {
  if (!window.confirm('Очистить историю у себя? Сообщения пропадут только у вас.')) return
  await m.deleteConversation(true)
  emit('close')
}
</script>

<template>
  <div class="fixed inset-0 z-50 grid place-items-center p-4" style="background: var(--gb-overlay)"
       @click.self="emit('close')">
    <div class="flex max-h-[85vh] w-full max-w-md flex-col rounded-xl border border-border2 bg-card shadow-card">
      <!-- Шапка -->
      <div class="flex items-center gap-2 border-b border-border p-4">
        <component :is="kind === 'channel' ? Radio : (isModeration ? ShieldCheck : Users)"
                   class="size-5 shrink-0 text-accent" />
        <div class="min-w-0 flex-1">
          <h3 class="truncate font-title text-base font-bold text-text">{{ title }}</h3>
          <p class="text-xs text-text3">
            {{ KIND_RU[kind] || 'Беседа' }}
            <span v-if="isGroupOrChannel"> · {{ activeInfo?.subscribers || 0 }}
              {{ kind === 'channel' ? 'подписчиков' : 'участников' }}</span>
          </p>
        </div>
        <!-- §D6: переименовать (owner/admin) -->
        <button v-if="canRename && !editing" type="button" @click="startEdit" aria-label="Переименовать"
                class="grid size-8 shrink-0 place-items-center rounded-md text-text3 hover:bg-bg2 hover:text-text">
          <Pencil class="size-4" />
        </button>
        <button type="button" @click="emit('close')" aria-label="Закрыть"
                class="grid size-8 shrink-0 place-items-center rounded-md text-text3 hover:bg-bg2 hover:text-text">
          <X class="size-5" />
        </button>
      </div>

      <div class="min-h-0 flex-1 overflow-y-auto p-4">
        <!-- §D6: форма переименования -->
        <div v-if="editing" class="mb-4 space-y-2 rounded-lg border border-border2 bg-card2 p-3">
          <input v-model="titleDraft" placeholder="Название" maxlength="120"
                 class="w-full rounded-md border border-border2 bg-card px-2.5 py-1.5 text-sm text-text outline-none focus:border-accent" />
          <textarea v-model="aboutDraft" placeholder="Описание (необязательно)" rows="2" maxlength="500"
                    class="w-full resize-none rounded-md border border-border2 bg-card px-2.5 py-1.5 text-sm text-text outline-none focus:border-accent" />
          <div class="flex justify-end gap-2">
            <button type="button" @click="editing = false" class="rounded-md px-3 py-1.5 text-xs text-text3 hover:bg-bg2">Отмена</button>
            <button type="button" @click="saveEdit" :disabled="!titleDraft.trim()"
                    class="flex items-center gap-1 rounded-md bg-accent px-3 py-1.5 text-xs font-semibold text-white hover:bg-accent2 disabled:opacity-50">
              <Check class="size-3.5" />Сохранить
            </button>
          </div>
        </div>
        <p v-if="activeInfo?.about" class="mb-4 text-sm text-text2">{{ activeInfo.about }}</p>

        <!-- Личный чат: карточка собеседника с его плашкой и «О себе» -->
        <!-- В «Избранном» карточки «собеседника» нет: это ты сам. -->
        <p v-if="isSaved" class="text-sm text-text2">
          Личные заметки: ссылки, файлы и мысли для себя. Здесь же работает команда
          <span class="font-semibold text-accent">/vector</span> — спросить ИИ-помощника.
        </p>
        <!-- Модерация раньше рендерилась как обычная карточка собеседника (activePeer =
             {full_name:'Модерация', role:'moderation'}) — тоже падала в «Студент». -->
        <div v-else-if="isModeration" class="rounded-lg border border-border bg-card2 p-4 text-sm text-text2">
          <div class="mb-2 flex items-center gap-2 text-text">
            <ShieldCheck class="size-5 text-accent" /><span class="font-semibold">Модерация</span>
          </div>
          Сюда можно написать о проблеме: жалоба на пользователя, технический вопрос,
          нарушение правил. Переписка может быть просмотрена модерацией в целях безопасности.
        </div>
        <template v-else-if="!isGroupOrChannel && activePeer">
          <div class="flex items-center gap-3 rounded-xl p-4" :style="{ background: plate(activePeer) }">
            <Avatar :src="activePeer.avatar" :name="activePeer.full_name"
                    :online="!!activePeer.online" :size="56" />
            <div class="min-w-0">
              <div class="truncate text-base font-bold text-white">{{ activePeer.full_name }}</div>
              <div class="truncate text-xs text-white/80">{{ peerMeta(activePeer) }}</div>
              <div class="mt-0.5 text-xs text-white/70">
                {{ activePeer.online ? 'в сети' : 'не в сети' }}
              </div>
            </div>
          </div>
          <p v-if="activePeer.bio" class="mt-3 whitespace-pre-wrap text-sm text-text2">{{ activePeer.bio }}</p>
          <!-- ЛС с администратором — другой контекст переписки, поясняем границы. -->
          <div v-if="activePeer.role === 'admin'" class="mt-3 rounded-lg border border-border bg-card2 p-3 text-sm text-text2">
            <p class="mb-1 text-[11px] uppercase tracking-wide text-text3">Лучше не сюда</p>
            Жалобы на пользователей — через «Модерация» (кнопка ⚙ у чата). Учебные вопросы
            (оценки, расписание) — своему куратору или преподавателю.
          </div>
        </template>

        <!-- Группа/канал: участники, владелец сверху и с короной -->
        <template v-else-if="isGroupOrChannel">
          <p class="mb-2 text-[11px] uppercase tracking-wide text-text3">
            Участники · {{ people.length }}
          </p>
          <div class="space-y-1">
            <div v-for="p in people" :key="p.user_id"
                 class="flex items-center gap-2.5 rounded-lg px-2 py-1.5 hover:bg-bg2">
              <Avatar :src="p.avatar" :name="p.full_name" :online="!!p.online" :size="36" />
              <div class="min-w-0 flex-1">
                <div class="flex items-center gap-1.5">
                  <span class="truncate text-sm font-medium text-text">{{ p.full_name }}</span>
                  <Crown v-if="p.user_id === ownerId || p.role === 'owner'"
                         class="size-3.5 shrink-0 text-accent" aria-label="Владелец" />
                </div>
                <div class="truncate text-[11px] text-text3">{{ meta(p) }}</div>
              </div>
              <span class="shrink-0 rounded-full px-2 py-0.5 text-[11px] font-semibold"
                    :class="(p.user_id === ownerId || p.role === 'owner')
                      ? 'bg-accent-glow text-accent' : 'bg-bg2 text-text3'">
                {{ ROLE_RU[p.role] || p.role }}
              </span>
            </div>
          </div>
        </template>
      </div>

      <!-- Действия -->
      <div class="flex flex-wrap gap-2 border-t border-border p-3">
        <button type="button" @click="clearHistory"
                class="rounded-lg border border-border2 px-3 py-2 text-sm text-text2 hover:bg-bg2">
          Очистить историю
        </button>
        <button v-if="isGroupOrChannel" type="button" @click="leave"
                class="flex items-center gap-1.5 rounded-lg border border-border2 px-3 py-2 text-sm text-text2 hover:bg-bg2">
          <LogOut class="size-4" />Покинуть
        </button>
        <!-- «Избранное» удалить нельзя: оно одно на пользователя и всегда есть в списке
             (как в Telegram). Для него доступна только очистка — кнопка выше. -->
        <button v-if="!isSaved" type="button" @click="removeChat"
                class="ml-auto flex items-center gap-1.5 rounded-lg border border-red/40 px-3 py-2 text-sm font-semibold text-red hover:bg-red/10">
          <Trash2 class="size-4" />Удалить переписку
        </button>
      </div>
    </div>
  </div>
</template>
