<script setup>
// BottomNav — нижняя панель разделов на телефоне (23.10.2026, §4.51).
//
// Раньше на телефоне все разделы жили за кнопкой «Меню» в левом верхнем углу: любой
// переход — два касания, и оба в зоне, куда большой палец на 6,5-дюймовом экране не
// дотягивается (живой прогон на S24 23.10.2026). Панель устроена как у Material 3 и
// iOS: три-четыре частых раздела роли (`TABS` в config/nav.js) и «Меню» последним;
// подпись под значком видна всегда, выбранный раздел подсвечен «пилюлей» за значком.
// Повторное касание открытой вкладки возвращает к её началу, как в больших
// приложениях: со страницы раздела — на сам раздел, с самого раздела — наверх списка.
//
// Высота панели меняется вместе с режимом слабовидящих (всё в rem), поэтому она сама
// сообщает её оболочке через `--gb-bottom-chrome`: из этой переменной считают высоту
// полноэкранные страницы и подъём всплывающих уведомлений (style.css).
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Menu } from '@lucide/vue'
import { useAuthStore } from '@/stores/auth'
import { useLocaleStore } from '@/stores/locale'
import { useMessengerStore } from '@/stores/messenger'
import { useNavBadgesStore } from '@/stores/navBadges'
import { NAV, TABS, TAB_LABELS, isNavActive, tabsFor } from '@/config/nav'

const emit = defineEmits(['menu'])
const auth = useAuthStore()
const loc = useLocaleStore()
const messenger = useMessengerStore()
const navBadges = useNavBadgesStore()
const route = useRoute()
const router = useRouter()

const tabs = computed(() => tabsFor(auth.role))

function label(item) {
  const short = TAB_LABELS[item.key]
  if (short) return loc.t(short[0], short[1])
  return item.i18n ? loc.t(item.i18n, item.label) : item.label
}

function badgeCount(key) {
  if (key === 'messagesUnread') return messenger.totalUnread
  if (key === 'notifyUnread') return navBadges.notifyUnread
  return 0
}

// Непрочитанное в разделах, которых на панели нет, видно на «Меню» — как «Ещё» в iOS:
// иначе о новом уведомлении узнавали бы, только открыв меню.
const menuBadge = computed(() => {
  const onBar = TABS[auth.role] || []
  return (NAV[auth.role] || [])
    .filter((it) => it.badge && !onBar.includes(it.key))
    .reduce((n, it) => n + badgeCount(it.badge), 0)
})

function shown(n) { return n > 99 ? '99+' : String(n) }

// Нажатую вкладку подсвечиваем сразу, не дожидаясь загрузки страницы: иначе палец
// уже убран, а панель выглядит так, будто касание не засчиталось (тот же урок, что у
// шторки меню, Sidebar.vue::highlighted).
const pressed = ref('')
let pressedTimer = null
watch(() => route.path, () => { pressed.value = '' })

function active(item) {
  return pressed.value ? pressed.value === item.to : isNavActive(item.to, route.path)
}

function onTap(item, e) {
  if (!isNavActive(item.to, route.path)) {
    pressed.value = item.to
    clearTimeout(pressedTimer)
    pressedTimer = setTimeout(() => { pressed.value = '' }, 2000)
    return
  }
  e.preventDefault()
  if (route.path !== item.to) router.push(item.to)
  else document.getElementById('gb-main')?.scrollTo({ top: 0, behavior: 'smooth' })
}

// Высоту отдаём оболочке. Пока панели нет (ПК, открытая беседа, клавиатура), переменной
// нет тоже, и действует значение по умолчанию из style.css — нижняя безопасная зона.
const bar = ref(null)
let observer = null
function publishHeight() {
  const h = bar.value?.offsetHeight || 0
  if (h) document.documentElement.style.setProperty('--gb-bottom-chrome', `${h}px`)
}
onMounted(() => {
  publishHeight()
  if (typeof ResizeObserver === 'function' && bar.value) {
    observer = new ResizeObserver(publishHeight)
    observer.observe(bar.value)
  }
})
onBeforeUnmount(() => {
  observer?.disconnect()
  clearTimeout(pressedTimer)
  document.documentElement.style.removeProperty('--gb-bottom-chrome')
})
</script>

<template>
  <nav ref="bar" :aria-label="loc.t('nav.tabBar', 'Разделы')"
       class="flex shrink-0 items-stretch border-t border-border bg-bg2 lg:hidden"
       style="padding-bottom: var(--gb-safe-bottom)">
    <RouterLink v-for="item in tabs" :key="item.key" :to="item.to"
                class="gb-tab flex min-h-16 min-w-0 flex-1 flex-col items-center justify-center gap-1 px-0.5 py-2"
                :aria-current="active(item) ? 'page' : null"
                @click="onTap(item, $event)">
      <span class="relative grid h-8 w-14 max-w-full place-items-center rounded-full transition-colors"
            :class="active(item) ? 'bg-accent-glow text-accent' : 'text-text2'">
        <component :is="item.icon" class="size-6" aria-hidden="true" />
        <span v-if="item.badge && badgeCount(item.badge)"
              class="absolute -top-1 right-0 grid h-[1.125rem] min-w-[1.125rem] place-items-center rounded-full px-1 text-tiny font-bold text-white ring-2 ring-bg2"
              :class="item.badge === 'messagesUnread' ? 'bg-accent' : 'bg-red'">
          {{ shown(badgeCount(item.badge)) }}
        </span>
      </span>
      <span class="gb-tab-label max-w-full overflow-hidden text-center leading-tight text-ellipsis whitespace-nowrap"
            :class="active(item) ? 'font-bold text-accent' : 'font-medium text-text2'">{{ label(item) }}</span>
    </RouterLink>
    <button type="button"
            class="gb-tab flex min-h-16 min-w-0 flex-1 flex-col items-center justify-center gap-1 px-0.5 py-2"
            :aria-label="menuBadge ? `${loc.t('header.menu', 'Меню')}: ${shown(menuBadge)}` : loc.t('header.menu', 'Меню')"
            @click="emit('menu')">
      <span class="relative grid h-8 w-14 max-w-full place-items-center rounded-full text-text2">
        <Menu class="size-6" aria-hidden="true" />
        <span v-if="menuBadge"
              class="absolute -top-1 right-0 grid h-[1.125rem] min-w-[1.125rem] place-items-center rounded-full bg-red px-1 text-tiny font-bold text-white ring-2 ring-bg2">
          {{ shown(menuBadge) }}
        </span>
      </span>
      <span class="gb-tab-label max-w-full overflow-hidden text-center font-medium leading-tight text-ellipsis whitespace-nowrap text-text2">{{ loc.t('header.menu', 'Меню') }}</span>
    </button>
  </nav>
</template>

<style scoped>
/* Подпись растёт с режимом слабовидящих, но не шире своей пятой части экрана: на
   «Максимуме» «Расписание» рвалось посреди слова на две строки (живой прогон 23.10.2026).
   Так же поступает iOS — подписи вкладок с крупным шрифтом растут до предела панели. */
.gb-tab-label { font-size: min(0.75rem, 3.3vw); }
/* Отклик касания без синей вспышки Android: подсветка «пилюли» и есть ответ. */
.gb-tab { -webkit-tap-highlight-color: transparent; }
.gb-tab:active > span:first-child { transform: scale(0.94); }
@media (prefers-reduced-motion: no-preference) {
  .gb-tab > span:first-child { transition: transform 0.12s ease, background-color 0.15s ease; }
}
</style>
