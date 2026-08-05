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
  <div class="fixed inset-0 z-50 grid place-items-center p-4" style="background: var(--gb-overlay)"
       @click.self="emit('close')">
    <div class="flex max-h-[85vh] w-full max-w-3xl overflow-hidden rounded-xl">
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
