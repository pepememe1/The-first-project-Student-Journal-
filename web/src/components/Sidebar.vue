<script setup>
import { useLocaleStore } from '@/stores/locale'
// Sidebar — боковая навигация. 250px, фон bg2, секции-заголовки (uppercase) + пункты с
// иконками; активный подсвечен акцентом.
//
// С 3.5.6 сайдбар несёт ТРИ этажа, а не один список (живой отзыв: «сайдбар пустой, а
// хэдер жирный и бесполезный»):
//   1) шапка — фирменный знак и название (переехали из акцентной полосы во всю ширину);
//   2) сам список разделов — растягивается, прокручивается только он;
//   3) карточка себя (SidebarUserPanel) — аватар/ФИО/логин/роль/статус, компоновка Discord.
// Из-за этого корневой aside стал flex-колонкой с overflow-y ТОЛЬКО на середине: иначе
// карточка себя уезжала бы вверх вместе с прокруткой длинного админского меню.
import { computed, ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useMessengerStore } from '@/stores/messenger'
import { NAV } from '@/config/nav'
import { curatorApi, adminApi } from '@/api/endpoints'
import BrandLogo from '@/components/BrandLogo.vue'
import SidebarUserPanel from '@/components/SidebarUserPanel.vue'
import ConnectionBadge from '@/components/ui/ConnectionBadge.vue'
import SyncIssuesBadge from '@/components/ui/SyncIssuesBadge.vue'
import AccessibilityMenu from '@/components/AccessibilityMenu.vue'
import ReportProblemButton from '@/components/ReportProblemButton.vue'

defineProps({ open: { type: Boolean, default: false } })
const emit = defineEmits(['navigate'])

const auth = useAuthStore()
const loc = useLocaleStore()
const messenger = useMessengerStore()
const route = useRoute()
// Значение бейджа пункта: непрочитанные сообщения берём из стора мессенджера (живой
// счётчик), остальные — из локальной карты badges (напр., накладки расписания).
function badgeCount(key) {
  if (key === 'messagesUnread') return messenger.totalUnread
  return badges.value[key] || 0
}
// Пункт «Курирование» (curatorOnly) виден только преподавателю-куратору.
const isCurator = ref(false)
// Счётчики у пунктов меню (nav.badge → число). Пока нужен один — накладки расписания.
const badges = ref({})
onMounted(async () => {
  if (auth.role === 'teacher') {
    try { isCurator.value = ((await curatorApi.groups()).data.groups || []).length > 0 } catch { /* */ }
  }
  if (auth.role === 'admin') {
    // Ошибку глушим намеренно: недоступная проверка расписания не повод ломать меню.
    try { badges.value.scheduleIssues = (await adminApi.scheduleConflicts()).data.count || 0 } catch { /* */ }
  }
})
const items = computed(() => (NAV[auth.role] || []).filter((it) => !it.curatorOnly || isCurator.value))

function isActive(to) {
  if (to.split('/').length <= 2) return route.path === to
  return route.path === to || route.path.startsWith(to + '/')
}
</script>

