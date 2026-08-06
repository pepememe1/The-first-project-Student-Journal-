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
import { useLocaleStore } from '@/stores/locale'

const locale = useLocaleStore()
const theme = useThemeStore()
const vector = useVectorStore()
const tts = useTtsStore()
const messenger = useMessengerStore()
const route = useRoute()
const sidebarOpen = ref(false)

// Embed-режим: тот же SPA, встроенный в ДЕСКТОП (QWebEngineView, см. ui/messenger_web.py
// и ui/vue_shell.py). Прячем собственную навигацию/шапку/док — их роль на десктопе
// играет нативная оболочка, иначе получилась бы «навигация внутри навигации». Десктоп
// ставит флаг gb.embed ДО загрузки страницы (плюс поддерживаем ?embed=1 в URL). Значение
// фиксируется на загрузке.
// ⚠️ ТРИ режима, а не два. Когда десктоп показывает ВЕСЬ кабинет одним веб-видом
// (ui/vue_dashboard.py::VueDashboard), своя навигация SPA нужна (иначе человек застрянет
// на одной странице), а вот шапка — нет: её роль играет заголовок окна программы, и две
// шапки подряд выглядят как ошибка.
//   '1'   — встроена одна страница (старый ui/messenger_web.py): прячем и шапку, и меню;
//   'nav' — встроен весь кабинет (ui/vue_dashboard.py): прячем ТОЛЬКО шапку, меню оставляем;
//   иначе — обычный сайт/телефон, всё своё.
const embedMode = (() => {
  try {
    const q = new URLSearchParams(window.location.search)
    const v = q.get('embed') || localStorage.getItem('gb.embed') || ''
    return v === '1' || v === 'nav' ? v : ''
  } catch { return '' }
})()
const embed = embedMode === '1'                 //прятать навигацию (одна страница)
const chromeless = embedMode !== ''             //прятать шапку (любой режим внутри окна)

// Подзаголовок страницы — переводим через необязательный meta.i18nSubtitle (см.
// router/index.js); маршрут без него показывает meta.subtitle как есть.
// ⚠️ meta.title здесь БОЛЬШЕ НЕ ЧИТАЕТСЯ: имя раздела и так подсвечено в сайдбаре, а на
// телефоне его показывает мобильная полоса (HeaderBar.vue) — она же и берёт meta.title.
const subtitle = computed(() => route.meta?.i18nSubtitle ? locale.t(route.meta.i18nSubtitle, route.meta.subtitle) : (route.meta?.subtitle || ''))
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
  // ⚠️ ВНУТРИ ДЕСКТОПА тему с сервера НЕ подтягиваем. Оболочка окна уже покрашена в
  // тему, выбранную в самой программе, и роуминг перекрашивал бы страницу в другую —
  // в одном окне получались два разных оформления. Снаружи (сайт, телефон) роуминг
  // нужен и работает как раньше: там окна нет и спорить не с кем.
  if (!chromeless) theme.loadFromPrefs()
  messenger.loadChats()
  _unreadTimer = setInterval(() => messenger.loadChats(), 20000)
})
onBeforeUnmount(() => {
  if (_mq) _mq.removeEventListener('change', _onMq)
  if (_unreadTimer) clearInterval(_unreadTimer)
})
</script>

