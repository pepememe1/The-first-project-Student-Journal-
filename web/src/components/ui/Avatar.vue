<script setup>
// Avatar — круглая аватарка: показывает картинку (prefs.avatar) либо, если её нет,
// значок РОЛИ (RoleAvatarIcon, Discord-style — «у каждой роли свой значок») цветом
// профиля человека; для ролей вне списка (роль неизвестна/не передана — маскот,
// групповой чат и т.п.) — инициалы по ФИО, как было. Единый вид во всех местах
// (список чатов, карточка, каталог людей, модерация).
import { computed } from 'vue'
import { useLocaleStore } from '@/stores/locale'
import RoleAvatarIcon from '@/components/ui/RoleAvatarIcon.vue'
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

const initials = computed(() => {
  const p = (props.name || '').trim().split(/\s+/)
  return ((p[0]?.[0] || '') + (p[1]?.[0] || '')).toUpperCase() || '?'
})
</script>

<template>
  <div class="relative shrink-0" :style="{ width: size + 'px', height: size + 'px' }">
    <div class="size-full overflow-hidden rounded-full" :class="hasRoleIcon || src ? '' : 'bg-accent'">
      <img v-if="src" :src="src" alt="" class="size-full object-cover"
           :style="{ objectPosition: position }" />
      <RoleAvatarIcon v-else-if="hasRoleIcon" :role="role" :color="color || undefined" />
      <span v-else class="grid size-full place-items-center font-bold text-white"
            :style="{ fontSize: Math.round(size * 0.4) + 'px' }">{{ initials }}</span>
    </div>
    <span v-if="online" :title="locale.t('profilePanel.online', 'в сети')"
          class="absolute bottom-0 right-0 size-3 rounded-full border-2 border-card" style="background:#2e9e5b"></span>
  </div>
</template>
