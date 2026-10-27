<script setup>
// Avatar — круглая аватарка: показывает картинку (prefs.avatar) либо, если её нет,
// значок РОЛИ (RoleAvatarIcon, Discord-style — «у каждой роли свой значок») цветом
// профиля человека; для ролей вне списка (роль неизвестна/не передана — маскот,
// групповой чат и т.п.) — инициалы по ФИО, как было. Единый вид во всех местах
// (список чатов, карточка, каталог людей, модерация).
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useLocaleStore } from '@/stores/locale'
import RoleAvatarIcon from '@/components/ui/RoleAvatarIcon.vue'
import { gifPosterSrc, gifStillSrc, gifVideoSrc, mediaSrc, playMuted, watchInView } from '@/utils/mediaSrc'
const locale = useLocaleStore()

const props = defineProps({
  src: { type: String, default: '' },
  name: { type: String, default: '' },
  size: { type: Number, default: 40 },
  online: { type: Boolean, default: false },
  //Какую часть картинки оставлять при кадрировании в круг. Аватарки людей обрезаны по
  //центру ещё при загрузке, а спрайт маскота — фигура в полный рост: без 'top' в кружок
  //попало бы туловище вместо морды.
  position: { type: String, default: 'center' },
  //Роль (student/teacher/admin/parent/moderation) — выбирает значок по умолчанию.
  //Пусто/неизвестная роль — откат на инициалы (прежнее поведение, для маскота/групп/
  //каналов и т.п.). 'moderation' — не роль аккаунта, а синтетический peer чата с
  //администрацией (см. RoleAvatarIcon.vue).
  role: { type: String, default: '' },
  //Цвет фона значка роли — обычно profilePlate(prefs.profile_color) вызывающей стороны.
  //На инициалы НЕ влияет (у них свой класс bg-accent, как было всегда).
  color: { type: String, default: '' },
})

const ROLE_ICONS = new Set(['admin', 'teacher', 'student', 'parent', 'moderation'])
const hasRoleIcon = computed(() => ROLE_ICONS.has(props.role))

//Картинка через `mediaSrc`: ссылка боя на аватарку открывается от адреса сервера, а
//внутри программы гифка идёт через кэш (см. utils/mediaSrc.js).
const shown = computed(() => mediaSrc(props.src))
//Не загрузилась (сменили аватарку, а список ещё не перечитан; нет сети) — рисуем значок
//роли или инициалы, а не пустой кружок. Новая ссылка — новая попытка.
const failed = ref(false)
//Гифка Klipy — как аватарки Discord: сразу первый кадр (webp, десятки КБ), следом ролик
//MP4, который браузер показывает по мере загрузки, а не целым файлом. Ролик качается,
//только когда аватарку видно, и стоит на паузе вне экрана (utils/mediaSrc.js).
const video = computed(() => gifVideoSrc(props.src))
const poster = computed(() => gifPosterSrc(props.src))
const videoFailed = ref(false)
//🔑 Первый кадр — ПОДЛОЖКА, а не запасной путь после отказа (27.10.2026, требование
//Влада «если клипи не работает — один кадр из гифки, как обычная аватарка»). Лёгкий
//webp лежит под роликом всегда: гифка не открылась (Klipy недоступен, ролик не
//поддержан) — человек видит кадр, а не пустой круг, и ждать таймаута CDN ради этого не
//нужно. Кадр аватарок сервер держит у себя про запас (`klipy_media.pin`).
const still = computed(() => gifStillSrc(props.src))
const stillFailed = ref(false)
const stillOk = computed(() => !!still.value && !stillFailed.value)
watch(shown, () => { failed.value = false; videoFailed.value = false; stillFailed.value = false })
const box = ref(null)
const videoEl = ref(null)
const seen = ref(false)
let unwatch = () => {}
onMounted(() => {
  unwatch = watchInView(box.value, (visible) => {
    if (visible) seen.value = true
    const v = videoEl.value
    if (!v) return
    if (visible) v.play?.()?.catch?.(() => {})
    else v.pause?.()
  })
})
onBeforeUnmount(() => unwatch())

const initials = computed(() => {
  const p = (props.name || '').trim().split(/\s+/)
  return ((p[0]?.[0] || '') + (p[1]?.[0] || '')).toUpperCase() || '?'
})
</script>

<template>
  <div ref="box" class="relative shrink-0" :style="{ width: size + 'px', height: size + 'px' }">
    <div class="relative size-full overflow-hidden rounded-full" :class="hasRoleIcon || stillOk || (shown && !failed) || (video && !videoFailed) ? '' : 'bg-accent'">
      <img v-if="stillOk" :src="still" alt="" decoding="async" class="absolute inset-0 size-full object-cover"
           :style="{ objectPosition: position }" @error="stillFailed = true" />
      <template v-if="video && !videoFailed">
        <video v-if="seen" ref="videoEl" :src="video" :poster="poster" autoplay muted loop playsinline
               preload="auto" disablepictureinpicture aria-hidden="true" class="relative size-full object-cover"
               :style="{ objectPosition: position }" @canplay="playMuted" @error="videoFailed = true" />
      </template>
      <img v-else-if="shown && !failed" :src="shown" alt="" class="relative size-full object-cover"
           :style="{ objectPosition: position }" @error="failed = true" />
      <RoleAvatarIcon v-else-if="hasRoleIcon && !stillOk" :role="role" :color="color || undefined" />
      <span v-else-if="!stillOk" class="grid size-full place-items-center font-bold text-white"
            :style="{ fontSize: Math.round(size * 0.4) + 'px' }">{{ initials }}</span>
    </div>
    <span v-if="online" :title="locale.t('profilePanel.online', 'в сети')"
          class="absolute bottom-0 right-0 size-3 rounded-full border-2 border-card" style="background:#2e9e5b"></span>
  </div>
</template>
