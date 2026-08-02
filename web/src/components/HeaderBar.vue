<script setup>
// HeaderBar — верхняя полоса (порт ui_components.HeaderBar): СПЛОШНОЙ акцентный фон
// (в десктопе от горизонтального градиента отказались — он давал видимую полосу-
// «обрыв»), белый текст, лого GB + «GradeBookAI» + колледж, индикатор онлайн, бейдж
// роли, имя пользователя, выход. На телефоне — кнопка-гамбургер.
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { Menu, Moon, Sun, LogOut, ChevronDown } from '@lucide/vue'
import { useAuthStore } from '@/stores/auth'
import { useThemeStore } from '@/stores/theme'
import { useMessengerStore } from '@/stores/messenger'
import { useLocaleStore } from '@/stores/locale'
import BrandLogo from '@/components/BrandLogo.vue'
import { STATUS_KINDS, myStatusLabel } from '@/config/status'
import { roleLabel as roleLabelOf } from '@/config/roles'
import FarewellOverlay from '@/components/FarewellOverlay.vue'

const emit = defineEmits(['toggle-sidebar'])
const router = useRouter()
const auth = useAuthStore()
const theme = useThemeStore()
const messenger = useMessengerStore()
const locale = useLocaleStore()

const roleLabel = computed(() => roleLabelOf(auth.role))
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

// §D7: СВОЙ статус — в правом верхнем углу, а не только в шапке списка чатов.
// Раньше переключатель жил внутри вкладки «Сообщения», и со стороны выглядело, что
// смена статуса ни на что не влияет: сам её автор нигде свой статус больше не видел.
// Здесь он на всех страницах и меняется одним кликом.
const statusOpen = ref(false)
const myStatus = computed(() =>
  STATUS_KINDS.find(k => k.kind === messenger.myStatus.kind) || STATUS_KINDS[0])
// Свой текст преподавателя («принимаю до 15:00») информативнее ярлыка — показываем его.
const statusText = computed(() =>
  myStatusLabel(messenger.myStatus.kind, messenger.myStatus.custom_text))
async function pickStatus(kind) {
  statusOpen.value = false
  // Вид статуса меняем, УЖЕ ЗАДАННЫЙ ТЕКСТ сохраняем: «не беспокоить» не должно молча
  // стирать пояснение «принимаю до 15:00».
  await messenger.setMyStatus(kind, messenger.myStatus.custom_text || '')
}

// Свой текст статуса задаёт только преподаватель — то же правило, что в мессенджере
// (MyStatusPicker.vue): у студента такого поля нет ни там, ни здесь.
const canSetStatusText = computed(() => auth.role === 'teacher')
const statusDraft = ref('')
async function saveStatusText() {
  statusOpen.value = false
  await messenger.setMyStatus(messenger.myStatus.kind, statusDraft.value)
}

onMounted(async () => {
  window.addEventListener('online', updateOnline)
  window.addEventListener('offline', updateOnline)
  await messenger.loadMyStatus()
  // Поле открываем с текущим текстом, а не пустым: пустое читается как «текста нет» и
  // человек стёр бы свой статус, просто нажав «Сохранить».
  statusDraft.value = messenger.myStatus.custom_text || ''
})
onBeforeUnmount(() => {
  window.removeEventListener('online', updateOnline)
  window.removeEventListener('offline', updateOnline)
})

