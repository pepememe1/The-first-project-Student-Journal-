<script setup>
// HeaderBar — верхняя полоса (порт ui_components.HeaderBar): широкий ГРАДИЕНТ
// фирменного акцента (green→green2), белый текст, лого GB + название + колледж,
// бейдж роли, имя пользователя, выход. На телефоне — кнопка-гамбургер.
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { Menu, Moon, Sun, LogOut } from '@lucide/vue'
import { useAuthStore } from '@/stores/auth'
import { useThemeStore } from '@/stores/theme'

const emit = defineEmits(['toggle-sidebar'])
const router = useRouter()
const auth = useAuthStore()
const theme = useThemeStore()

const ROLE_LABEL = { student: 'Студент', teacher: 'Преподаватель', admin: 'Администратор' }
const roleLabel = computed(() => ROLE_LABEL[auth.role] || '')
const showName = computed(() => {
  const n = (auth.user?.name || '').trim()
  return n && n.toLowerCase() !== roleLabel.value.toLowerCase() ? n : ''
})

async function onLogout() {
  await auth.logout()
  router.push('/login')
}
</script>

<template>
  <header
    class="flex h-[60px] shrink-0 items-center gap-3 px-4 text-white sm:px-5"
    style="background: linear-gradient(90deg, var(--gb-accent), var(--gb-accent2)); border-bottom: 1px solid var(--gb-accent2);"
  >
    <button
      class="grid size-9 place-items-center rounded-md text-white/90 hover:bg-white/15 lg:hidden"
      aria-label="Меню" @click="emit('toggle-sidebar')"
    >
      <Menu class="size-5" />
    </button>

    <!-- Лого GB + название + колледж -->
    <div class="grid size-8 place-items-center rounded-md text-[11px] font-extrabold"
         style="background: rgba(255,255,255,0.16); border: 1.5px solid rgba(255,255,255,0.55);">
      GB
    </div>
    <div class="min-w-0 leading-tight">
      <p class="font-title text-[15px] font-extrabold tracking-wide">GRADEBOOK</p>
      <!-- Полное название колледжа — только с sm: на телефоне места нет, обрезка выглядела криво. -->
      <p class="hidden truncate text-[10px] font-semibold text-white/80 sm:block">Технологический колледж ВСГУТУ</p>
    </div>

    <div class="min-w-2 flex-1" />

    <!-- Переключатель темы (тёмная/светлая) -->
    <button
      class="grid size-9 shrink-0 place-items-center rounded-md text-white/90 hover:bg-white/15"
      :aria-label="theme.isDark ? 'Светлая тема' : 'Тёмная тема'" @click="theme.toggleMode()"
    >
      <Sun v-if="theme.isDark" class="size-5" />
      <Moon v-else class="size-5" />
    </button>

    <!-- Бейдж роли + имя -->
    <span class="hidden items-center rounded-full px-3 py-1 text-[11px] font-medium sm:inline-flex"
          style="background: rgba(255,255,255,0.18); border: 1px solid rgba(255,255,255,0.5);">
      {{ roleLabel }}
    </span>
    <span v-if="showName" class="hidden max-w-[220px] truncate text-[13px] text-white/95 md:inline">
      {{ showName }}
    </span>

    <span class="mx-1 hidden h-5 w-px bg-white/30 sm:block" />

    <button
      class="inline-flex shrink-0 items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium text-white sm:px-3"
      style="background: rgba(255,255,255,0.15); border: 1px solid rgba(255,255,255,0.5);"
      @click="onLogout"
    >
      <LogOut class="size-4" />
      <span class="hidden sm:inline">Выйти</span>
    </button>
  </header>
</template>
