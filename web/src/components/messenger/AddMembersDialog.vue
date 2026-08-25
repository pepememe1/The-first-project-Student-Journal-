<script setup>
// AddMembersDialog — «Добавить участников» в уже существующую беседу.
//
// 🔥 ДО 25.08.2026 ЭТОГО НЕ БЫЛО ВОВСЕ. Серверная ручка `POST /chats/{id}/members`
// работала с самого начала, но её не звал НИКТО: добавить человека в группу через
// продукт было нельзя, только правкой базы руками. Влад сообщил это как «в беседы
// невозможно добавить новых людей».
//
// ⚠️ Поиск и правила отбора — ТЕ ЖЕ, что при создании беседы (`CreateChatDialog`):
// тот же каталог, те же вкладки ролей, тот же режим куратора «добавить целую учебную
// группу». Второй набор правил доступа разошёлся бы с первым, и разойтись он мог бы
// молча — в сторону «видно лишних людей».
//
// ⚠️ Кого показывать, решает СЕРВЕР (`messengerApi.users` работает по белому списку
// ролей, родителей выдаёт только админу и настоящему куратору). Здесь лишь прячем тех,
// кто уже в беседе, — чтобы не предлагать бессмысленное действие.
import { ref, watch, computed, onMounted } from 'vue'
import { X, Search, Check, UserPlus } from '@lucide/vue'
import { messengerApi, curatorApi } from '@/api/endpoints'
import { useAuthStore } from '@/stores/auth'
import { useLocaleStore } from '@/stores/locale'
import Avatar from '@/components/ui/Avatar.vue'

const props = defineProps({
  // Кто уже в беседе — их не предлагаем.
  existingIds: { type: Array, default: () => [] },
  kind: { type: String, default: 'group' },      // group | channel
  busy: { type: Boolean, default: false },
})
const emit = defineEmits(['add', 'close'])

const auth = useAuthStore()
const locale = useLocaleStore()
const isChannel = computed(() => props.kind === 'channel')

const role = ref('student')
const q = ref('')
const found = ref([])
const chosen = ref([])
let debounce = null

const already = computed(() => new Set(props.existingIds))

async function search() {
  try {
    const { data } = await messengerApi.users(role.value, q.value)
    found.value = (data.users || []).filter((u) => !already.value.has(u.id))
  } catch { found.value = [] }
}
watch([role, q], () => { clearTimeout(debounce); debounce = setTimeout(search, 250) })
search()

function toggle(u) {
  const i = chosen.value.findIndex((x) => x.id === u.id)
  if (i >= 0) chosen.value.splice(i, 1)
  else chosen.value.push({ id: u.id, full_name: u.full_name })
}
const isChosen = (id) => chosen.value.some((x) => x.id === id)

// Режим куратора: разом добавить всю учебную группу. Список — ТОЛЬКО собственные
// curated_groups; сервер это проверит ещё раз и чужие имена молча отбросит.
const curatedGroups = ref([])
const chosenGroups = ref([])
onMounted(async () => {
  if (auth.role !== 'teacher') return
  try { curatedGroups.value = (await curatorApi.groups()).data.groups || [] } catch { /* не куратор */ }
})
function toggleGroup(g) {
  const i = chosenGroups.value.indexOf(g)
  if (i >= 0) chosenGroups.value.splice(i, 1)
  else chosenGroups.value.push(g)
}

const roleTabs = computed(() => {
  const t = [['student', locale.t('messenger.tab.student', 'Студенты')],
             ['teacher', locale.t('createChat.teachers', 'Преподаватели')]]
  if (curatedGroups.value.length) t.push(['parent', locale.t('messenger.tab.parent', 'Родители')])
  return t
})

const total = computed(() => chosen.value.length + chosenGroups.value.length)

function submit() {
  if (!total.value || props.busy) return
  emit('add', { userIds: chosen.value.map((x) => x.id), classGroups: [...chosenGroups.value] })
}
</script>

