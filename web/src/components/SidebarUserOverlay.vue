<script setup>
// SidebarUserOverlay — карточка «себя», раскрывающаяся НАД панелью в нижнем углу
// сайдбара (компоновка Discord).
//
// Зачем (живой отзыв 3.6): в самой панели роль и статус физически не помещались в одну
// строку — они склеивались в «Студент · Не беспокоить» и обрезались многоточием на любом
// разумном сайдбаре. Уменьшать шрифт бессмысленно (данные и так мелкие), а расширять
// сайдбар — отдавать место навигации. Поэтому в панели остаётся только самое частое
// (аватар, имя, точка статуса), а всё остальное — здесь, по клику.
//
// Что показываем: полосу цвета профиля, аватар (с карандашом по наведению — уводит в
// «Профиль»), ФИО, @логин, роль, «О себе» и статус с переключателем.
//
// ⚠️ Открывается ВВЕРХ (`bottom-full`): панель прижата к нижнему краю окна, и обычное
// раскрытие вниз ушло бы за экран.
import { ref, computed, watch } from 'vue'
import { Pencil, ChevronRight } from '@lucide/vue'
import { RouterLink } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useProfileStore } from '@/stores/profile'
import { useMessengerStore } from '@/stores/messenger'
import { useLocaleStore } from '@/stores/locale'
import { STATUS_KINDS, myStatusLabel } from '@/config/status'
import { roleLabel as roleLabelOf } from '@/config/roles'
import { profilePlate } from '@/theme/palette'
import { nameDecor } from '@/config/nameEffects'
import Avatar from '@/components/ui/Avatar.vue'

const emit = defineEmits(['close'])

const auth = useAuthStore()
const profile = useProfileStore()
const messenger = useMessengerStore()
const locale = useLocaleStore()

const roleLabel = computed(() => roleLabelOf(auth.role))
const fullName = computed(() => (auth.user?.name || '').trim() || roleLabel.value)
const login = computed(() => (auth.user?.login || '').trim())
// Своё имя рисуется тем же стилем, что видят другие: шрифт, эффект и цвет разом.
const myNameDecor = computed(() => nameDecor({
  name_font: profile.font, name_effect: profile.effect,
  name_color: profile.nameColor, profile_color: profile.color,
}))
// Плашка цвета профиля — тот же резолвер, что в мессенджере: своей копии сопоставления
// «id пресета → цвет» не заводим (иначе в чате и в профиле человек будет разного цвета).
const plate = computed(() => profilePlate(profile.color))

const statusOpen = ref(false)
const myStatus = computed(() =>
  STATUS_KINDS.find((k) => k.kind === messenger.myStatus.kind) || STATUS_KINDS[0])
const statusText = computed(() =>
  myStatusLabel(messenger.myStatus.kind, messenger.myStatus.custom_text))

// Свой текст статуса задаёт только преподаватель — то же правило, что в мессенджере.
const canSetStatusText = computed(() => auth.role === 'teacher')
const statusDraft = ref(messenger.myStatus.custom_text || '')
watch(() => messenger.myStatus.custom_text, (v) => { statusDraft.value = v || '' })

async function pickStatus(kind) {
  statusOpen.value = false
  // Вид статуса меняем, УЖЕ ЗАДАННЫЙ ТЕКСТ сохраняем: «не беспокоить» не должно молча
  // стирать пояснение «принимаю до 15:00».
  await messenger.setMyStatus(kind, messenger.myStatus.custom_text || '')
}
async function saveStatusText() {
  statusOpen.value = false
  await messenger.setMyStatus(messenger.myStatus.kind, statusDraft.value)
}
</script>