// Прощание: Вектор машет ~1.2 с, потом уходим на форму входа. Выход при этом ВЫПОЛНЯЕТСЯ
// сразу — анимация не задерживает ни сам logout, ни очистку токенов: если что-то пойдёт
// не так, человек всё равно окажется разлогинен. Задержка — только на переход экрана.
const FAREWELL_MS = 1200
const farewell = ref(false)
async function onLogout() {
  farewell.value = true
  try { await auth.logout() } finally {
    setTimeout(() => router.push('/login'), FAREWELL_MS)
  }
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
      :aria-label="locale.t('header.menu', 'Меню')" @click="emit('toggle-sidebar')"
    >
      <Menu class="size-5" />
    </button>

    <!-- Утверждённый фирменный знак: вращающийся гексагон GB (цвет — из темы, белая
         обводка/кольца видны на акцентном фоне шапки). -->
    <BrandLogo :size="40" class="shrink-0" />
    <div class="min-w-0 leading-tight">
      <!-- Фирменное написание «GradeBookAI» (как на экране входа), НЕ капсом «GRADEBOOK».
           Шрифт — основной (DM Sans), как в десктопной шапке. -->
      <p class="text-base font-extrabold tracking-[0.2px]">GradeBookAI</p>
      <!-- Полное название колледжа — только с sm: на телефоне места нет. -->
      <p class="hidden truncate text-[10px] font-semibold text-white/80 sm:block">{{ locale.t('app.college') }}</p>
    </div>

    <div class="min-w-2 flex-1" />

    <!-- ⚠️ Постоянного бейджа «Онлайн» здесь БОЛЬШЕ НЕТ. Рядом с выбираемым статусом
         стояли два кружка подряд, и человек читал их как один составной статус — при
         «Не беспокоить» шапка всё равно говорила «Онлайн». Наличие связи вообще не
         статус, а состояние сети, и сообщать о нём стоит лишь когда оно ПЛОХОЕ. -->
    <span v-if="!online"
          class="hidden items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold text-white/90 sm:inline-flex"
          style="background: rgba(255,255,255,0.12);"
          :title="locale.t('header.offlineHint', 'Нет связи с сетью — данные подтянутся, когда связь вернётся.')">
      <span class="text-[14px] leading-none" style="color:#ff8a8a">●</span>
      {{ locale.t('header.offline', 'Офлайн') }}
    </span>

    <!-- §D7: свой статус — виден и меняется с любой страницы. Кружок в цвет статуса,
         подпись прячем на узких экранах (там за неё говорит цвет). -->
    <div class="relative shrink-0">
      <button type="button" @click="statusOpen = !statusOpen"
              :title="locale.t('header.myStatus', { status: statusText })"
              :aria-label="locale.t('header.myStatusAria', 'Мой статус')"
              class="flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold text-white/90 hover:bg-white/15"
              style="background: rgba(255,255,255,0.12);">
        <span class="size-2.5 shrink-0 rounded-full" :style="{ background: myStatus.color }" />
        <span class="hidden max-w-[160px] truncate md:inline">{{ statusText }}</span>
        <ChevronDown class="size-3.5 shrink-0" />
      </button>
      <div v-if="statusOpen"
           class="absolute right-0 top-full z-30 mt-1 w-52 rounded-lg border border-border2 bg-card p-1.5 shadow-card">
        <button v-for="k in STATUS_KINDS" :key="k.kind" type="button" @click="pickStatus(k.kind)"
                class="flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-sm text-text hover:bg-bg2"
                :class="{ 'bg-accent-glow': messenger.myStatus.kind === k.kind }">
          <span class="size-2.5 shrink-0 rounded-full" :style="{ background: k.color }" />
          {{ k.self }}
        </button>

        <!-- Свой текст статуса — только преподавателю (как в мессенджере, тот же лимит).
             Раньше поле было ТОЛЬКО внутри вкладки «Сообщения»: статус висел в шапке на
             всех страницах, а поменять его текст можно было лишь уйдя в мессенджер. -->
        <div v-if="canSetStatusText" class="mt-1 border-t border-border pt-1.5">
          <input v-model="statusDraft" :placeholder="locale.t('header.statusTextPlaceholder', 'Текст статуса (видят другие)')" maxlength="80"
                 @keydown.enter="saveStatusText"
                 class="w-full rounded-md border border-border2 bg-card2 px-2 py-1 text-xs text-text outline-none focus:border-accent" />
          <button type="button" @click="saveStatusText"
                  class="mt-1 w-full rounded-md bg-accent px-2 py-1 text-xs font-semibold text-white hover:bg-accent2">
            {{ locale.t('header.saveStatusText', 'Сохранить текст') }}
          </button>
        </div>
      </div>
      <!-- Клик мимо меню закрывает его (глобальной директивы click-outside в проекте нет). -->
      <div v-if="statusOpen" class="fixed inset-0 z-20" @click="statusOpen = false" />
    </div>

    <!-- Переключатель темы (тёмная/светлая) -->
    <button
      class="grid size-9 shrink-0 place-items-center rounded-md text-white/90 hover:bg-white/15"
      :aria-label="theme.isDark ? locale.t('header.lightTheme', 'Светлая тема') : locale.t('header.darkTheme', 'Тёмная тема')" @click="theme.toggleMode()"
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
      <span class="hidden sm:inline">{{ locale.t('nav.logout') }}</span>
    </button>
  </header>
  <FarewellOverlay v-if="farewell" :name="showName" />
</template>
