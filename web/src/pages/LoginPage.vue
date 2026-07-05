<script setup>
// LoginPage — экран входа (порт ui/auth_pages.py): светлый фон-«соты», три колонки —
// «Вектор» слева (наведение → поза «думает» + облачко-совет с ротацией), карточка
// входа по центру, карточка «фичи» справа. Адрес сервера НЕ спрашиваем (same-origin).
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { Eye, EyeOff, Bot, Globe, ShieldCheck, Trophy, Monitor, Download } from '@lucide/vue'
import { useAuthStore } from '@/stores/auth'
import { desktopApi } from '@/api/endpoints'
import { HOME_BY_ROLE } from '@/config/nav'
import AppButton from '@/components/ui/AppButton.vue'
import DeviceApproval from '@/components/DeviceApproval.vue'
import HexBackground from '@/components/HexBackground.vue'
import HexLogo from '@/components/HexLogo.vue'
import Mascot from '@/components/Mascot.vue'

const router = useRouter()
const auth = useAuthStore()

const login = ref('')
const password = ref('')
const showPass = ref(false)
const needApproval = ref(false)

// Секция «скачать десктоп» — только для ПК (мышь), не для телефонов/планшетов (touch).
const isDesktop = ref(false)
const desktop = ref({ available: false })
onMounted(async () => {
  isDesktop.value = window.matchMedia?.('(hover: hover) and (pointer: fine)').matches ?? true
  try { desktop.value = (await desktopApi.info()).data } catch { desktop.value = { available: false } }
})

// Наведение на Вектора: поза «думает» + облачко-совет. Крутятся полезные подсказки и
// интересные факты о ВСГУТУ, обо мне и о разработке GradeBookAI (без «внутренностей»).
const TIPS = [
  // — Важное про вход —
  'За логином и паролем обратитесь к администратору колледжа.',
  'Пароль вводите внимательно: после нескольких неудачных попыток вход ненадолго блокируется.',
  'Студенты и преподаватели входят по логину и паролю, которые выдал администратор.',
  // — Полезное про приложение —
  'Десктоп-версия работает и без интернета: данные сохранятся локально и синхронизируются, когда сеть вернётся.',
  'Оценки, средний балл, долги и пропуски всегда под рукой — и в приложении, и на сайте.',
  'Я беру цифры из реальных данных журнала, а не выдумываю их — на меня можно положиться.',
  'Тёмную тему можно включить по расписанию: вечером сама затемняется, утром светлеет.',
  'Расписание тянется прямо с портала ВСГУТУ и обновляется автоматически.',
  'Забыл пароль? Его выдаёт и меняет администратор колледжа — обратись к нему.',
  'Один аккаунт — на всех устройствах: тема и данные «переезжают» за тобой.',
  // — Про ВСГУТУ —
  'Факт: ВСГУТУ — Восточно-Сибирский государственный университет технологий и управления в Улан-Удэ.',
  'Технологический колледж ВСГУТУ готовит специалистов среднего звена — для них и сделан этот журнал.',
  'Учебный год в колледже идёт по неделям I и II — расписание это учитывает.',
  // — Про меня, Вектора —
  'Меня зовут Вектор, я тигр — символ силы и упорства. Помогаю тебе держать успеваемость в тонусе.',
  'Арт для меня нарисовала участница команды Synapse.',
  // — Про разработку —
  'GradeBookAI создала студенческая команда Synapse.',
  'Проект — победитель хакатона «Мы — будущее IT Бурятии».',
  'Приложение спроектировано под 152-ФЗ: персональные данные шифруются, канал защищён HTTPS.',
]
const hovered = ref(false)
const tipIndex = ref(0)
const tip = computed(() => TIPS[tipIndex.value])
function onEnter() { hovered.value = true; tipIndex.value = (tipIndex.value + 1) % TIPS.length }

const canSubmit = computed(() => login.value.trim() && password.value && !auth.loading)

