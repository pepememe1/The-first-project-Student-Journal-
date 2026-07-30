<script setup>
// LoginPage — экран входа (порт ui/auth_pages.py): светлый фон-«соты», три колонки —
// «Вектор» слева (наведение → поза «думает» + облачко-совет с ротацией), карточка
// входа по центру, карточка «фичи» справа. Адрес сервера НЕ спрашиваем (same-origin).
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { Eye, EyeOff, Bot, Globe, ShieldCheck, Trophy, Monitor, Download, Fingerprint } from '@lucide/vue'
import { useAuthStore } from '@/stores/auth'
import { desktopApi } from '@/api/endpoints'
import { platformAuthenticatorAvailable } from '@/api/webauthn'
import { HOME_BY_ROLE } from '@/config/nav'
import AppButton from '@/components/ui/AppButton.vue'
import DeviceApproval from '@/components/DeviceApproval.vue'
import HexBackground from '@/components/HexBackground.vue'
import BrandLogo from '@/components/BrandLogo.vue'
import Mascot from '@/components/Mascot.vue'
import RegisterDialog from '@/components/RegisterDialog.vue'
import RecoverDialog from '@/components/RecoverDialog.vue'

const router = useRouter()
const auth = useAuthStore()

const login = ref('')
const password = ref('')
const showPass = ref(false)
const needApproval = ref(false)

