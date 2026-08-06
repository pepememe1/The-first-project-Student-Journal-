<script setup>
// RoleAvatarIcon — дефолтная аватарка по РОЛИ вместо инициалов (Discord-style: у людей
// без своей картинки — не буквы, а узнаваемый значок роли). Фон значка = ЦВЕТ ПРОФИЛЯ
// человека (см. Avatar.vue — передаёт `color` из profilePlate(prefs.profile_color)),
// а не фиксированный цвет на роль: две учительницы с разными цветами профиля получат
// один и тот же значок, но разного цвета — ровно как просил заказчик.
//
// 4 значка ролей (student/teacher/admin/parent, см. config/roles.js) + 5-й, служебный —
// «модерация»: НЕ роль аккаунта, а синтетический «собеседник» чата с администрацией
// (messenger.js — role: 'moderation' у peer вида {full_name: 'Модерация', ...}, см.
// messengerApi.moderation()). Живой баг: этот псевдо-собеседник не входил в список
// значков и везде, где показывается его аватарка (панель профиля собеседника и т.п.),
// падал на голые инициалы «М» — заметно на фоне того, что у всех остальных есть значок.
defineProps({
  role: { type: String, default: '' },
  color: { type: String, default: 'var(--gb-accent)' },
})
</script>

<template>
  <svg viewBox="0 0 80 80" xmlns="http://www.w3.org/2000/svg" class="block size-full">
    <circle cx="40" cy="40" r="40" :fill="color" />

    <!-- Администратор: шестерня + ключ -->
    <template v-if="role === 'admin'">
      <path d="M44.5 21.5 L43 17 L37 17 L35.5 21.5 Q33 22.5 31 24L26.5 22.5 L22.5 27.5 L25 31.5
               Q24 34 24 37 L19.5 38.5 L19.5 44.5 L24 46 Q25 48.5 26.5 50.5 L24 54.5 L28.5 59 L32.5 56.5
               Q35 58 37.5 58.5 L39 63 L45 63 L46.5 58.5 Q49 57.5 51.5 56.5 L55.5 59 L60 54.5 L57.5 50.5
               Q59 48.5 59.5 46 L64 44.5 L64 38.5 L59.5 37 Q59 34.5 57.5 32 L60 28 L55.5 23 L51.5 25.5
               Q49 23.5 46.5 22.5 Z" fill="white" opacity=".9" />
      <circle cx="41.5" cy="41" r="8" :fill="color" />
      <circle cx="41" cy="40" r="7.5" fill="none" stroke="white" stroke-width="2.5" opacity=".95" />
      <rect x="44.5" y="39" width="12" height="2.5" rx="1.25" fill="white" opacity=".95" />
      <rect x="53" y="41.5" width="2.5" height="3.5" rx="1" fill="white" opacity=".95" />
      <rect x="49" y="41.5" width="2.5" height="2.5" rx="1" fill="white" opacity=".95" />
    </template>

    <!-- Преподаватель: шапка выпускника + диплом -->
    <template v-else-if="role === 'teacher'">
      <polygon points="40,20 64,33 40,38 16,33" fill="white" opacity=".95" />
      <polygon points="40,38 16,33 16,46 40,51 64,46 64,33" fill="white" opacity=".3" />
      <rect x="62" y="33" width="3" height="14" rx="1.5" fill="white" opacity=".8" />
      <circle cx="63.5" cy="48" r="3" fill="white" opacity=".9" />
      <rect x="27" y="53" width="26" height="18" rx="3" fill="white" opacity=".9" />
      <rect x="31" y="57" width="18" height="2" rx="1" :fill="color" opacity=".6" />
      <rect x="31" y="61" width="14" height="2" rx="1" :fill="color" opacity=".4" />
      <rect x="31" y="65" width="11" height="2" rx="1" :fill="color" opacity=".3" />
    </template>

    <!-- Студент: раскрытая книга + маленькая шапка -->
    <template v-else-if="role === 'student'">
      <polygon points="40,16 54,23 40,27 26,23" fill="white" opacity=".9" />
      <rect x="52" y="23" width="2.5" height="9" rx="1.25" fill="white" opacity=".7" />
      <circle cx="53.25" cy="33" r="2.5" fill="white" opacity=".8" />
      <path d="M18 38 Q18 35 22 35 L40 37 L40 62 Q32 60 22 62 Q18 62 18 59 Z" fill="white" opacity=".9" />
      <path d="M62 38 Q62 35 58 35 L40 37 L40 62 Q48 60 58 62 Q62 62 62 59 Z" fill="white" opacity=".75" />
      <line x1="40" y1="37" x2="40" y2="62" :stroke="color" stroke-width="1.5" opacity=".4" />
      <rect x="23" y="41" width="13" height="1.5" rx=".75" :fill="color" opacity=".35" />
      <rect x="23" y="45" width="11" height="1.5" rx=".75" :fill="color" opacity=".3" />
      <rect x="23" y="49" width="13" height="1.5" rx=".75" :fill="color" opacity=".25" />
      <rect x="44" y="41" width="13" height="1.5" rx=".75" :fill="color" opacity=".3" />
      <rect x="44" y="45" width="10" height="1.5" rx=".75" :fill="color" opacity=".25" />
      <rect x="44" y="49" width="12" height="1.5" rx=".75" :fill="color" opacity=".2" />
    </template>

    <!-- Родитель: домик + окно-сердце -->
    <template v-else-if="role === 'parent'">
      <path d="M40 18 L64 38 L58 38 L58 62 L22 62 L22 38 L16 38 Z" fill="white" opacity=".9" />
      <path d="M40 34 Q40 30 36 30 Q32 30 32 34 Q32 38 40 43 Q48 38 48 34 Q48 30 44 30 Q40 30 40 34 Z"
            :fill="color" opacity=".7" />
    </template>

    <!-- Модерация: щит + галочка -->
    <template v-else-if="role === 'moderation'">
      <path d="M40 16 L58 25 L58 44 Q58 57 40 65 Q22 57 22 44 L22 25 Z" fill="white" opacity=".18" />
      <path d="M40 19 L55 27 L55 44 Q55 55 40 62 Q25 55 25 44 L25 27 Z"
            fill="none" stroke="white" stroke-width="2.2" stroke-linejoin="round" opacity=".95" />
      <path d="M31 42 L38 49 L51 33" fill="none" stroke="white" stroke-width="3.5"
            stroke-linecap="round" stroke-linejoin="round" />
    </template>
  </svg>
</template>
