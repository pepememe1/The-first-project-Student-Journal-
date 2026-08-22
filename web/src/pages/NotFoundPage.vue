<script setup>
// Страница «не найдено».
//
// ━━ КОГДА СЮДА ПОПАДАЮТ ━━
// Только если в адресе оказалась ЧУЖАЯ роль: студент набрал /admin/…, преподаватель
// /student/… и так далее. Промах внутри СВОЕЙ роли сюда не ведёт — там это обычная
// опечатка, и человека возвращают на главную (см. router/index.js).
//
// Разница по смыслу настоящая: «я ошибся буквой» и «мне сюда нельзя» — разные события,
// и раньше оба молча заканчивались дашбордом, из-за чего второе выглядело как сбой.
//
// ⚠️ Цифра вынесена в отдельный узел с `data-404-code`: пасхалка Stanley Parable
// подменяет её на 427 ПО МЕСТУ. Своей цифры сцена не рисует — иначе на экране
// оказались бы две, настоящая под оверлеем и нарисованная поверх.
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useLocaleStore } from '@/stores/locale'
import { useEasterStore } from '@/stores/easterEggs'

const router = useRouter()
const auth = useAuthStore()
const locale = useLocaleStore()
const easter = useEasterStore()

const HOME = { student: '/student', teacher: '/teacher', admin: '/admin', parent: '/parent' }

onMounted(() => {
  // Ровно ОДНА из двух: две шутки на одной странице перестают быть находкой.
  easter.roll(['stanley_parable_404', 'rdr2_404'])
})

function home() { router.push(HOME[auth.role] || '/') }
</script>

<template>
  <div class="grid min-h-[60vh] place-items-center px-4 text-center">
    <div class="flex flex-col items-center gap-3">
      <p data-404-code class="font-mono text-6xl font-bold tabular-nums text-text3">404</p>
      <p class="text-lg font-semibold text-text">
        {{ locale.t('notFound.title', 'Страница не найдена') }}
      </p>
      <p class="max-w-sm text-sm leading-relaxed text-text2">
        {{ locale.t('notFound.hint', 'Этот раздел не относится к вашей роли — или такой страницы просто нет.') }}
      </p>
      <button type="button" @click="home"
              class="mt-2 rounded-lg bg-accent px-5 py-2 text-sm font-semibold text-white hover:brightness-110">
        {{ locale.t('notFound.home', 'На главную') }}
      </button>
    </div>
  </div>
</template>
