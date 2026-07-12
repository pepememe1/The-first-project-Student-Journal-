<script setup>
// HeaderBar — верхняя полоса (порт ui_components.HeaderBar): СПЛОШНОЙ акцентный фон
// (в десктопе от горизонтального градиента отказались — он давал видимую полосу-
// «обрыв»), белый текст, лого GB + «GradeBookAI» + колледж, индикатор онлайн, бейдж
// роли, имя пользователя, выход. На телефоне — кнопка-гамбургер.
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
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
// Имя показываем, только если оно есть и не дублирует роль (как set_role в десктопе:
// у админа «личность» = «Администратор», второй раз не выводим).
const showName = computed(() => {
  const n = (auth.user?.name || '').trim()
  return n && n.toLowerCase() !== roleLabel.value.toLowerCase() ? n : ''
})

// Индикатор связи (порт HeaderBar.set_online): маленький цветной кружок + короткое
// слово. На вебе состояние берём из navigator.onLine (есть ли у браузера сеть).
const online = ref(navigator.onLine)
function updateOnline() { online.value = navigator.onLine }
onMounted(() => {
  window.addEventListener('online', updateOnline)
  window.addEventListener('offline', updateOnline)
})
onBeforeUnmount(() => {
  window.removeEventListener('online', updateOnline)
  window.removeEventListener('offline', updateOnline)
})

async function onLogout() {
  await auth.logout()
  router.push('/login')
}
</script>

<template>
  <header
    class="flex shrink-0 items-center gap-2.5 px-4 text-white sm:px-5"
    style="background: var(--gb-accent); border-bottom: 1px solid rgba(0,0,0,0.14);
           height: calc(60px + env(safe-area-inset-top)); padding-top: env(safe-area-inset-top);"
  >
    <button
      class="grid size-9 place-items-center rounded-md text-white/90 hover:bg-white/15 lg:hidden"
      aria-label="Меню" @click="emit('toggle-sidebar')"
    >
      <Menu class="size-5" />
    </button>

    <!-- Лого GB + «GradeBookAI» + колледж -->
    <div class="grid size-8 place-items-center rounded-md text-[11px] font-extrabold"
         style="background: rgba(255,255,255,0.16); border: 1.5px solid rgba(255,255,255,0.55);">
      GB
    </div>
    <div class="min-w-0 leading-tight">
      <!-- Фирменное написание «GradeBookAI» (как на экране входа), НЕ капсом «GRADEBOOK».
           Шрифт — основной (DM Sans), как в десктопной шапке. -->
      <p class="text-base font-extrabold tracking-[0.2px]">GradeBookAI</p>
      <!-- Полное название колледжа — только с sm: на телефоне места нет. -->
      <p class="hidden truncate text-[10px] font-semibold text-white/80 sm:block">Технологический колледж ВСГУТУ</p>
    </div>

    <div class="min-w-2 flex-1" />

    <!-- Индикатор связи с сервером (онлайн/офлайн) — как в десктопной шапке -->
    <span class="hidden items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold text-white/90 sm:inline-flex"
          style="background: rgba(255,255,255,0.12);"
          :title="online ? 'Есть связь с сервером колледжа.' : 'Нет связи с сетью — данные подтянутся, когда связь вернётся.'">
      <span class="text-[14px] leading-none" :style="{ color: online ? '#3ddc84' : '#ff8a8a' }">●</span>
      {{ online ? 'Онлайн' : 'Офлайн' }}
    </span>

    <!-- Переключатель темы (тёмная/светлая) -->
    <button
      class="grid size-9 shrink-0 place-items-center rounded-md text-white/90 hover:bg-white/15"
      :aria-label="theme.isDark ? 'Светлая тема' : 'Тёмная тема'" @click="theme.toggleMode()"
    >
      <Sun v-if="theme.isDark" class="size-5" />
      <Moon v-else class="size-5" />
    </button>

    <!-- Бейдж роли — тот же тихий стиль, что и индикатор онлайн (без яркой обводки) -->
    <span class="hidden items-center rounded-full px-[11px] py-[3px] text-[11px] font-semibold text-white/90 sm:inline-flex"
          style="background: rgba(255,255,255,0.12);">
      {{ roleLabel }}
    </span>
    <span v-if="showName" class="hidden max-w-[420px] truncate text-[13px] text-white md:inline">
      {{ showName }}
    </span>

    <span class="mx-1 hidden h-5 w-px bg-white/30 sm:block" />

    <button
      class="inline-flex shrink-0 items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium text-white transition-colors sm:px-3.5"
      style="background: rgba(255,255,255,0.15); border: 1px solid rgba(255,255,255,0.5);"
      @click="onLogout"
      @mouseover="(e) => (e.currentTarget.style.background = 'rgba(255,255,255,0.28)')"
      @mouseout="(e) => (e.currentTarget.style.background = 'rgba(255,255,255,0.15)')"
    >
      <LogOut class="size-4" />
      <span class="hidden sm:inline">Выйти</span>
    </button>
  </header>
</template>
