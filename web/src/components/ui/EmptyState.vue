<script setup>
// EmptyState — аккуратная заглушка для разделов без данных / ещё не подключённого API.
import { Inbox } from '@lucide/vue'
defineProps({
  title: { type: String, default: 'Пока пусто' },
  message: { type: String, default: '' },
  icon: { type: [Object, Function], default: null },
})
</script>

<template>
  <div class="flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-border2 bg-card2/50 px-6 py-14 text-center">
    <component :is="icon || Inbox" class="size-9 text-text2" />
    <p class="font-title text-lg font-semibold text-text">{{ title }}</p>
    <p v-if="message" class="max-w-md text-sm text-text3">{{ message }}</p>
    <slot />
  </div>
</template>
