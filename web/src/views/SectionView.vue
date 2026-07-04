<script setup>
// SectionView — универсальный раздел-заглушка для страниц, чьё серверное
// role-scoped представление (/web/*) ещё не реализовано. Показывает честное
// пустое состояние и называет эндпоинт, к которому раздел подключится.
import { useRoute } from 'vue-router'
import { computed } from 'vue'
import { Wrench } from '@lucide/vue'
import EmptyState from '@/components/ui/EmptyState.vue'

const route = useRoute()
const endpoint = computed(() => route.meta?.endpoint || '')
</script>

<template>
  <EmptyState
    :icon="Wrench"
    title="Раздел готовится"
    :message="
      endpoint
        ? `Интерфейс готов. Данные появятся после реализации серверного представления ${endpoint}.`
        : 'Интерфейс готов, серверное представление подключается.'
    "
  />
</template>
