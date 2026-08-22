<script setup>
// Страница «не найдено» — САМОСТОЯТЕЛЬНАЯ, без сайдбара и шапки.
//
// ━━ ПОЧЕМУ БЕЗ ОБОЛОЧКИ ━━
// Сюда попадают, только если в адресе оказалась ЧУЖАЯ роль: студент набрал /admin/…,
// преподаватель /student/…. Показывать при этом чужое меню было бы странно вдвойне —
// человеку и так говорят «этот раздел не ваш», а рядом стоит навигация. Промах внутри
// СВОЕЙ роли сюда не ведёт вовсе: там обычная опечатка, и человека возвращают на
// главную (см. utils/missedRoute.js).
//
// Вид — тот же, что у входа: соты на весь экран и одна карточка по центру. Это уже
// знакомый человеку «экран вне кабинета», и второй визуальный язык для него заводить
// незачем.
//
// ⚠️ Цифра вынесена в отдельный узел с `data-404-code`: пасхалка Stanley Parable
// подменяет её на 427 ПО МЕСТУ. Своей цифры сцена не рисует — иначе на экране
// оказались бы две, настоящая под оверлеем и нарисованная поверх.
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useLocaleStore } from '@/stores/locale'
import { useEasterStore } from '@/stores/easterEggs'
import HexBackground from '@/components/HexBackground.vue'
import BrandLogo from '@/components/BrandLogo.vue'
import EasterEggHost from '@/components/easter/EasterEggHost.vue'

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
  <div class="relative flex min-h-full items-center justify-center overflow-x-hidden overflow-y-auto p-4"
       style="padding-top: calc(1rem + env(safe-area-inset-top));
              padding-bottom: calc(1rem + env(safe-area-inset-bottom))">
    <HexBackground />

    <div class="relative z-10 flex w-full max-w-sm flex-col items-center gap-4 rounded-2xl border
                border-border2 bg-card/95 px-7 py-9 text-center shadow-card backdrop-blur-sm">
      <BrandLogo class="h-9 w-9 opacity-70" />

      <p data-404-code class="font-title text-6xl font-extrabold tabular-nums leading-none text-text3">404</p>

      <p class="text-base font-semibold text-text">
        {{ locale.t('notFound.title', 'Такой страницы не существует') }}
      </p>
      <p class="text-sm leading-relaxed text-text2">
        {{ locale.t('notFound.hint', 'Возможно, этот раздел не относится к вашей роли.') }}
      </p>

      <button type="button" @click="home"
              class="mt-1 w-full rounded-lg bg-accent px-5 py-2.5 text-sm font-semibold text-white
                     transition hover:brightness-110">
        {{ locale.t('notFound.home', 'На главную') }}
      </button>
    </div>

    <!-- Хост пасхалок здесь СВОЙ: страница живёт вне оболочки, а тот, что в AppShell,
         на неё не распространяется. Без этого Stanley и RDR2 роллились бы вхолостую. -->
    <EasterEggHost />
  </div>
</template>
