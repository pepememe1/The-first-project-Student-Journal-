<script setup>
// SharedGroupsChannels — правая колонка «Общие группы»/«Общие каналы» карточки
// профиля (Discord-style). Общий компонент для ДВУХ мест, которые обязаны выглядеть
// одинаково (заказчик прямо просил «по аналогии»): PeerProfileModal.vue (профиль
// участника группы/канала, открывается ВТОРЫМ уровнем) и ConversationInfo.vue (профиль
// собеседника в ЛС — там карточка теперь ПЕРВЫЙ и единственный уровень, см. её
// докстринг про 3.6.1). Пересечение бесед — GET .../shared (см. её докстринг на
// сервере): безопасно по построению, раскрывает только то, в чём вызывающий и так
// уже состоит.
import { ref, onMounted, watch, computed } from 'vue'
import { Radio, Users } from '@lucide/vue'
import { useRouter } from 'vue-router'
import { useLocaleStore } from '@/stores/locale'
import { useAuthStore } from '@/stores/auth'
import { useMessengerStore } from '@/stores/messenger'
import { messengerApi } from '@/api/endpoints'

const props = defineProps({
  userId: { type: String, default: '' },
})
const emit = defineEmits(['navigate'])   // сообщаем родителю «пора закрыться» — переход состоялся
const locale = useLocaleStore()
const auth = useAuthStore()
const messenger = useMessengerStore()
const router = useRouter()

const groups = ref([])
const channels = ref([])
async function loadShared() {
  groups.value = []
  channels.value = []
  if (!props.userId) return
  try {
    const { data } = await messengerApi.shared(props.userId)
    groups.value = data.groups || []
    channels.value = data.channels || []
  } catch { /* нет доступа/сервера — тихо, список останется пустым */ }
}
onMounted(loadShared)
watch(() => props.userId, loadShared)

async function openConversation(conv) {
  await messenger.selectChat({ conversation_id: conv.id, title: conv.title })
  router.push(`/${auth.role}/messages`)
  emit('navigate')
}
</script>

<template>
  <div class="w-56 shrink-0 overflow-y-auto border-l border-border2 bg-card p-4">
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
</template>