<template>
  <!-- ⚠️ Безопасные зоны (3.7, живой отзыв Ярослава с APK: «при заходе в бургер-меню
       надпись GradeBookAI залазит под шторку уведомлений»). Выезжающий сайдбар —
       `fixed inset-y-0` (AppShell), то есть начинается от координаты 0, а в приложении
       это ПОД системной шторкой: бренд оказывался наполовину перекрыт. Мобильная полоса
       свой отступ уже учитывает (`HeaderBar.vue`), а сайдбар — нет, потому что он не
       часть той же колонки. Заодно нижняя вставка спасает карточку профиля внизу от
       полосы жестов. На сайте и в десктопе обе вставки нулевые — поведение прежнее. -->
  <aside class="flex h-full w-[250px] shrink-0 flex-col border-r border-border bg-bg2"
         style="padding-top: var(--gb-safe-top); padding-bottom: var(--gb-safe-bottom)">
    <!-- 1. Шапка: фирменный знак и название. Раньше стояли в акцентной полосе во всю
         ширину окна — здесь занимают ту же строку, но не отнимают высоту у контента. -->
    <div class="flex shrink-0 items-center gap-2.5 px-3 py-3">
      <BrandLogo :size="32" class="shrink-0" />
      <div class="min-w-0 flex-1 leading-tight">
        <p class="truncate font-title text-[15px] font-extrabold text-text">GradeBookAI</p>
        <p class="truncate text-[10px] font-semibold text-text3">{{ loc.t('app.college') }}</p>
      </div>
      <!-- Версия для слабовидящих — всегда на виду в шапке (как иконка-очки на порталах). -->
      <AccessibilityMenu placement="down" class="shrink-0" />
    </div>
    <div class="mx-3 h-px shrink-0 bg-border" />

    <!-- 2. Разделы — единственная прокручиваемая часть. -->
    <nav class="min-h-0 flex-1 overflow-y-auto px-2.5 py-2">
      <template v-for="(item, i) in items" :key="i">
        <p v-if="item.section" class="px-2.5 pb-1 pt-3.5 text-[10px] font-medium uppercase tracking-wide text-text2 first:pt-1">
          {{ item.i18n ? loc.t(item.i18n, item.section) : item.section }}
        </p>
        <RouterLink
          v-else
          :to="item.to"
          class="mb-0.5 flex items-center gap-2.5 rounded-sm px-3.5 py-2.5 text-sm transition-colors"
          :class="
            isActive(item.to)
              ? 'bg-accent-glow font-semibold text-accent'
              : 'font-medium text-text3 hover:bg-accent-glow hover:text-accent'
          "
          @click="emit('navigate')"
        >
          <component :is="item.icon" class="size-[18px] shrink-0" />
          <span class="truncate">{{ item.i18n ? loc.t(item.i18n, item.label) : item.label }}</span>
          <!-- Счётчик у пункта. Непрочитанные сообщения — акцентом (информация), накладки
               расписания — красным (требует вмешательства). Ноль не показываем. -->
          <span v-if="item.badge && badgeCount(item.badge)"
                class="ml-auto grid min-w-5 shrink-0 place-items-center rounded-full px-1.5 text-tiny font-bold text-white"
                :class="item.badge === 'messagesUnread' ? 'bg-accent' : 'bg-red'">
            {{ badgeCount(item.badge) }}
          </span>
        </RouterLink>
      </template>
    </nav>

    <!-- Режим связи — НАД карточкой себя: это состояние всего приложения, а не свойство
         аккаунта. В приложении виден всегда, на сайте появляется только при потере сети
         (см. сам компонент о том, почему постоянное «Онлайн» в браузере — шум). -->
    <div class="shrink-0 px-3 pb-1">
      <ConnectionBadge />
    </div>

    <!-- Рядом, но ОТДЕЛЬНО от значка связи: тот про «есть ли сеть», этот про «дошли ли
         правки». Состояния не совпадают — связь бывает прекрасной, а оценка всё равно
         остаётся только на этом ПК. Появляется, лишь когда есть о чём сказать. -->
    <div class="shrink-0 px-3 pb-1">
      <SyncIssuesBadge />
    </div>

    <!-- «Сообщить о проблеме» — встроенный канал обратной связи (ClassDojo, §9 №3).
         Над карточкой себя, спокойным стилем: действие редкое, но должно быть под рукой
         из любого раздела. Админу компонент себя не рисует (он и есть модерация). -->
    <div class="shrink-0 px-2.5 pb-1">
      <ReportProblemButton />
    </div>

    <!-- 3. Карточка себя — прижата к нижнему краю (Discord). Занимает ровно тот угол,
         который в прежней раскладке пустовал. -->
    <SidebarUserPanel />
  </aside>
</template>
