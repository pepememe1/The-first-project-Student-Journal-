<script setup>
// Skeleton — заглушки типовых форм для PageReveal (28.10.2026): ряд карточек-чисел, список,
// таблица, карточка. Форма и отступы повторяют настоящие блоки (StatCard, строки списка,
// журнал), чтобы при появлении данных ничего не прыгало.
defineProps({
  kind: { type: String, default: 'card' },   // stats | list | table | card
  count: { type: Number, default: 4 },
})
</script>

<template>
  <div v-if="kind === 'stats'" class="grid grid-cols-2 gap-3" :class="count >= 4 ? 'xl:grid-cols-4' : 'sm:grid-cols-3'">
    <div v-for="i in count" :key="i" class="gb-skeleton h-[84px] rounded-lg sm:h-[104px]" />
  </div>
  <div v-else-if="kind === 'list'" class="space-y-1.5 sm:space-y-2">
    <div v-for="i in count" :key="i" class="gb-skeleton h-11 rounded-md sm:h-12" />
  </div>
  <div v-else-if="kind === 'table'" class="rounded-lg border border-border bg-card p-3 shadow-card">
    <div class="gb-skeleton mb-2 h-9 rounded" />
    <div v-for="i in count" :key="i" class="gb-skeleton mb-2 h-8 rounded last:mb-0" />
  </div>
  <div v-else class="gb-skeleton rounded-lg" :style="{ height: `${count * 1.5}rem` }" />
</template>