<template>
  <div class="fixed inset-0 z-50 grid place-items-center p-4" style="background: var(--gb-overlay)"
       @click.self="emit('close')">
    <div class="flex max-h-[85vh] w-full max-w-md flex-col overflow-hidden rounded-xl border border-border bg-card shadow-xl">

      <div class="flex items-center justify-between border-b border-border px-4 py-3">
        <h3 class="flex items-center gap-2 text-sm font-semibold">
          <UserPlus :size="16" />
          {{ isChannel
             ? locale.t('members.addToChannel', 'Добавить читателей')
             : locale.t('members.addToGroup', 'Добавить участников') }}
        </h3>
        <button type="button" class="text-text3 hover:text-text" :aria-label="locale.t('common.close', 'Закрыть')"
                @click="emit('close')">
          <X :size="18" />
        </button>
      </div>

      <div class="min-h-0 flex-1 overflow-y-auto p-4">
        <!-- Целая учебная группа — только настоящему куратору и только в группу. -->
        <div v-if="curatedGroups.length && !isChannel" class="mb-4">
          <p class="mb-1.5 text-xs text-text3">
            {{ locale.t('createChat.wholeGroup', 'Добавить целую группу') }}
          </p>
          <div class="flex flex-wrap gap-1.5">
            <button v-for="g in curatedGroups" :key="g" type="button" @click="toggleGroup(g)"
                    class="rounded-md border px-2 py-1 text-xs transition-colors"
                    :class="chosenGroups.includes(g)
                      ? 'border-accent bg-accent-glow text-accent'
                      : 'border-border text-text2 hover:text-text'">
              {{ g }}
            </button>
          </div>
        </div>

        <div class="mb-2 flex gap-1.5">
          <button v-for="[val, label] in roleTabs" :key="val" type="button" @click="role = val"
                  class="rounded-md px-2.5 py-1 text-xs transition-colors"
                  :class="role === val ? 'bg-accent-glow text-accent' : 'text-text3 hover:text-text'">
            {{ label }}
          </button>
        </div>

        <label class="mb-3 flex items-center gap-2 rounded-lg border border-border px-2.5 py-1.5">
          <Search :size="14" class="shrink-0 text-text3" />
          <input v-model="q" type="search" class="w-full bg-transparent text-sm outline-none"
                 :placeholder="locale.t('members.searchPlaceholder', 'Поиск по ФИО…')" />
        </label>

        <!-- Уже выбранные — чипами, чтобы длинный список не заставлял искать их заново. -->
        <div v-if="chosen.length" class="mb-3 flex flex-wrap gap-1.5">
          <span v-for="p in chosen" :key="p.id"
                class="flex items-center gap-1 rounded-md bg-accent-glow px-2 py-0.5 text-xs text-accent">
            {{ p.full_name }}
            <button type="button" class="hover:text-red" @click="toggle({ id: p.id })"
                    :aria-label="locale.t('common.remove', 'Убрать')">✕</button>
          </span>
        </div>

        <p v-if="!found.length" class="py-6 text-center text-xs text-text3">
          {{ q
             ? locale.t('members.nobodyFound', 'Никого не найдено')
             : locale.t('members.allAlreadyHere', 'Все, кого можно добавить, уже в беседе') }}
        </p>

        <div v-else class="flex flex-col gap-0.5">
          <button v-for="u in found" :key="u.id" type="button" @click="toggle(u)"
                  class="flex items-center gap-2.5 rounded-lg px-2 py-1.5 text-left transition-colors hover:bg-bg2">
            <Avatar :name="u.full_name" :src="u.avatar_url" :size="28" />
            <span class="min-w-0 flex-1">
              <span class="block truncate text-sm">{{ u.full_name }}</span>
              <span v-if="u.groups?.length" class="block truncate text-[11px] text-text3">{{ u.groups.join(', ') }}</span>
            </span>
            <Check v-if="isChosen(u.id)" :size="15" class="shrink-0 text-accent" />
          </button>
        </div>
      </div>

      <div class="flex items-center justify-between gap-3 border-t border-border px-4 py-3">
        <span class="text-xs text-text3">
          {{ total ? locale.t('members.chosenCount', { n: total }) : '' }}
        </span>
        <button type="button" :disabled="!total || busy" @click="submit"
                class="rounded-lg bg-accent px-4 py-1.5 text-sm font-semibold text-white
                       disabled:cursor-not-allowed disabled:opacity-40 hover:brightness-110">
          {{ locale.t('common.add', 'Добавить') }}
        </button>
      </div>
    </div>
  </div>
</template>
