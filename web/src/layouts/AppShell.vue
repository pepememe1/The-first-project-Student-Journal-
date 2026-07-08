<script setup>
// AppShell — оболочка после входа (порт компоновки десктопа): широкая шапка-градиент
// СВЕРХУ на всю ширину, ниже — сайдбар слева и область контента. Каждая страница
// показывает свой заголовок (как title_lbl в десктопе). Адаптив: на телефоне
// сайдбар выезжает поверх как drawer.
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { PanelRightOpen } from '@lucide/vue'
import Sidebar from '@/components/Sidebar.vue'
import HeaderBar from '@/components/HeaderBar.vue'
import VectorDock from '@/components/VectorDock.vue'
import { useThemeStore } from '@/stores/theme'
import { useVectorStore } from '@/stores/vector'

const theme = useThemeStore()
const vector = useVectorStore()
const route = useRoute()
const sidebarOpen = ref(false)

const title = computed(() => route.meta?.title || '')
const subtitle = computed(() => route.meta?.subtitle || '')
// Боковой Вектор виден на всех страницах, КРОМЕ самой вкладки «ИИ Помощник»
// (там полноразмерный Вектор в контенте). Только десктоп (на мобиле не показываем).
const showDock = computed(() => !route.path.endsWith('/vector'))

onMounted(() => theme.loadFromPrefs())
</script>

<template>
  <div class="flex h-full flex-col overflow-hidden">
    <HeaderBar @toggle-sidebar="sidebarOpen = !sidebarOpen" />

    <div class="flex min-h-0 flex-1">
      <!-- Десктоп: постоянный сайдбар -->
      <div class="hidden lg:block">
        <Sidebar />
      </div>

      <!-- Мобайл: выезжающий сайдбар -->
      <transition name="fade">
        <div v-if="sidebarOpen" class="fixed inset-0 z-40 lg:hidden">
          <div class="absolute inset-0" style="background: var(--gb-overlay)" @click="sidebarOpen = false" />
          <div class="absolute inset-y-0 left-0 z-50 top-[60px] shadow-xl">
            <Sidebar :open="sidebarOpen" @navigate="sidebarOpen = false" />
          </div>
        </div>
      </transition>

      <!-- Контент: мягкий фон + сетка (как AnimatedBackground в десктопе) -->
      <main class="app-canvas min-h-0 flex-1 overflow-y-auto">
        <div class="mx-auto max-w-6xl p-4 sm:p-6">
          <div v-if="title" class="mb-5">
            <h1 class="font-title text-2xl font-extrabold text-text">{{ title }}</h1>
            <p v-if="subtitle" class="mt-1 text-sm text-text3">{{ subtitle }}</p>
          </div>
          <RouterView v-slot="{ Component }">
            <transition name="fade" mode="out-in">
              <component :is="Component" />
            </transition>
          </RouterView>
        </div>
      </main>

      <!-- Постоянный боковой Вектор (десктоп): справа поверх всех страниц, кроме вкладки
           «ИИ Помощник». Переписка общая со вкладкой (Pinia-store vector). Можно скрыть. -->
      <div v-if="showDock && !vector.collapsed" class="hidden lg:block">
        <VectorDock />
      </div>
    </div>

    <!-- Панель скрыта → вкладка-возврат у правого края (десктоп). -->
    <button v-if="showDock && vector.collapsed" @click="vector.setCollapsed(false)"
            aria-label="Показать панель Вектора" title="Показать Вектора"
            class="fixed right-0 top-1/2 z-30 hidden -translate-y-1/2 items-center gap-2 rounded-l-xl border border-r-0 border-border bg-card py-3 pl-2.5 pr-2 text-accent shadow-card transition-colors hover:bg-accent-glow lg:flex">
      <PanelRightOpen class="size-5" />
      <span class="text-xs font-semibold" style="writing-mode: vertical-rl; transform: rotate(180deg)">Вектор</span>
    </button>
  </div>
</template>

<style scoped>
/* Мягкий градиент bg→bg2 + едва заметная акцентная сетка — как статичный
   AnimatedBackground в десктопе. */
.app-canvas {
  background:
    linear-gradient(180deg, var(--gb-bg), var(--gb-bg2)),
    repeating-linear-gradient(0deg, transparent 0 63px, color-mix(in srgb, var(--gb-accent) 4%, transparent) 63px 64px),
    repeating-linear-gradient(90deg, transparent 0 63px, color-mix(in srgb, var(--gb-accent) 4%, transparent) 63px 64px);
}
.fade-enter-active,
.fade-leave-active { transition: opacity 0.15s ease; }
.fade-enter-from,
.fade-leave-to { opacity: 0; }
</style>
