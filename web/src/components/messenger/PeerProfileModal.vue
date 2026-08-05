<script setup>
// PeerProfileModal — открывается кликом по аватарке/имени человека где угодно в
// мессенджере (участник группы/канала, собеседник ЛС), как в Discord. Сама карточка —
// PeerProfileCard (общий компонент, см. его докстринг); здесь — оболочка модалки + правая
// колонка «Общие каналы»/«Общие группы»: пересечение бесед с человеком (GET .../shared),
// клик по строке открывает ту беседу и закрывает модалку — тот же переход, что у кнопки
// «Сообщение» в самой карточке.
import { ref, onMounted, watch, computed } from 'vue'
import { X, Radio, Users } from '@lucide/vue'
import { useRouter } from 'vue-router'
import { useLocaleStore } from '@/stores/locale'
import { useAuthStore } from '@/stores/auth'
import { useMessengerStore } from '@/stores/messenger'
import { messengerApi } from '@/api/endpoints'
import PeerProfileCard from '@/components/messenger/PeerProfileCard.vue'

const props = defineProps({
  userId: { type: String, default: '' },
  peerData: { type: Object, default: null },
})
const emit = defineEmits(['close'])
const locale = useLocaleStore()
const auth = useAuthStore()
const messenger = useMessengerStore()
const router = useRouter()

const targetId = computed(() => props.userId || props.peerData?.id || '')
const groups = ref([])
const channels = ref([])
async function loadShared() {
  groups.value = []
  channels.value = []
  if (!targetId.value) return
  try {
    const { data } = await messengerApi.shared(targetId.value)
    groups.value = data.groups || []
    channels.value = data.channels || []
  } catch { /* нет доступа/сервера — тихо, список останется пустым */ }
}
onMounted(loadShared)
watch(targetId, loadShared)

async function openConversation(conv) {
  await messenger.selectChat({ conversation_id: conv.id, title: conv.title })
  router.push(`/${auth.role}/messages`)
  emit('close')
}
</script>

<template>
  <div class="fixed inset-0 z-50 grid place-items-center p-4" style="background: var(--gb-overlay)"
       @click.self="emit('close')">
    <div class="flex max-h-[85vh] w-full max-w-3xl overflow-hidden rounded-xl">
      <div class="min-h-0 flex-1 overflow-y-auto">
        <PeerProfileCard :user-id="userId" :peer-data="peerData" @messaged="emit('close')" />
      </div>
      <div class="hidden w-56 shrink-0 overflow-y-auto border-l border-border2 bg-card p-4 sm:block">
        <p class="mb-2 flex items-center gap-1.5 text-[11px] uppercase tracking-wide text-text3">
          <Users class="size-3.5" />{{ locale.t('peerProfile.sharedGroups', 'Общие группы') }}
        </p>
        <ul v-if="groups.length" class="mb-4 space-y-0.5">
          <li v-for="g in groups" :key="g.id">
            <button type="button" @click="openConversation(g)"
                    class="block w-full truncate rounded-md px-2 py-1.5 text-left text-sm text-text2 hover:bg-bg2 hover:text-text">
              {{ g.title }}
            </button>
          </li>
        </ul>
        <p v-else class="mb-4 text-xs text-text3">{{ locale.t('peerProfile.noneYet', 'Пока нет') }}</p>

        <p class="mb-2 flex items-center gap-1.5 text-[11px] uppercase tracking-wide text-text3">
          <Radio class="size-3.5" />{{ locale.t('peerProfile.sharedChannels', 'Общие каналы') }}
        </p>
        <ul v-if="channels.length" class="space-y-0.5">
          <li v-for="c in channels" :key="c.id">
            <button type="button" @click="openConversation(c)"
                    class="block w-full truncate rounded-md px-2 py-1.5 text-left text-sm text-text2 hover:bg-bg2 hover:text-text">
              {{ c.title }}
            </button>
          </li>
        </ul>
        <p v-else class="text-xs text-text3">{{ locale.t('peerProfile.noneYet', 'Пока нет') }}</p>
      </div>
    </div>
    <button type="button" @click="emit('close')" :aria-label="locale.t('common.close')"
            class="fixed right-4 top-4 grid size-9 place-items-center rounded-full bg-card text-text3 shadow-card hover:text-text sm:right-6 sm:top-6">
      <X class="size-5" />
    </button>
  </div>
</template>
