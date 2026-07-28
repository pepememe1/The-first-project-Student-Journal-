<script setup>
// ConversationInfo — модалка «О беседе»: описание, ВЛАДЕЛЕЦ и список участников с
// аватарками и ролями. Открывается кликом по шапке чата (как в Telegram), поэтому
// доступна на ЛЮБОЙ ширине — боковая ProfilePanel показывается только с xl и на
// десктопе/телефоне была не видна.
// Здесь же — выход из группы/канала и удаление переписки у себя.
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { storeToRefs } from 'pinia'
import { X, Crown, Trash2, LogOut, Users, Radio, ShieldCheck, Pencil, Check, MoreVertical } from '@lucide/vue'
import { useMessengerStore } from '@/stores/messenger'
import { useToast } from '@/composables/useToast'
import { profilePlate } from '@/theme/palette'
import { statusColor, statusLabel } from '@/config/status'
import Avatar from '@/components/ui/Avatar.vue'
import RoleManagerDialog from '@/components/messenger/RoleManagerDialog.vue'

// Цвет плашки профиля выбирает сам человек (id пресета) — см. palette.profilePlate.
function plate(u) {
  return profilePlate(u?.profile_color)
}

const emit = defineEmits(['close'])
const m = useMessengerStore()
const toast = useToast()
const { activeInfo, activePeer, isModeration, activeKind } = storeToRefs(m)

// §ролей: права звонящего в ЭТОЙ беседе + личный игнор-лист + мой user_id — всё уже
// приезжает в conversation_info (см. routers/messenger.py::conversation_info). Свой id
// клиент иначе не знает (в JWT/сторе только логин+роль, см. комментарий у _msg_out).
const myPermissions = computed(() => new Set(activeInfo.value?.my_permissions || []))
const myIgnoredIds = computed(() => new Set(activeInfo.value?.my_ignored_user_ids || []))
const myUserId = computed(() => activeInfo.value?.my_user_id || '')
const canKick = computed(() => myPermissions.value.has('kick'))
const canManageRoles = computed(() => myPermissions.value.has('manage_roles'))
const openMenuFor = ref(null)
const roleDialogFor = ref(null)

function toggleMenu(uid) { openMenuFor.value = openMenuFor.value === uid ? null : uid }
// Клик вне меню участника — закрыть (нет глобальной v-click-outside директивы в проекте,
// делаем локально одним слушателем на весь компонент).
function onDocClick(e) {
  if (openMenuFor.value && !e.target.closest('[data-role-menu]')) openMenuFor.value = null
}
onMounted(() => document.addEventListener('click', onDocClick))
onUnmounted(() => document.removeEventListener('click', onDocClick))

async function kick(p) {
  openMenuFor.value = null
  if (!window.confirm(`Выгнать ${p.full_name} из беседы?`)) return
  const ok = await m.kickMember(p.user_id)
  if (!ok) toast.error('Не удалось выгнать участника')
}
async function toggleIgnore(p) {
  openMenuFor.value = null
  const ok = await m.toggleIgnore(p.user_id, myIgnoredIds.value.has(p.user_id))
  if (!ok) toast.error('Не удалось изменить игнор')
}
function openRoleDialog(p) {
  openMenuFor.value = null
  roleDialogFor.value = p
}

const kind = computed(() => activeKind.value)
const isGroupOrChannel = computed(() => ['group', 'channel'].includes(kind.value))
const isSaved = computed(() => kind.value === 'saved')
const people = computed(() => activeInfo.value?.participants || [])
const ownerId = computed(() => activeInfo.value?.owner_id || '')

const KIND_RU = { group: 'Группа', channel: 'Канал', moderation: 'Модерация', direct: 'Личный чат' }
const ROLE_RU = { owner: 'владелец', admin: 'админ', writer: 'автор', member: 'участник', reader: 'читатель' }

