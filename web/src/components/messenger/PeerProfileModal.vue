<script setup>
// PeerProfileModal — открывается кликом по аватарке/имени человека где угодно в
// мессенджере (участник группы/канала), как в Discord. Сама карточка — PeerProfileCard
// (общий компонент, см. её докстринг); правая колонка «Общие каналы»/«Общие группы» —
// SharedGroupsChannels (общий и с ConversationInfo.vue, см. её докстринг — 3.6.1).
import { computed } from 'vue'
import { X } from '@lucide/vue'
import { useLocaleStore } from '@/stores/locale'
import PeerProfileCard from '@/components/messenger/PeerProfileCard.vue'
import SharedGroupsChannels from '@/components/messenger/SharedGroupsChannels.vue'

const props = defineProps({
  userId: { type: String, default: '' },
  peerData: { type: Object, default: null },
})
const emit = defineEmits(['close'])
const locale = useLocaleStore()

const targetId = computed(() => props.userId || props.peerData?.id || '')
</script>

<template>
  <!-- ⚠️ Окно во ВЕСЬ экран с небольшим отступом, а не карточка на 768 px (правка
       23.08.2026 по живому отзыву). Причина предметная: у профиля есть баннер и
       крупная аватарка, и в узкой колонке баннер сжимался в полоску — то есть ровно
       то, ради чего его заводили, разглядеть было нельзя. Так же сделано в Discord.
       Отступ оставлен намеренно: окно без полей перестаёт читаться как окно, и
       становится непонятно, куда кликать, чтобы закрыть. -->
  <div class="fixed inset-0 z-50 grid place-items-center p-3 sm:p-6" style="background: var(--gb-overlay)"
       @click.self="emit('close')">
    <div class="flex h-full max-h-full w-full overflow-hidden rounded-xl shadow-card"
         style="padding: env(safe-area-inset-top) 0 env(safe-area-inset-bottom)">
      <div class="min-h-0 flex-1 overflow-y-auto">
        <PeerProfileCard :user-id="userId" :peer-data="peerData" @messaged="emit('close')" />
      </div>
      <SharedGroupsChannels :user-id="targetId" class="hidden sm:block" @navigate="emit('close')" />
    </div>
    <button type="button" @click="emit('close')" :aria-label="locale.t('common.close')"
            class="fixed right-4 top-4 grid size-9 place-items-center rounded-full bg-card text-text3 shadow-card hover:text-text sm:right-6 sm:top-6">
      <X class="size-5" />
    </button>
  </div>
</template>
