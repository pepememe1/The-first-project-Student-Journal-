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
import Avatar from '@/components/ui/Avatar.vue'

const auth = useAuthStore()
const theme = useThemeStore()
const profile = useProfileStore()
const messenger = useMessengerStore()
const locale = useLocaleStore()

const roleLabel = computed(() => roleLabelOf(auth.role))
const fullName = computed(() => (auth.user?.name || '').trim() || roleLabel.value)
const login = computed(() => (auth.user?.login || '').trim())

// Статус — тот же общий словарь (config/status.js), что у мессенджера: второй копии нет.
const statusOpen = ref(false)
const myStatus = computed(() =>
  STATUS_KINDS.find(k => k.kind === messenger.myStatus.kind) || STATUS_KINDS[0])
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
  // Поле открываем с текущим текстом, а не пустым: пустое читается как «текста нет» и
  // человек стёр бы свой статус, просто нажав «Сохранить».
  statusDraft.value = messenger.myStatus.custom_text || ''
})
</script>

<template>
  <div class="relative shrink-0 border-t border-border px-2 py-2">
    <!-- Меню статуса раскрывается ВВЕРХ: панель прижата к нижнему краю окна. -->
    <div v-if="statusOpen"
         class="absolute bottom-full left-2 right-2 z-40 mb-1 rounded-lg border border-border2 bg-card p-1.5 shadow-card">
      <button v-for="k in STATUS_KINDS" :key="k.kind" type="button" @click="pickStatus(k.kind)"
              class="flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-sm text-text hover:bg-bg2"
              :class="{ 'bg-accent-glow': messenger.myStatus.kind === k.kind }">
        <span class="size-2.5 shrink-0 rounded-full" :style="{ background: k.color }" />
        {{ k.self }}
      </button>
      <div v-if="canSetStatusText" class="mt-1 border-t border-border pt-1.5">
        <input v-model="statusDraft" :placeholder="locale.t('header.statusTextPlaceholder', 'Текст статуса (видят другие)')"
               maxlength="80" @keydown.enter="saveStatusText"
               class="w-full rounded-md border border-border2 bg-card2 px-2 py-1 text-xs text-text outline-none focus:border-accent" />
        <button type="button" @click="saveStatusText"
                class="mt-1 w-full rounded-md bg-accent px-2 py-1 text-xs font-semibold text-white hover:bg-accent2">
          {{ locale.t('header.saveStatusText', 'Сохранить текст') }}
        </button>
      </div>
    </div>
    <!-- Клик мимо меню закрывает его (глобальной директивы click-outside в проекте нет). -->
    <div v-if="statusOpen" class="fixed inset-0 z-30" @click="statusOpen = false" />

    <div class="relative z-10 flex items-center gap-2 rounded-md px-1.5 py-1.5 transition-colors hover:bg-bg">
      <RouterLink :to="`/${auth.role}/profile`" class="shrink-0"
                  :title="locale.t('nav.profile', 'Профиль')">
        <Avatar :src="profile.avatar" :name="fullName" :size="36" />
      </RouterLink>

      <button type="button" @click="statusOpen = !statusOpen"
              class="min-w-0 flex-1 text-left"
              :aria-label="locale.t('header.myStatusAria', 'Мой статус')"
              :title="locale.t('header.myStatus', { status: statusText })">
        <p class="truncate text-[13px] font-semibold leading-tight text-text">{{ fullName }}</p>
        <p v-if="login" class="truncate text-[11px] leading-tight text-text3">@{{ login }}</p>
        <p class="mt-0.5 flex items-center gap-1.5 text-[11px] leading-tight text-text2">
          <span class="size-2 shrink-0 rounded-full" :style="{ background: myStatus.color }" />
          <span class="truncate">{{ roleLabel }} · {{ statusText }}</span>
          <ChevronDown class="size-3 shrink-0" />
        </p>
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