<template>
  <div class="absolute bottom-full left-2 right-2 z-40 mb-2 overflow-hidden rounded-xl border border-border2 bg-card shadow-card">
    <!-- Баннер профиля — то же, что видят другие в мессенджере: картинка/гифка, если
         выбрана, иначе полоса цвета. Раньше показывался ТОЛЬКО цвет (баннер не виден
         вовсе), хотя на карточке профиля он уже есть. -->
    <div class="relative h-12 overflow-hidden">
      <img v-if="profile.banner" :src="profile.banner" alt="" class="size-full object-cover" />
      <div v-else class="size-full" :style="plate ? { background: plate } : { background: 'var(--gb-accent)' }" />
    </div>

    <div class="px-3 pb-3">
      <!-- Аватар заходит на полосу, как в Discord. Карандаш по наведению — в «Профиль». -->
      <RouterLink :to="`/${auth.role}/profile`" @click="emit('close')"
                  class="group relative -mt-8 block w-fit rounded-full ring-4 ring-card"
                  :title="locale.t('userOverlay.editProfile', 'Редактировать профиль')">
        <Avatar :src="profile.avatar" :name="fullName" :role="auth.role" :color="plate" :size="64" />
        <span class="absolute inset-0 grid place-items-center rounded-full bg-black/50 opacity-0 transition-opacity group-hover:opacity-100">
          <Pencil class="size-5 text-white" />
        </span>
        <!-- Точка статуса на аватаре — как в мессенджере. -->
        <span class="absolute bottom-0 right-0 size-4 rounded-full border-2 border-card"
              :style="{ background: myStatus.color }" />
      </RouterLink>

      <p class="mt-2 truncate font-title text-base font-extrabold text-text"
         v-bind="myNameDecor">{{ fullName }}</p>
      <p class="truncate text-xs text-text3">
        <span v-if="login">@{{ login }} · </span>{{ roleLabel }}
      </p>

      <!-- «О себе» — то же поле, что видят другие в карточке профиля. -->
      <p v-if="profile.bio" class="mt-2 whitespace-pre-wrap break-words border-t border-border pt-2 text-xs leading-relaxed text-text2">
        {{ profile.bio }}
      </p>

      <!-- Статус: строка-кнопка, раскрывающая список (как «В сети ›» у Discord). -->
      <div class="mt-2 border-t border-border pt-2">
        <button type="button" @click="statusOpen = !statusOpen"
                class="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm text-text transition-colors hover:bg-bg2">
          <span class="size-2.5 shrink-0 rounded-full" :style="{ background: myStatus.color }" />
          <span class="min-w-0 flex-1 truncate">{{ statusText }}</span>
          <ChevronRight class="size-4 shrink-0 text-text3 transition-transform"
                        :class="statusOpen ? 'rotate-90' : ''" />
        </button>

        <div v-if="statusOpen" class="mt-1 flex flex-col gap-0.5">
          <button v-for="k in STATUS_KINDS" :key="k.kind" type="button" @click="pickStatus(k.kind)"
                  class="flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-sm text-text hover:bg-bg2"
                  :class="{ 'bg-accent-glow': messenger.myStatus.kind === k.kind }">
            <span class="size-2.5 shrink-0 rounded-full" :style="{ background: k.color }" />
            {{ k.self }}
          </button>
          <div v-if="canSetStatusText" class="mt-1 border-t border-border pt-1.5">
            <input v-model="statusDraft"
                   :placeholder="locale.t('header.statusTextPlaceholder', 'Текст статуса (видят другие)')"
                   maxlength="80" @keydown.enter="saveStatusText"
                   class="w-full rounded-md border border-border2 bg-card2 px-2 py-1 text-xs text-text outline-none focus:border-accent" />
            <button type="button" @click="saveStatusText"
                    class="mt-1 w-full rounded-md bg-accent px-2 py-1 text-xs font-semibold text-white hover:bg-accent2">
              {{ locale.t('header.saveStatusText', 'Сохранить текст') }}
            </button>
          </div>
        </div>
      </div>

      <RouterLink :to="`/${auth.role}/profile`" @click="emit('close')"
                  class="mt-2 flex items-center gap-2 rounded-md border border-border2 px-2.5 py-1.5 text-sm text-text2 transition-colors hover:border-accent hover:text-accent">
        <Pencil class="size-3.5 shrink-0" />
        {{ locale.t('userOverlay.editProfile', 'Редактировать профиль') }}
      </RouterLink>
    </div>
  </div>
</template>
