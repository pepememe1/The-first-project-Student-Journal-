<script setup>
// ProfilePanel — карточка собеседника (портфолио) СЛЕВА от чата. Только безопасные поля
// (см. MESSENGER-PLAN.md §9): ФИО, роль, группа (студент) / предметы (преподаватель).
import { computed, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { GraduationCap, UserRound, ShieldCheck, Users, PanelLeftClose, PanelLeftOpen, Landmark } from '@lucide/vue'
import { useMessengerStore } from '@/stores/messenger'
import { profilePlate } from '@/theme/palette'
import Avatar from '@/components/ui/Avatar.vue'

const m = useMessengerStore()
const { activePeer, isModeration, activeInfo } = storeToRefs(m)

// Панель можно свернуть — состояние помним между сеансами (кому-то нужен только чат).
// По умолчанию СВЁРНУТА: карточка собеседника и список участников нужны изредка, а места
// они съедают столько же, сколько сама переписка. Разворачивается кнопкой и с тех пор
// помнится — поэтому сравниваем с '0', а не с '1' (пустой ключ = «ещё не решал» = скрыто).
const K_COLLAPSED = 'gb.messenger.profile_collapsed'
const collapsed = ref(localStorage.getItem(K_COLLAPSED) !== '0')
function toggle() {
  collapsed.value = !collapsed.value
  localStorage.setItem(K_COLLAPSED, collapsed.value ? '1' : '0')
}

// Цвет плашки собеседника (он выбирает его в своём профиле).
const plate = computed(() => profilePlate(activePeer.value?.profile_color))

function initials(name) {
  const p = (name || '').trim().split(/\s+/)
  return ((p[0]?.[0] || '') + (p[1]?.[0] || '')).toUpperCase() || '?'
}
const isTeacher = computed(() => activePeer.value?.role === 'teacher')
//Админ ошибочно попадал в "иначе" этого тернарника и подписывался «Студент» — роль-словарь
//вместо бинарного teacher/не-teacher, на случай будущих ролей (например, "parent").
const ROLE_LABELS = { teacher: 'Преподаватель', student: 'Студент', admin: 'Администратор', parent: 'Родитель' }
const roleLabel = computed(() => ROLE_LABELS[activePeer.value?.role] || 'Студент')
const isAdminPeer = computed(() => activePeer.value?.role === 'admin')
const isGroupOrChannel = computed(() => ['group', 'channel'].includes(activeInfo.value?.kind))
//«Избранное» — блокнот с самим собой: карточка «собеседника» тут показывала бы тебя же
//(роль, «в сети»), что бессмысленно. Панель для него просто не показываем.
const isSaved = computed(() => activeInfo.value?.kind === 'saved')
const ROLE_RU = { owner: 'владелец', admin: 'админ', writer: 'автор', member: 'участник', reader: 'читатель' }
</script>

<template>
  <!-- В «Избранном» боковой панели нет вовсе: показывать карточку самого себя незачем. -->
  <aside v-if="isSaved" class="hidden"></aside>

  <!-- Свёрнутое состояние: узкая полоска с кнопкой «развернуть» -->
  <aside v-else-if="collapsed" class="hidden w-10 shrink-0 flex-col items-center border-r border-border bg-card py-2 xl:flex">
    <button type="button" @click="toggle" title="Показать профиль" aria-label="Показать профиль"
            class="grid size-8 place-items-center rounded-md text-text3 hover:bg-bg2 hover:text-text">
      <PanelLeftOpen class="size-5" />
    </button>
  </aside>

  <aside v-else class="relative hidden w-72 shrink-0 flex-col border-r border-border bg-card xl:flex">
    <!-- Свернуть панель (состояние помнится) -->
    <button type="button" @click="toggle" title="Скрыть профиль" aria-label="Скрыть профиль"
            class="absolute right-1.5 top-1.5 z-10 grid size-8 place-items-center rounded-md bg-black/20 text-white/80 backdrop-blur-sm hover:bg-black/35 hover:text-white">
      <PanelLeftClose class="size-4" />
    </button>
    <!-- Режим модерации: сводка правил + контакты вместо карточки собеседника -->
    <div v-if="isModeration" class="flex flex-col p-6">
      <div class="mb-3 flex items-center gap-2">
        <ShieldCheck class="size-6 text-accent" />
        <h2 class="font-title text-lg font-bold text-text">Модерация</h2>
      </div>
      <p class="text-sm text-text2">Сюда можно написать о проблеме: жалоба на пользователя,
        технический вопрос, нарушение правил.</p>
      <div class="mt-4 rounded-lg border border-border bg-card2 p-3 text-sm text-text2">
        <p class="mb-1 text-[11px] uppercase tracking-wide text-text3">Что не делать</p>
        Оскорбления, спам, флуд. Сообщения переписки могут быть просмотрены модерацией в
        целях безопасности.
      </div>
      <div class="mt-3 rounded-lg border border-border bg-card2 p-3 text-sm text-text2">
        <p class="mb-1 text-[11px] uppercase tracking-wide text-text3">Контакты</p>
        Учебная часть колледжа · ответ обычно в течение рабочего дня.
      </div>
    </div>

    <!-- Группа / канал: описание + участники + покинуть -->
    <div v-else-if="isGroupOrChannel" class="flex min-h-0 flex-col p-5">
      <div class="mb-3 flex items-center gap-2">
        <Users class="size-6 text-accent" />
        <div class="min-w-0">
          <h2 class="truncate font-title text-lg font-bold text-text">{{ activeInfo.title }}</h2>
          <p class="text-xs text-text3">{{ activeInfo.kind === 'channel' ? 'Канал' : 'Группа' }} · {{ activeInfo.subscribers }}</p>
        </div>
      </div>
      <p v-if="activeInfo.about" class="mb-3 text-sm text-text2">{{ activeInfo.about }}</p>
      <p class="mb-1 text-[11px] uppercase tracking-wide text-text3">Участники</p>
      <div class="min-h-0 flex-1 space-y-1 overflow-y-auto">
        <div v-for="p in activeInfo.participants" :key="p.user_id"
             class="flex items-center gap-2 rounded-md px-2 py-1.5 hover:bg-bg2">
          <div class="grid size-7 shrink-0 place-items-center rounded-full bg-accent2 text-[11px] font-bold text-white">{{ initials(p.full_name) }}</div>
          <span class="min-w-0 flex-1 truncate text-sm text-text">{{ p.full_name }}</span>
          <span class="shrink-0 text-[11px] text-text3">{{ ROLE_RU[p.role] || p.role }}</span>
        </div>
      </div>
      <button type="button" @click="m.leaveActive()"
              class="mt-3 rounded-lg border border-border2 px-4 py-2 text-sm text-red hover:bg-bg2">
        Покинуть {{ activeInfo.kind === 'channel' ? 'канал' : 'группу' }}
      </button>
    </div>

    <!-- ЛС с администратором — не «студент/препод», отдельная карточка (по образцу
         карточки модерации), т.к. личка с админом это другой контекст переписки. -->
    <div v-else-if="isAdminPeer" class="flex flex-col p-6">
      <div class="mb-3 flex flex-col items-center text-center">
        <Avatar :src="activePeer.avatar" :name="activePeer.full_name" :online="!!activePeer.online" :size="72" />
        <h2 class="mt-3 font-title text-lg font-bold text-text">{{ activePeer.full_name }}</h2>
        <span class="mt-1 inline-flex items-center gap-1 text-xs text-text3">
          <Landmark class="size-3.5" />Администратор
        </span>
      </div>
      <div class="rounded-lg border border-border bg-card2 p-3 text-sm text-text2">
        <p class="mb-1 text-[11px] uppercase tracking-wide text-text3">Можно писать</p>
        Организационные вопросы: доступ к аккаунту, документы, техническая проблема.
      </div>
      <div class="mt-3 rounded-lg border border-border bg-card2 p-3 text-sm text-text2">
        <p class="mb-1 text-[11px] uppercase tracking-wide text-text3">Лучше не сюда</p>
        Жалобы на пользователей — через «Модерация» (кнопка ⚙ у любого чата, её видят все, в
        том числе можно пожаловаться на действия самого администратора). Учебные вопросы
        (оценки, расписание) — своему куратору или преподавателю.
      </div>
    </div>

    <div v-else-if="activePeer" class="flex min-h-0 flex-col">
      <!-- Плашка в цвет, выбранный самим пользователем в его профиле -->
      <div class="flex flex-col items-center p-6 text-center" :style="{ background: plate }">
        <Avatar :src="activePeer.avatar" :name="activePeer.full_name" :online="!!activePeer.online" :size="96" />
        <h2 class="mt-3 font-title text-lg font-bold text-white">{{ activePeer.full_name }}</h2>
        <span class="mt-1 inline-flex items-center gap-1 text-xs text-white/80">
          <component :is="isTeacher ? GraduationCap : UserRound" class="size-3.5" />{{ roleLabel }}
        </span>
        <span class="mt-1 inline-flex items-center gap-1.5 text-xs text-white/75">
          <span class="size-2 rounded-full"
                :style="activePeer.online ? 'background:#8ef0b4' : 'background:rgba(255,255,255,0.5)'"></span>
          {{ activePeer.online ? 'в сети' : 'не в сети' }}
        </span>
      </div>

      <div class="min-h-0 flex-1 overflow-y-auto p-6 pt-4">
        <!-- «О себе» — то, что человек написал о себе в профиле -->
        <div v-if="activePeer.bio" class="mb-3 rounded-lg border border-border bg-card2 p-3">
          <p class="mb-1 text-[11px] uppercase tracking-wide text-text3">О себе</p>
          <p class="whitespace-pre-wrap text-sm text-text2">{{ activePeer.bio }}</p>
        </div>

        <div class="w-full space-y-3 text-left">
          <div v-if="!isTeacher" class="rounded-lg border border-border bg-card2 p-3">
            <p class="text-[11px] uppercase tracking-wide text-text3">Группа</p>
            <p class="text-sm text-text">{{ activePeer.group_name || '—' }}</p>
          </div>
          <div v-else class="rounded-lg border border-border bg-card2 p-3">
            <p class="text-[11px] uppercase tracking-wide text-text3">Ведёт предметы</p>
            <p class="text-sm text-text">{{ (activePeer.subjects || []).join(', ') || '—' }}</p>
          </div>
        </div>
      </div>
    </div>

    <div v-else class="grid flex-1 place-items-center p-6 text-center text-sm text-text3">
      Выберите чат, чтобы увидеть карточку собеседника.
    </div>
  </aside>
</template>
