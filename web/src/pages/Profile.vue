<script setup>
// Profile — «Профиль» (порт dashboards "profile"): карточка пользователя + оформление
// (тема роумится через /me/prefs, поэтому доступна каждому — как у студента в проге).
import { computed } from 'vue'
import { Check } from '@lucide/vue'
import { useAuthStore } from '@/stores/auth'
import { useThemeStore } from '@/stores/theme'
import { PRESETS, swatchColors } from '@/theme/palette'
import Card from '@/components/ui/Card.vue'
import AppButton from '@/components/ui/AppButton.vue'

const auth = useAuthStore()
const theme = useThemeStore()
const ROLE = { student: 'Студент', teacher: 'Преподаватель', admin: 'Администратор' }
const initial = computed(() => (auth.user?.name || '?').trim().charAt(0).toUpperCase())
const currentId = computed(() => theme.spec.id)
function swatch(id) { const [a, b] = swatchColors({ ...theme.spec, id }); return { a, b } }
</script>

<template>
  <div class="space-y-6">
    <Card>
      <div class="flex items-center gap-4">
        <div class="grid size-16 place-items-center rounded-full bg-accent text-2xl font-extrabold text-white">{{ initial }}</div>
        <div>
          <p class="font-title text-xl font-extrabold text-text">{{ auth.user?.name }}</p>
          <p class="text-sm text-text3">{{ ROLE[auth.role] }} · {{ auth.user?.login }}</p>
        </div>
      </div>
    </Card>

    <Card title="Оформление" subtitle="Тема сохраняется за вашим аккаунтом">
      <div class="mb-4 flex gap-2">
        <AppButton :variant="theme.isDark ? 'ghost' : 'green'" @click="theme.setMode('light')">Светлая</AppButton>
        <AppButton :variant="theme.isDark ? 'green' : 'ghost'" @click="theme.setMode('dark')">Тёмная</AppButton>
      </div>
      <div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <button v-for="p in PRESETS" :key="p.id" type="button"
                class="flex items-center gap-2.5 rounded-md border p-2.5 text-left transition-colors"
                :class="currentId === p.id ? 'border-accent bg-accent-glow' : 'border-border hover:border-accent'"
                @click="theme.setPreset(p.id)">
          <span class="grid size-7 shrink-0 place-items-center rounded-full border border-black/10"
                :style="{ background: `linear-gradient(135deg, ${swatch(p.id).a}, ${swatch(p.id).b})` }">
            <Check v-if="currentId === p.id" class="size-3.5 text-white" />
          </span>
          <span class="truncate text-xs font-medium text-text">{{ p.name }}</span>
        </button>
      </div>
    </Card>
  </div>
</template>