// Секция «скачать десктоп» — только для ПК (мышь), не для телефонов/планшетов (touch).
const isDesktop = ref(false)
const desktop = ref({ available: false })
// Кнопку «Войти по биометрии» показываем только если на устройстве есть встроенный
// биометрический аутентификатор (Face ID/отпечаток) и браузер поддерживает passkeys.
const canBiometric = ref(false)
onMounted(async () => {
  // greeting держим ~1.6 с, потом плавный переход в покой (без частого мелькания).
  setTimeout(() => { greetingDone.value = true }, 1600)
  isDesktop.value = window.matchMedia?.('(hover: hover) and (pointer: fine)').matches ?? true
  try { desktop.value = (await desktopApi.info()).data } catch { desktop.value = { available: false } }
  try { canBiometric.value = await platformAuthenticatorAvailable() } catch { canBiometric.value = false }
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

// Анимированный Вектор на входе: появляется с «приветствием» (машет), через ~1.6 с
// успокаивается в покой (idle) — задержка убирает мелькание greeting↔idle. Наведение
// мыши → «думает». Все три состояния — тот же анимированный WebP, что и в чате.
const greetingDone = ref(false)

// ── Вектор закрывает глаза, пока набран пароль ──────────────────────────────────────
// Жест смысловой, а не декоративный: маскот показывает, что НЕ подсматривает. Поэтому
// он привязан к наличию символов в поле, а не к наведению мыши — важно, что пароль
// введён, а не куда смотрит курсор.
//
// ⚠️ Обратный ход — ОТДЕЛЬНЫЙ файл `eyes_open` (собран реверсом того же ролика, см.
// tools/build_mascot_anim.py): ни браузер, ни Qt не умеют отматывать анимированный WebP
// назад. Поэтому «убирает лапы» — это проигрывание второго файла, после которого сами
// возвращаемся в покой (в самом WebP loop=1, он застывает на последнем кадре).
const eyesState = ref('')            // '' | 'eyes_close' | 'eyes_open'
// 10 кадров при FPS=12 в сборщике → ~830 мс. Держим с небольшим запасом, чтобы покой
// не начался раньше, чем лапы действительно опустились.
const EYES_OPEN_MS = 900
let eyesTimer = null

watch(() => password.value.length > 0, (typed) => {
  clearTimeout(eyesTimer)
  if (typed) { eyesState.value = 'eyes_close'; return }
  // Поле опустело. Если глаза и не закрывались (страница только открылась), открывать
  // нечего — иначе на пустой форме проигрывалось бы «убирает лапы» из ниоткуда.
  if (!eyesState.value) return
  eyesState.value = 'eyes_open'
  eyesTimer = setTimeout(() => { eyesState.value = '' }, EYES_OPEN_MS)
})
onBeforeUnmount(() => clearTimeout(eyesTimer))

// Закрытые глаза ВАЖНЕЕ «думает» при наведении: пока пароль в поле, маскот не
// подсматривает — это обещание, а подсказка при наведении может и подождать.
const loginAnim = computed(() => {
  if (eyesState.value) return eyesState.value
  return hovered.value ? 'thinking' : (greetingDone.value ? 'idle' : 'greeting')
})

const canSubmit = computed(() => login.value.trim() && password.value && !auth.loading)

// Предложить браузеру/менеджеру паролей сохранить вход. Для SPA/AJAX-входа одних
// autocomplete-атрибутов мало — надёжно срабатывает Credential Management API
// (navigator.credentials.store). Побочный бонус: когда пароль сохранён в системном
// менеджере, iOS предлагает автозаполнение по Face ID, Android — по отпечатку. Где API
// нет (Safari/Firefox) — молча полагаемся на autocomplete-эвристику браузера.
async function saveCredential(id, pass) {
  try {
    if (window.PasswordCredential) {
      const cred = new window.PasswordCredential({ id, password: pass, name: id })
      await navigator.credentials.store(cred)
    }
  } catch { /* сохранение необязательно — не мешаем входу */ }
}

async function submit() {
  needApproval.value = false
  try {
    const user = await auth.login(login.value, password.value)
    await saveCredential(login.value, password.value)
    router.push(HOME_BY_ROLE[user.role] || '/')
  } catch (e) {
    if (e.response?.status === 403) needApproval.value = true
  }
}

// Вход по биометрии (passkey). Отмену пользователем игнорируем молча.
async function submitPasskey() {
  needApproval.value = false
  try {
    const user = await auth.loginPasskey()
    router.push(HOME_BY_ROLE[user.role] || '/')
  } catch {
    /* ошибка уже в auth.error (или отмена — молчим) */
  }
}
function onApproved() { needApproval.value = false; submit() }

// Регистрация студента / восстановление пароля — модалки под кнопкой «Войти».
const showRegister = ref(false)
const showRecover = ref(false)
</script>

<template>
  <div class="relative flex min-h-full items-center justify-center overflow-hidden p-4"
       style="padding-top: calc(1rem + env(safe-area-inset-top)); padding-bottom: calc(1rem + env(safe-area-inset-bottom))">
    <HexBackground />

    <!-- Угловой логотип с названием убран по требованию: знак теперь только в карточке входа. -->

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
        <Mascot :anim="loginAnim" class="h-[30rem] w-80 cursor-pointer" />
      </div>

      <!-- Карточка входа (центр экрана) -->
      <div class="mx-auto w-full max-w-sm justify-self-center rounded-2xl border border-border bg-card p-7 shadow-card">
        <div class="mb-5 flex flex-col items-center text-center">
          <!-- Знак над названием журнала: цвет из темы (кольца — акцентным цветом,
               видны на белой карточке; ядро двухцветное). -->
          <BrandLogo :size="76" oncard />
          <h1 class="mt-3 font-title text-2xl font-extrabold text-text">GradeBookAI</h1>
          <p class="mt-1 text-sm text-text3">Система учёта успеваемости</p>
          <p class="mt-1 text-sm font-semibold text-accent">Технологический колледж ВСГУТУ</p>
        </div>

        <form class="space-y-4" @submit.prevent="submit">
          <div>
            <label class="mb-1.5 block text-xs font-medium text-text3">Логин</label>
            <input v-model="login" id="login" name="username" autocomplete="username"
                   class="h-11 w-full rounded-sm border border-border2 bg-card2 px-3.5 text-text outline-none transition-colors focus:border-accent focus:bg-card"
                   placeholder="Введите логин" />
          </div>
          <div>
            <label class="mb-1.5 block text-xs font-medium text-text3">Пароль</label>
            <div class="relative">
              <input v-model="password" id="password" name="password" :type="showPass ? 'text' : 'password'" autocomplete="current-password"
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

        <!-- Вход по passkey. На телефоне это Face ID/отпечаток, на ПК — «ключ доступа»
             (Windows Hello / PIN / аппаратный ключ), поэтому подпись зависит от устройства.
             Включается в настройках профиля после обычного входа. -->
        <div v-if="canBiometric" class="mt-3">
          <button type="button" :disabled="auth.loading"
                  class="flex w-full items-center justify-center gap-2 rounded-sm border border-accent/50 px-4 py-2.5 text-sm font-semibold text-accent transition-colors hover:bg-accent-glow disabled:opacity-50"
                  @click="submitPasskey">
            <Fingerprint class="size-4" />
            {{ isDesktop ? 'Войти по ключу доступа' : 'Войти по Face ID / отпечатку' }}
          </button>
          <p class="mt-1.5 text-center text-tiny text-text3">Функция настраивается в настройках профиля</p>
        </div>

        <div class="mt-4 border-t border-border pt-3 text-center">
          <p class="text-xs text-text3">Для обучающихся:</p>
          <div class="mt-1.5 flex flex-wrap items-center justify-center gap-2">
            <button type="button" class="rounded-sm border border-accent/40 px-3 py-1.5 text-xs font-semibold text-accent transition-colors hover:bg-accent-glow"
                    @click="showRegister = true">Регистрация</button>
            <button type="button" class="rounded-sm border border-border2 px-3 py-1.5 text-xs font-medium text-text3 transition-colors hover:border-accent hover:text-accent"
                    @click="showRecover = true">Восстановление пароля</button>
          </div>
          <p class="mt-2 text-tiny text-text3">Преподаватели и админ входят по данным от администратора.</p>
        </div>

        <!-- Адрес сервера (как «⚙ Сервер синхронизации» в десктопе): сменить/задать вручную. -->
        <div class="mt-3 text-center">
          <button type="button" class="text-tiny text-text3 transition-colors hover:text-accent" @click="router.push('/connect')">
            ⚙ Сервер синхронизации
          </button>
        </div>

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

    <RegisterDialog v-if="showRegister" @close="showRegister = false" />
    <RecoverDialog v-if="showRecover" @close="showRecover = false" />

    <!-- Футер — заполняет низ, даёт «завершённость» экрану. -->
    <p class="absolute bottom-3 left-1/2 z-10 w-full max-w-[94vw] -translate-x-1/2 px-4 text-center text-tiny leading-relaxed text-text3">
      © 2026 GradeBookAI · Технологический колледж ВСГУТУ · команда Synapse
    </p>
  </div>
</template>

<style scoped>
.pop-enter-active, .pop-leave-active { transition: opacity 0.16s ease, transform 0.16s ease; }
.pop-enter-from, .pop-leave-to { opacity: 0; transform: translate(-50%, 6px); }
</style>
