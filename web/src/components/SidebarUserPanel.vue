<script setup>
// SidebarUserPanel — «карточка себя» в САМОМ НИЗУ сайдбара (компоновка Discord).
//
// Зачем появилась (живой отзыв 3.5.6): раньше всё это жило в широкой акцентной шапке
// на всю ширину окна — 60 px по вертикали ради данных, на которые смотрят раз в день
// (кто я, какая роль, статус). Шапка ушла, её содержимое переехало сюда: левый нижний
// угол в прежней раскладке не использовался вовсе, а здесь блок стоит ровно там, где
// его ищут по привычке из Discord/Slack/Teams.
//
// Что показываем: аватар (prefs.avatar, тот же источник, что в профиле и мессенджере),
// ФИО, логин, роль и СВОЙ статус (§D7 — меняется одним кликом с любой страницы).
// Кнопки выхода здесь НЕТ намеренно: она переехала в самый низ «Настроек» (отзыв
// «случайно жму выход») — выход это редкое и необратимое действие, ему не место рядом
// с постоянно нажимаемым меню.
import { ref, computed, onMounted } from 'vue'
import { Moon, Sun, ChevronDown } from '@lucide/vue'
import { useAuthStore } from '@/stores/auth'
import { useThemeStore } from '@/stores/theme'
import { useProfileStore } from '@/stores/profile'
import { useMessengerStore } from '@/stores/messenger'
import { useLocaleStore } from '@/stores/locale'
import { STATUS_KINDS, myStatusLabel } from '@/config/status'
import { roleLabel as roleLabelOf } from '@/config/roles'
import { nameFontFamily } from '@/config/nameFonts'
import Avatar from '@/components/ui/Avatar.vue'
import SidebarUserOverlay from '@/components/SidebarUserOverlay.vue'

const auth = useAuthStore()
const theme = useThemeStore()
const profile = useProfileStore()
const messenger = useMessengerStore()
const locale = useLocaleStore()

const roleLabel = computed(() => roleLabelOf(auth.role))
const fullName = computed(() => (auth.user?.name || '').trim() || roleLabel.value)
const login = computed(() => (auth.user?.login || '').trim())

// Статус — тот же общий словарь (config/status.js), что у мессенджера: второй копии нет.
// Сам ВЫБОР статуса живёт в раскрывающейся карточке (SidebarUserOverlay) — здесь нужна
// только точка нужного цвета рядом с аватаром.
const cardOpen = ref(false)
const myStatus = computed(() =>
  STATUS_KINDS.find(k => k.kind === messenger.myStatus.kind) || STATUS_KINDS[0])
const statusText = computed(() =>
  myStatusLabel(messenger.myStatus.kind, messenger.myStatus.custom_text))

// Связь показываем, ТОЛЬКО когда её нет (то же решение, что было в шапке): «онлайн»
// рядом с выбираемым статусом читалось как один составной статус, и «Не беспокоить»
// уживалось с бодрым «Онлайн».
const online = ref(navigator.onLine)
function updateOnline() { online.value = navigator.onLine }

onMounted(async () => {
  window.addEventListener('online', updateOnline)
  window.addEventListener('offline', updateOnline)
  profile.load()
  await messenger.loadMyStatus()
  //Авто-«отошёл» по бездействию (как в Discord). Запускаем ЗДЕСЬ, а не на странице
  //мессенджера: панель видна на всех страницах, а отлучиться можно и из журнала —
  //привяжи слежение к одной вкладке, и статус завис бы на «в сети» у всех остальных.
  messenger.startIdleWatch()
})
</script>

<template>
  <div class="relative shrink-0 border-t border-border px-2 py-2">
    <!-- Карточка себя раскрывается ВВЕРХ: панель прижата к нижнему краю окна. -->
    <SidebarUserOverlay v-if="cardOpen" @close="cardOpen = false" />
    <!-- Клик мимо карточки закрывает её (глобальной директивы click-outside в проекте нет). -->
    <div v-if="cardOpen" class="fixed inset-0 z-30" @click="cardOpen = false" />

    <div class="relative z-10 flex items-center gap-2 rounded-md px-1.5 py-1.5 transition-colors hover:bg-bg">
      <!-- ⚠️ В самой панели — ТОЛЬКО самое частое: аватар, имя, логин и точка статуса.
           Роль и статус словами сюда не помещались (склеивались в «Студент · Не
           беспокоить» и обрезались) — они переехали в карточку по клику. -->
      <button type="button" @click="cardOpen = !cardOpen"
              class="flex min-w-0 flex-1 items-center gap-2 text-left"
              :aria-label="locale.t('userOverlay.open', 'Профиль и статус')"
              :title="locale.t('header.myStatus', { status: statusText })">
        <span class="relative shrink-0">
          <Avatar :src="profile.avatar" :name="fullName" :size="36" />
          <span class="absolute bottom-0 right-0 size-3 rounded-full border-2 border-card"
                :style="{ background: myStatus.color }" />
        </span>
        <span class="min-w-0 flex-1">
          <span class="block truncate text-[13px] font-semibold leading-tight text-text"
                :style="{ fontFamily: nameFontFamily(profile.font) }">{{ fullName }}</span>
          <span v-if="login" class="block truncate text-[11px] leading-tight text-text3">@{{ login }}</span>
        </span>
        <ChevronDown class="size-3.5 shrink-0 text-text3 transition-transform"
                     :class="cardOpen ? 'rotate-180' : ''" />
      </button>

      <button type="button" @click="theme.toggleMode()"
              class="grid size-8 shrink-0 place-items-center rounded-md text-text3 transition-colors hover:bg-bg2 hover:text-accent"
              :aria-label="theme.isDark ? locale.t('header.lightTheme', 'Светлая тема') : locale.t('header.darkTheme', 'Тёмная тема')">
        <Sun v-if="theme.isDark" class="size-4" />
        <Moon v-else class="size-4" />
      </button>
    </div>

    <!-- Нет связи — единственное состояние сети, о котором стоит сообщать. -->
    <p v-if="!online" class="mt-1 px-1.5 text-[11px] font-semibold text-red"
       :title="locale.t('header.offlineHint', 'Нет связи с сетью — данные подтянутся, когда связь вернётся.')">
      ● {{ locale.t('header.offline', 'Офлайн') }}
    </p>
  </div>
</template>
