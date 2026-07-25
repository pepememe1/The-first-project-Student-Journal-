<script setup>
// ConversationInfo — модалка «О беседе»: описание, ВЛАДЕЛЕЦ и список участников с
// аватарками и ролями. Открывается кликом по шапке чата (как в Telegram), поэтому
// доступна на ЛЮБОЙ ширине — боковая ProfilePanel показывается только с xl и на
// десктопе/телефоне была не видна.
// Здесь же — выход из группы/канала и удаление переписки у себя.
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { X, Crown, Trash2, LogOut, Users, Radio, ShieldCheck } from '@lucide/vue'
import { useMessengerStore } from '@/stores/messenger'
import { profilePlate } from '@/theme/palette'
import Avatar from '@/components/ui/Avatar.vue'

// Цвет плашки профиля выбирает сам человек (id пресета) — см. palette.profilePlate.
function plate(u) {
  return profilePlate(u?.profile_color)
}

const emit = defineEmits(['close'])
const m = useMessengerStore()
const { activeInfo, activePeer, isModeration } = storeToRefs(m)

const kind = computed(() => activeInfo.value?.kind || 'direct')
const isGroupOrChannel = computed(() => ['group', 'channel'].includes(kind.value))
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

const title = computed(() => {
  if (isModeration.value) return 'Модерация'
  if (isGroupOrChannel.value) return activeInfo.value?.title || 'Беседа'
  return activePeer.value?.full_name || 'Диалог'
})

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
        <button type="button" @click="emit('close')" aria-label="Закрыть"
                class="grid size-8 shrink-0 place-items-center rounded-md text-text3 hover:bg-bg2 hover:text-text">
          <X class="size-5" />
        </button>
      </div>

      <div class="min-h-0 flex-1 overflow-y-auto p-4">
        <p v-if="activeInfo?.about" class="mb-4 text-sm text-text2">{{ activeInfo.about }}</p>

        <!-- Личный чат: карточка собеседника с его плашкой и «О себе» -->
        <template v-if="!isGroupOrChannel && activePeer">
          <div class="flex items-center gap-3 rounded-xl p-4" :style="{ background: plate(activePeer) }">
            <Avatar :src="activePeer.avatar" :name="activePeer.full_name"
                    :online="!!activePeer.online" :size="56" />
            <div class="min-w-0">
              <div class="truncate text-base font-bold text-white">{{ activePeer.full_name }}</div>
              <div class="truncate text-xs text-white/80">
                {{ activePeer.role === 'teacher'
                  ? ((activePeer.subjects || []).join(', ') || 'Преподаватель')
                  : (activePeer.group_name ? 'Группа ' + activePeer.group_name : 'Студент') }}
              </div>
              <div class="mt-0.5 text-xs text-white/70">
                {{ activePeer.online ? 'в сети' : 'не в сети' }}
              </div>
            </div>
          </div>
          <p v-if="activePeer.bio" class="mt-3 whitespace-pre-wrap text-sm text-text2">{{ activePeer.bio }}</p>
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
        <button type="button" @click="removeChat"
                class="ml-auto flex items-center gap-1.5 rounded-lg border border-red/40 px-3 py-2 text-sm font-semibold text-red hover:bg-red/10">
          <Trash2 class="size-4" />Удалить переписку
        </button>
      </div>
    </div>
  </div>
</template>
