<script setup>
// AppShell — оболочка после входа (порт компоновки десктопа): широкая шапка-градиент
// СВЕРХУ на всю ширину, ниже — сайдбар слева и область контента. Каждая страница
// показывает свой заголовок (как title_lbl в десктопе). Адаптив: на телефоне
// сайдбар выезжает поверх как drawer.
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRoute } from 'vue-router'
import { PanelRightOpen } from '@lucide/vue'
import Sidebar from '@/components/Sidebar.vue'
import HeaderBar from '@/components/HeaderBar.vue'
import VectorDock from '@/components/VectorDock.vue'
import { useThemeStore } from '@/stores/theme'
import { useVectorStore } from '@/stores/vector'
import { useTtsStore } from '@/stores/tts'
import { useMessengerStore } from '@/stores/messenger'

const theme = useThemeStore()
const vector = useVectorStore()
const tts = useTtsStore()
const messenger = useMessengerStore()
const route = useRoute()
const sidebarOpen = ref(false)

// Embed-режим: тот же SPA, встроенный в ДЕСКТОП (QWebEngineView, см. ui/messenger_web.py).
// Прячем собственную навигацию/шапку/док — их роль на десктопе играет нативная оболочка,
// иначе получилась бы «навигация внутри навигации». Десктоп ставит флаг gb.embed ДО
// загрузки страницы (плюс поддерживаем ?embed=1 в URL). Значение фиксируется на загрузке.
const embed = (() => {
  try {
    const q = new URLSearchParams(window.location.search)
    return q.get('embed') === '1' || localStorage.getItem('gb.embed') === '1'
  } catch { return false }
})()

const title = computed(() => route.meta?.title || '')
const subtitle = computed(() => route.meta?.subtitle || '')
// Боковой Вектор виден на всех страницах, КРОМЕ самой вкладки «ИИ Помощник»
// (там полноразмерный Вектор в контенте). Только десктоп (на мобиле не показываем).
const onVectorPage = computed(() => route.path.endsWith('/vector'))
const showDock = computed(() => !onVectorPage.value)

// «Вектор виден» = полноэкранный на вкладке ИИ ЛИБО открытая боковая шторка (шторка —
// только на широком экране lg, на мобиле её нет). Озвучка звучит, пока виден хоть один
// Вектор, и обрывается РОВНО когда пропал последний: ушли на вкладку без шторки — тишина;
// на вкладке шторка открыта — Вектор договаривает; закрыли шторку — тишина.
const isLg = ref(typeof window !== 'undefined' && window.matchMedia('(min-width:1024px)').matches)
let _mq = null
const _onMq = (e) => { isLg.value = e.matches }
if (typeof window !== 'undefined') {
  _mq = window.matchMedia('(min-width:1024px)')
  _mq.addEventListener('change', _onMq)
}
const dockShown = computed(() => showDock.value && !vector.collapsed && isLg.value)
const vectorShown = computed(() => onVectorPage.value || dockShown.value)
watch(vectorShown, (now, was) => { if (was && !now) tts.stop() })

// Фоновый счётчик непрочитанных для бейджа «Сообщения» в меню (живёт на всех страницах).
// На самой вкладке мессенджера свой опрос чаще — этот лишь держит бейдж свежим глобально.
let _unreadTimer = null
onMounted(() => {
  theme.loadFromPrefs()
  messenger.loadChats()
  _unreadTimer = setInterval(() => messenger.loadChats(), 20000)
})
onBeforeUnmount(() => {
  if (_mq) _mq.removeEventListener('change', _onMq)
  if (_unreadTimer) clearInterval(_unreadTimer)
})
</script>

<template>
  <div class="flex h-full flex-col overflow-hidden">
    <HeaderBar v-if="!embed" @toggle-sidebar="sidebarOpen = !sidebarOpen" />

    <div class="flex min-h-0 flex-1">
      <!-- Десктоп: постоянный сайдбар -->
      <div v-if="!embed" class="hidden lg:block">
        <Sidebar />
      </div>

      <!-- Мобайл: выезжающий сайдбар -->
      <transition name="fade">
        <div v-if="sidebarOpen" class="fixed inset-0 z-40 lg:hidden">
          <div class="absolute inset-0" style="background: var(--gb-overlay)" @click="sidebarOpen = false" />
          <div class="absolute inset-y-0 left-0 z-50 shadow-xl" style="top: calc(60px + env(safe-area-inset-top))">
            <Sidebar :open="sidebarOpen" @navigate="sidebarOpen = false" />
          </div>
        </div>
      </transition>

      <!-- Контент: мягкий фон + сетка (как AnimatedBackground в десктопе) -->
      <main class="app-canvas min-h-0 flex-1 overflow-y-auto" style="padding-bottom: env(safe-area-inset-bottom)">
        <!-- Контент тянется на всю ширину области (как в десктопе — там сетка не
             ограничена узкой колонкой), с очень высоким потолком, чтобы на 4K не
             растягивалось до нечитаемых строк. -->
        <div :class="embed ? 'h-full p-0' : 'mx-auto max-w-[1700px] p-4 sm:px-7 sm:py-6'">
          <!-- На телефоне заголовок компактнее (меньше кегль и отступы), чтобы не
               «съедал» экран у небольших страниц; с sm — как в десктопе. -->
          <div v-if="title && !embed" class="mb-3 sm:mb-5">
            <h1 class="font-title text-lg font-extrabold text-text sm:text-2xl">{{ title }}</h1>
            <p v-if="subtitle" class="mt-0.5 text-xs text-text3 sm:mt-1 sm:text-sm">{{ subtitle }}</p>
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
      <div v-if="!embed && showDock && !vector.collapsed" class="hidden lg:block">
        <VectorDock />
      </div>
    </div>

    <!-- Панель скрыта → вкладка-возврат у правого края (десктоп). -->
    <button v-if="!embed && showDock && vector.collapsed" @click="vector.setCollapsed(false)"
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
