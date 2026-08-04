<script setup>
// PeerProfileModal — открывается кликом по аватарке/имени человека где угодно в
// мессенджере (участник группы/канала, собеседник ЛС), как в Discord. Сама карточка —
// PeerProfileCard (общий компонент, см. его докстринг); здесь только оболочка модалки +
// правая колонка «Общие каналы»/«Общие группы» — ЗАГОТОВКА (заголовки без данных, как
// «Эффекты профиля» на своей карточке, см. Profile.vue): реальный запрос пересечения
// бесед — отдельная по объёму задача, не часть этого захода.
import { X, Radio, Users } from '@lucide/vue'
import { useLocaleStore } from '@/stores/locale'
import PeerProfileCard from '@/components/messenger/PeerProfileCard.vue'

defineProps({
  userId: { type: String, default: '' },
  peerData: { type: Object, default: null },
})
const emit = defineEmits(['close'])
const locale = useLocaleStore()
</script>

<template>
  <div class="fixed inset-0 z-50 grid place-items-center p-4" style="background: var(--gb-overlay)"
       @click.self="emit('close')">
    <div class="flex max-h-[85vh] w-full max-w-3xl overflow-hidden rounded-xl">
      <div class="min-h-0 flex-1 overflow-y-auto">
        <PeerProfileCard :user-id="userId" :peer-data="peerData" @messaged="emit('close')" />
      </div>
      <!-- Резерв места под будущее — не запрашиваем и не считаем ничего, только каркас. -->
      <div class="hidden w-56 shrink-0 border-l border-border2 bg-card p-4 sm:block">
        <p class="mb-3 flex items-center gap-1.5 text-[11px] uppercase tracking-wide text-text3">
          <Users class="size-3.5" />{{ locale.t('peerProfile.sharedGroups', 'Общие группы') }}
        </p>
        <p class="mb-4 text-xs text-text3">{{ locale.t('peerProfile.soon', 'Скоро') }}</p>
        <p class="mb-3 flex items-center gap-1.5 text-[11px] uppercase tracking-wide text-text3">
          <Radio class="size-3.5" />{{ locale.t('peerProfile.sharedChannels', 'Общие каналы') }}
        </p>
        <p class="text-xs text-text3">{{ locale.t('peerProfile.soon', 'Скоро') }}</p>
      </div>
    </div>
    <button type="button" @click="emit('close')" :aria-label="locale.t('common.close')"
            class="fixed right-4 top-4 grid size-9 place-items-center rounded-full bg-card text-text3 shadow-card hover:text-text sm:right-6 sm:top-6">
      <X class="size-5" />
    </button>
  </div>
</template>