// §D7: статус поверх presence. Сервер отдаёт его и в карточке собеседника (_safe_user),
// и у каждого участника (conversation_info) — но панель их не показывала вовсе, и со
// стороны это читалось как «смена статуса не работает»: человек его выбрал, а никто не
// видит. Названия и цвета — из общего config/status.js (раньше набор жил пятью копиями).
function label(p) { return statusLabel(p?.status_kind, p?.status_text) }
function color(p) { return statusColor(p?.status_kind) }

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
                    :online="!!activePeer.online" :status="activePeer.status_kind"
                    :status-text="activePeer.status_text" :size="56" />
            <div class="min-w-0">
              <div class="truncate text-base font-bold text-white">{{ activePeer.full_name }}</div>
              <div class="truncate text-xs text-white/80">{{ peerMeta(activePeer) }}</div>
              <!-- Статус, который человек выбрал сам, ВАЖНЕЕ presence: «не беспокоить»
                   при этом остаётся «в сети», и показать только «в сети» — значит
                   потерять ровно то, что он просил передать. Кружок рисует Avatar. -->
              <div class="mt-0.5 flex items-center gap-1.5 text-xs text-white/70">
                <template v-if="label(activePeer)">
                  <span class="truncate">{{ label(activePeer) }}</span>
                  <span class="shrink-0 text-white/50">· {{ activePeer.online ? 'в сети' : 'не в сети' }}</span>
                </template>
                <template v-else>{{ activePeer.online ? 'в сети' : 'не в сети' }}</template>
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
                 class="relative flex items-center gap-2.5 rounded-lg px-2 py-1.5 hover:bg-bg2">
              <Avatar :src="p.avatar" :name="p.full_name" :online="!!p.online"
                      :status="p.status_kind" :status-text="p.status_text" :size="36" />
              <div class="min-w-0 flex-1">
                <div class="flex items-center gap-1.5">
                  <span class="truncate text-sm font-medium text-text">{{ p.full_name }}</span>
                  <Crown v-if="p.user_id === ownerId || p.role === 'owner'"
                         class="size-3.5 shrink-0 text-accent" aria-label="Владелец" />
                  <span v-if="p.silenced" title="Заглушён(а) — /mute" class="shrink-0 text-xs">🔇</span>
                </div>
                <div class="flex items-center gap-1.5 truncate text-[11px] text-text3">
                  <!-- Статус участника — кружок уже на аватарке, здесь только подпись. -->
                  <span v-if="label(p)" class="size-2 shrink-0 rounded-full"
                        :style="{ background: color(p) }" />
                  <span class="truncate">{{ label(p) || meta(p) }}</span>
                </div>
              </div>
              <span class="shrink-0 rounded-full px-2 py-0.5 text-[11px] font-semibold"
                    :class="(p.user_id === ownerId || p.role === 'owner')
                      ? 'bg-accent-glow text-accent' : 'bg-bg2 text-text3'">
                {{ p.custom_role_name || ROLE_RU[p.role] || p.role }}
              </span>
              <!-- §ролей: меню участника — кик/игнор/роль. Игнор доступен всем (личное),
                   кик/роль — по правам. Себя выгнать/игнорировать нельзя из этого меню. -->
              <button v-if="p.user_id !== myUserId" type="button" data-role-menu @click.stop="toggleMenu(p.user_id)"
                      aria-label="Действия" class="grid size-7 shrink-0 place-items-center rounded-md text-text3 hover:bg-bg2 hover:text-text">
                <MoreVertical class="size-4" />
              </button>
              <div v-if="openMenuFor === p.user_id" data-role-menu
                   class="absolute right-2 top-10 z-10 w-44 rounded-lg border border-border2 bg-card p-1 shadow-card">
                <button type="button" @click="toggleIgnore(p)"
                        class="block w-full rounded-md px-2.5 py-1.5 text-left text-sm text-text2 hover:bg-bg2">
                  {{ myIgnoredIds.has(p.user_id) ? 'Показать сообщения' : 'Игнорировать' }}
                </button>
                <button v-if="canManageRoles && p.role !== 'owner'" type="button" @click="openRoleDialog(p)"
                        class="block w-full rounded-md px-2.5 py-1.5 text-left text-sm text-text2 hover:bg-bg2">
                  Выдать роль
                </button>
                <button v-if="canKick && p.role !== 'owner'" type="button" @click="kick(p)"
                        class="block w-full rounded-md px-2.5 py-1.5 text-left text-sm text-red hover:bg-red/10">
                  Выгнать
                </button>
              </div>
            </div>
          </div>
        </template>
      </div>

      <RoleManagerDialog v-if="roleDialogFor" :user-id="roleDialogFor.user_id"
                         :user-name="roleDialogFor.full_name" @close="roleDialogFor = null" />

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