async function submit() {
  needApproval.value = false
  try {
    const user = await auth.login(login.value, password.value)
    router.push(HOME_BY_ROLE[user.role] || '/')
  } catch (e) {
    if (e.response?.status === 403) needApproval.value = true
  }
}
function onApproved() { needApproval.value = false; submit() }
</script>

<template>
  <div class="relative flex min-h-full items-center justify-center overflow-hidden p-4">
    <HexBackground />

    <!-- Брендинг в углу — заполняет верх и держит фирменный стиль. -->
    <div class="absolute left-6 top-5 z-10 hidden items-center gap-2.5 sm:flex">
      <HexLogo :size="32" />
      <div class="leading-tight">
        <p class="font-title text-base font-extrabold text-text">GradeBookAI</p>
        <p class="text-tiny text-text3">by Synapse</p>
      </div>
    </div>

    <!-- Сетка 1fr · auto · 1fr: карточка входа СТРОГО по центру экрана (боковые колонки
         равны). items-center — блок по центру по вертикали (не прижат к низу). -->
    <div class="relative z-10 grid w-full max-w-6xl grid-cols-1 items-center gap-x-6 gap-y-4 lg:grid-cols-[1fr_auto_1fr]">
      <!-- «Вектор» слева, прижат к правому краю колонки (ближе к карточке). Облачко —
           АБСОЛЮТНО НАД маскотом (bottom-full), поэтому не залазит на него. -->
      <div class="relative hidden justify-self-end lg:block"
           @mouseenter="onEnter" @mouseleave="hovered = false">
        <transition name="pop">
          <div v-if="hovered" class="absolute bottom-full left-1/2 mb-3 w-64 -translate-x-1/2 rounded-2xl border border-border2 bg-card px-4 py-3 shadow-card">
            <p class="text-sm font-extrabold text-accent">💡 Совет Вектора</p>
            <p class="mt-1 text-sm font-semibold text-text">{{ tip }}</p>
            <div class="absolute -bottom-2 left-1/2 size-4 -translate-x-1/2 rotate-45 border-b border-r border-border2 bg-card" />
          </div>
        </transition>
        <Mascot :sprite="hovered ? 'think-think' : 'neutral-idle'" class="h-[30rem] w-80 cursor-pointer" />
      </div>

      <!-- Карточка входа (центр экрана) -->
      <div class="mx-auto w-full max-w-sm justify-self-center rounded-2xl border border-border bg-card p-7 shadow-card">
        <div class="mb-5 flex flex-col items-center text-center">
          <HexLogo :size="56" />
          <h1 class="mt-3 font-title text-2xl font-extrabold text-text">GradeBookAI</h1>
          <p class="mt-1 text-sm text-text3">Система учёта успеваемости</p>
          <p class="mt-1 text-sm font-semibold text-accent">Технологический колледж ВСГУТУ</p>
        </div>

        <form class="space-y-4" @submit.prevent="submit">
          <div>
            <label class="mb-1.5 block text-xs font-medium text-text3">Логин</label>
            <input v-model="login" autocomplete="username"
                   class="h-11 w-full rounded-sm border border-border2 bg-card2 px-3.5 text-text outline-none transition-colors focus:border-accent focus:bg-card"
                   placeholder="Введите логин" />
          </div>
          <div>
            <label class="mb-1.5 block text-xs font-medium text-text3">Пароль</label>
            <div class="relative">
              <input v-model="password" :type="showPass ? 'text' : 'password'" autocomplete="current-password"
                     class="h-11 w-full rounded-sm border border-border2 bg-card2 px-3.5 pr-11 text-text outline-none transition-colors focus:border-accent focus:bg-card"
                     placeholder="••••••••" />
              <button type="button" class="absolute right-2 top-1/2 grid size-8 -translate-y-1/2 place-items-center rounded-sm text-text2 hover:text-accent"
                      :aria-label="showPass ? 'Скрыть' : 'Показать'" @click="showPass = !showPass">
                <EyeOff v-if="showPass" class="size-4" /><Eye v-else class="size-4" />
              </button>
            </div>
          </div>

          <p v-if="auth.error" class="rounded-sm border border-red/40 bg-red/10 px-3 py-2 text-sm text-red">{{ auth.error }}</p>

          <AppButton type="submit" class="w-full" :disabled="!canSubmit">
            {{ auth.loading ? 'Входим…' : 'Войти' }}
          </AppButton>
        </form>

        <p class="mt-4 text-center text-xs text-text3">
          Студенты и преподаватели входят по логину и паролю, которые выдал администратор.
        </p>

        <DeviceApproval v-if="needApproval" @approved="onApproved" />
      </div>

      <!-- Правая колонка: карточка «фичи» + (только для ПК) скачать десктоп -->
      <div class="hidden w-72 flex-col gap-4 justify-self-start lg:flex">
        <div class="rounded-2xl border border-border bg-card p-6 shadow-card">
        <h2 class="font-title text-2xl font-extrabold leading-tight text-text">Журнал, который думает вместе с вами</h2>
        <p class="mt-3 text-sm text-text3">
          Электронный журнал с ИИ-помощником «Вектор»: оценки, средний балл, долги и пропуски — понятно и под рукой.
        </p>
        <ul class="mt-5 space-y-3 text-sm">
          <li class="flex items-center gap-3 text-text"><Bot class="size-5 text-accent" /> ИИ-помощник «Вектор»</li>
          <li class="flex items-center gap-3 text-text"><Globe class="size-5 text-accent" /> Работает на всех устройствах</li>
          <li class="flex items-center gap-3 text-text"><ShieldCheck class="size-5 text-accent" /> Безопасно — по 152-ФЗ</li>
        </ul>
        <div class="mt-5 flex items-start gap-2 rounded-lg border border-border bg-card2 px-3 py-2.5">
          <Trophy class="mt-0.5 size-4 shrink-0 text-yellow" />
          <p class="text-xs font-medium text-text3">Победитель хакатона «Мы — будущее IT Бурятии»</p>
        </div>
          <p class="mt-4 text-tiny text-text2">GradeBookAI · Web Edition</p>
        </div>

        <!-- Скачать десктоп-версию — только на ПК (мышь), не на телефоне/планшете. -->
        <div v-if="isDesktop" class="rounded-2xl border border-border bg-card p-5 shadow-card">
          <div class="flex items-center gap-2">
            <Monitor class="size-5 text-accent" />
            <h3 class="font-title text-base font-extrabold text-text">Десктоп-версия</h3>
          </div>
          <p class="mt-2 text-xs text-text3">
            Полноценный офлайн-first клиент для Windows: работает без интернета, данные
            хранятся локально и синхронизируются позже. Быстрый, со встроенным Вектором.
          </p>
          <a v-if="desktop.available" :href="desktop.url" download
             class="mt-3 flex items-center justify-center gap-2 rounded-sm bg-accent px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-accent2">
            <Download class="size-4" /> Скачать GradeBookAI.exe
            <span v-if="desktop.size_mb" class="text-xs opacity-80">· {{ desktop.size_mb }} МБ</span>
          </a>
          <div v-else class="mt-3 rounded-sm border border-border2 bg-card2 px-4 py-2.5 text-center text-xs font-medium text-text3">
            Установщик готовится к выпуску
          </div>
        </div>
      </div>
    </div>

    <!-- Футер — заполняет низ, даёт «завершённость» экрану. -->
    <p class="absolute bottom-4 left-1/2 z-10 -translate-x-1/2 whitespace-nowrap px-4 text-center text-tiny text-text3">
      © 2026 GradeBookAI · Технологический колледж ВСГУТУ · команда Synapse
    </p>
  </div>
</template>

<style scoped>
.pop-enter-active, .pop-leave-active { transition: opacity 0.16s ease, transform 0.16s ease; }
.pop-enter-from, .pop-leave-to { opacity: 0; transform: translate(-50%, 6px); }
</style>
