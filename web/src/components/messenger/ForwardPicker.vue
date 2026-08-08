<script setup>
// ForwardPicker — выбор беседы(-д) для пересылки сообщений. Показывает список чатов
// пользователя; можно отметить несколько и переслать. Наверх уходит список conversation_id.
import { ref } from 'vue'
import { storeToRefs } from 'pinia'
import { X, Check } from '@lucide/vue'
import { useMessengerStore } from '@/stores/messenger'
import { useLocaleStore } from '@/stores/locale'
import { profilePlate } from '@/theme/palette'
import Avatar from '@/components/ui/Avatar.vue'

defineProps({ count: { type: Number, default: 1 } })
const emit = defineEmits(['submit', 'close'])

const m = useMessengerStore()
const locale = useLocaleStore()
const { chats } = storeToRefs(m)
const chosen = ref([])

function toggle(id) {
  const i = chosen.value.indexOf(id)
  if (i >= 0) chosen.value.splice(i, 1)
  else chosen.value.push(id)
}
function initials(name) {
  const p = (name || '').trim().split(/\s+/)
  return ((p[0]?.[0] || '') + (p[1]?.[0] || '')).toUpperCase() || '?'
}
</script>

<template>
  <div class="fixed inset-0 z-50 grid place-items-center p-4" style="background: var(--gb-overlay)"
       @click.self="emit('close')">
    <div class="flex max-h-[80vh] w-full max-w-sm flex-col rounded-xl border border-border2 bg-card shadow-card">
      <div class="flex items-center justify-between border-b border-border p-4">
        <h3 class="font-title text-lg font-bold text-text">{{ locale.t('forward.title', 'Переслать') }} {{ count > 1 ? `(${count})` : '' }}</h3>
        <button type="button" @click="emit('close')" :aria-label="locale.t('common.close')"
                class="grid size-8 place-items-center rounded-md text-text3 hover:bg-bg2 hover:text-text">
          <X class="size-5" />
        </button>
      </div>

      <div class="min-h-0 flex-1 overflow-y-auto p-2">
        <p v-if="!chats.length" class="p-4 text-center text-sm text-text3">{{ locale.t('forward.noChats', 'Нет чатов для пересылки.') }}</p>
        <button v-for="c in chats" :key="c.conversation_id" type="button" @click="toggle(c.conversation_id)"
                class="flex w-full items-center gap-3 rounded-lg px-2 py-2 text-left transition-colors hover:bg-bg2">
          <!-- Личный чат — аватар собеседника; группа/канал/избранное — цветной кружок
               с инициалами (тот же приём, что в ChatList.vue). -->
          <Avatar v-if="c.kind === 'direct'" :src="c.peer?.avatar" :name="c.title"
                  :role="c.peer?.role" :color="profilePlate(c.peer?.profile_color)" :size="36" />
          <div v-else class="grid size-9 shrink-0 place-items-center rounded-full text-xs font-bold text-white"
               :class="c.kind === 'channel' ? 'bg-accent2' : 'bg-blue'">
            {{ initials(c.title) }}
          </div>
          <span class="min-w-0 flex-1 truncate text-sm text-text">{{ c.title || locale.t('messenger.dialog', 'Диалог') }}</span>
          <span class="grid size-5 shrink-0 place-items-center rounded-full border"
                :class="chosen.includes(c.conversation_id) ? 'border-accent bg-accent text-white' : 'border-border2'">
            <Check v-if="chosen.includes(c.conversation_id)" class="size-3.5" />
          </span>
        </button>
      </div>

      <div class="flex justify-end gap-2 border-t border-border p-3">
        <button type="button" @click="emit('close')"
                class="rounded-lg border border-border2 px-4 py-2 text-sm text-text2 hover:bg-bg2">{{ locale.t('common.cancel') }}</button>
        <button type="button" :disabled="!chosen.length" @click="emit('submit', chosen)"
                class="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-accent2 disabled:opacity-50">
          {{ locale.t('forward.title', 'Переслать') }}
        </button>
      </div>
    </div>
  </div>
</template>