<template>
  <!-- Корень — ГОРИЗОНТАЛЬНЫЙ: сайдбар и контент рядом, полосы во всю ширину сверху
       больше нет (см. HeaderBar.vue — там осталась только мобильная версия). -->
  <div class="flex h-full overflow-hidden">
    <!-- Десктоп: постоянный сайдбар -->
    <div v-if="!embed" class="hidden lg:block">
      <Sidebar />
    </div>

    <!-- Мобайл: выезжающий сайдбар -->
    <transition name="fade">
      <div v-if="sidebarOpen" class="fixed inset-0 z-40 lg:hidden">
        <div class="absolute inset-0" style="background: var(--gb-overlay)" @click="sidebarOpen = false" />
        <div class="absolute inset-y-0 left-0 z-50 shadow-xl">
          <Sidebar :open="sidebarOpen" @navigate="sidebarOpen = false" />
        </div>
      </div>
    </transition>

    <div class="flex min-h-0 min-w-0 flex-1 flex-col">
      <!-- Компактная полоса — ТОЛЬКО телефон (сама прячется с lg): там сайдбар за
           бургером, и без неё не было бы ни меню, ни понимания, какой раздел открыт. -->
      <HeaderBar v-if="!chromeless" @toggle-sidebar="sidebarOpen = !sidebarOpen" />

      <!-- Контент: мягкий фон + сетка (как AnimatedBackground в десктопе) -->
      <main class="app-canvas min-h-0 flex-1 overflow-y-auto" style="padding-bottom: env(safe-area-inset-bottom)">
        <!-- Отступы ужаты (3.5.6): было p-4 / sm:px-7 sm:py-6 — «жирная рамка» вокруг
             активного окна съедала полосу по всему периметру, ничего в ней не показывая. -->
        <!-- Правый отступ добавляем ТОЛЬКО когда у края висит вкладка-возврат Вектора:
             она fixed и иначе ложится на последнюю колонку страницы (на расписании
             накрывала субботу). Панель раскрыта или её нет — отступ не нужен. -->
        <div :class="[embed ? 'h-full p-0' : 'mx-auto max-w-[1700px] p-3 sm:px-4 sm:py-3.5',
                      (!embed && showDock && vector.collapsed) ? 'lg:pr-10' : '']">
          <!-- ⚠️ КРУПНОГО ЗАГОЛОВКА СТРАНИЦЫ ЗДЕСЬ БОЛЬШЕ НЕТ. Он дублировал подсвеченный
               пункт сайдбара — то же слово, только вчетверо крупнее и с отступами
               (живой отзыв: «зачем-то огромная надпись, какое окно выбрано»). Остался
               ТОЛЬКО подзаголовок, где он есть: это пояснение к странице, а не её имя,
               и его нигде больше не видно. На телефоне имя раздела показывает
               мобильная полоса выше — там сайдбара на экране нет. -->
          <p v-if="subtitle && !embed" class="mb-2.5 text-xs text-text3">{{ subtitle }}</p>
          <!-- ⚠️ Живой отзыв (повторился ПОСЛЕ фикса :duration ниже — см. его же историю):
               «вкладка иногда не прогружается, помогает только F5», воспроизведено на
               десктопе (WebView2), где просто нажать F5 не всегда удобно. `:duration="150"`
               (был добавлен раньше — переводит Vue на явный JS-таймер вместо ожидания
               браузерного события `transitionend`, которое часть браузеров не шлёт для
               неактивных/фоновых вкладок) СТРАХУЕТ переход `mode="out-in"`, но не был
               подтверждён живым тестом (dev-browser вне работы) и, судя по повтору жалобы,
               не единственная причина. Без Suspense в проекте async-компонентов с зависшим
               setup нет (проверено), а без ГЛОБАЛЬНОГО обработчика ошибок (см. main.js —
               добавлен тем же заходом) необработанное исключение в setup/render/watcher
               ЛЮБОЙ страницы просто уходило в тишину: сайдбар — отдельное от RouterView
               поддерево дерева компонентов и продолжает жить нормально, а место страницы
               остаётся пустым — ровно то, что видно на скриншоте (сайдбар цел, «Профиль»
               подсвечен, контента нет). Два независимых усиления одним заходом:
               1) `app.config.errorHandler` — впервые видно, ЧТО именно упало (было
                  невозможно диагностировать дальше без этого);
               2) `:key="matched.fullPath"` — форсирует ПОЛНЫЙ ремонт компонента на каждую
                  отдельную навигацию, а не переиспользование существующего инстанса;
                  застрявший/сломанный инстанс не переживёт следующий переход на ту же
                  страницу. Если проблема останется — смотреть сюда, теперь уже с
                  сообщением из errorHandler в руках, а не вслепую. -->
          <RouterView v-slot="{ Component, route: matched }">
            <transition name="fade" mode="out-in" :duration="150">
              <component :is="Component" :key="matched.fullPath" />
            </transition>
          </RouterView>
        </div>
      </main>
    </div>

    <!-- Боковой Вектор — ОВЕРЛЕЙ поверх страницы, а не колонка в потоке (живой отзыв
         3.5.6: «ИИ-шторка должна налазить на текущую страницу, а не сдвигать её»).
         Раньше это был обычный <aside> в той же flex-строке: открытие шторки сжимало
         контент на 384 px, таблицы журнала перевёрстывались, и человек терял место, на
         которое смотрел. Теперь она fixed поверх, с тенью и выездом справа. -->
    <transition name="dock">
      <div v-if="!embed && dockShown" class="fixed inset-y-0 right-0 z-30 hidden shadow-2xl lg:block">
        <VectorDock />
      </div>
    </transition>

    <!-- Панель скрыта → вкладка-возврат у правого края (десктоп).
         ⚠️ Раньше рядом с иконкой стояло слово «Вектор», набранное ВЕРТИКАЛЬНО
         (writing-mode). Вкладка от этого была вдвое шире и заметно ложилась на правую
         колонку страницы — на расписании накрывала субботу. Осталась одна иконка с
         подсказкой: назначение читается по ней, а место она занимает вдвое меньше. -->
    <button v-if="!embed && showDock && vector.collapsed" @click="vector.setCollapsed(false)"
            :aria-label="locale.t('vectorDock.showPanel', 'Показать панель Вектора')"
            :title="locale.t('vectorDock.showPanelShort', 'Показать Вектора')"
            class="fixed right-0 top-1/2 z-30 hidden -translate-y-1/2 place-items-center rounded-l-lg border border-r-0 border-border bg-card px-1.5 py-3 text-accent shadow-card transition-colors hover:bg-accent-glow lg:grid">
      <PanelRightOpen class="size-5" />
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
/* Шторка Вектора выезжает справа поверх страницы (не раздвигает её). */
.dock-enter-active,
.dock-leave-active { transition: transform 0.18s ease, opacity 0.18s ease; }
.dock-enter-from,
.dock-leave-to { transform: translateX(16px); opacity: 0; }
</style>
