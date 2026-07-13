<script setup>
// Sidebar — боковая навигация (порт ui_components.Sidebar). 250px, фон bg2, секции-
// заголовки (uppercase) + пункты с иконками; активный подсвечен акцентом.
import { computed, ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { NAV } from '@/config/nav'
import { curatorApi } from '@/api/endpoints'

defineProps({ open: { type: Boolean, default: false } })
const emit = defineEmits(['navigate'])

const auth = useAuthStore()
const route = useRoute()
// Пункт «Курирование» (curatorOnly) виден только преподавателю-куратору.
const isCurator = ref(false)
onMounted(async () => {
  if (auth.role === 'teacher') {
    try { isCurator.value = ((await curatorApi.groups()).data.groups || []).length > 0 } catch { /* */ }
  }
})
const items = computed(() => (NAV[auth.role] || []).filter((it) => !it.curatorOnly || isCurator.value))

function isActive(to) {
  if (to.split('/').length <= 2) return route.path === to
  return route.path === to || route.path.startsWith(to + '/')
}
</script>

<template>
  <aside class="flex h-full w-[250px] shrink-0 flex-col overflow-y-auto border-r border-border bg-bg2 px-2.5 py-4">
    <template v-for="(item, i) in items" :key="i">
      <p v-if="item.section" class="px-2.5 pb-1 pt-3.5 text-[10px] font-medium uppercase tracking-wide text-text2 first:pt-1">
        {{ item.section }}
      </p>
      <RouterLink
        v-else
        :to="item.to"
        class="mb-0.5 flex items-center gap-2.5 rounded-sm px-3.5 py-2.5 text-sm transition-colors"
        :class="
          isActive(item.to)
            ? 'bg-accent-glow font-semibold text-accent'
            : 'font-medium text-text3 hover:bg-accent-glow hover:text-accent'
        "
        @click="emit('navigate')"
      >
        <component :is="item.icon" class="size-[18px] shrink-0" />
        <span class="truncate">{{ item.label }}</span>
      </RouterLink>
    </template>
  </aside>
</template>
