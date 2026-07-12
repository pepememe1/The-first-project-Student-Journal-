<script setup>
// ConnectServer — экран подключения к серверу (порт desktop auth_pages.ask_server_address).
// В приложении показывается при первом запуске: ввёл адрес → проверка /health → сохранили
// → на вход. В браузере доступен по кнопке «⚙ Сервер» (сменить/задать адрес вручную).
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { Server, ArrowRight } from '@lucide/vue'
import HexBackground from '@/components/HexBackground.vue'
import HexLogo from '@/components/HexLogo.vue'
import { getApiBase, normalizeUrl, setApiBase, clearApiBase, checkHealth, isNativeApp } from '@/api/server'

const router = useRouter()
// Показываем текущий адрес (в приложении — вшитый боевой, в браузере — пусто).
const url = ref(getApiBase() || '')
const busy = ref(false)
const error = ref('')
const canProceed = ref(false)
const native = isNativeApp()

async function connect() {
  error.value = ''
  canProceed.value = false
  const u = normalizeUrl(url.value)
  if (!u) { error.value = 'Введите адрес сервера'; return }
  busy.value = true
  try {
    const ok = await checkHealth(u)
    setApiBase(u)                    // сохраняем ВСЕГДА (как десктоп: адрес сохранён)
    if (ok) { router.replace('/login'); return }
    // Не достучались — НЕ блокируем: адрес сохранён, даём войти вручную.
    error.value = 'Не удалось проверить сервер. Адрес сохранён — можно продолжить и войти, либо исправить ссылку.'
    canProceed.value = true
  } finally {
    busy.value = false
  }
}

function proceed() { router.replace('/login') }

// В браузере: вернуться к работе на этом же сайте (сбросить адрес).
function useThisSite() {
  clearApiBase()
  router.replace('/login')
}
</script>

<template>
  <div class="relative flex min-h-full items-center justify-center overflow-hidden p-4"
       style="padding-top: calc(1rem + env(safe-area-inset-top)); padding-bottom: calc(1rem + env(safe-area-inset-bottom))">
    <HexBackground />

    <div class="relative z-10 mx-auto w-full max-w-sm rounded-2xl border border-border bg-card p-7 shadow-card">
      <div class="mb-5 flex flex-col items-center text-center">
        <HexLogo :size="56" />
        <h1 class="mt-3 font-title text-2xl font-extrabold text-text">GradeBookAI</h1>
        <p class="mt-1 text-sm text-text3">Подключение к серверу колледжа</p>
      </div>

      <form class="space-y-4" @submit.prevent="connect">
        <div>
          <label class="mb-1.5 block text-xs font-medium text-text3">Адрес сервера</label>
          <input v-model="url" inputmode="url" autocapitalize="none" autocorrect="off" spellcheck="false"
                 class="h-11 w-full rounded-sm border border-border2 bg-card2 px-3.5 text-text outline-none transition-colors focus:border-accent focus:bg-card"
                 placeholder="https://esstu-gradebook.ru  или  http://192.168.0.101:8000" />
          <p class="mt-1.5 text-tiny text-text3">Ссылку выдаёт администратор колледжа. Без «https://» — подставим сами.</p>
        </div>

        <p v-if="error" class="rounded-sm border border-red/40 bg-red/10 px-3 py-2 text-sm text-red">{{ error }}</p>

        <button type="submit" :disabled="busy"
                class="flex h-11 w-full items-center justify-center gap-2 rounded-sm bg-accent font-semibold text-white transition-colors hover:bg-accent2 disabled:opacity-50">
          <Server class="size-4" />
          {{ busy ? 'Проверяем…' : 'Подключиться' }}
          <ArrowRight v-if="!busy" class="size-4" />
        </button>
      </form>

      <!-- Сервер не ответил на проверку, но адрес сохранён — можно продолжить. -->
      <button v-if="canProceed" type="button" @click="proceed"
              class="mt-3 w-full rounded-sm border border-accent/50 py-2.5 text-sm font-semibold text-accent transition-colors hover:bg-accent-glow">
        Продолжить всё равно
      </button>

      <!-- В браузере (сайт на своём домене) — можно работать на этом же адресе. -->
      <div v-if="!native" class="mt-4 border-t border-border pt-3 text-center">
        <button type="button" class="text-xs font-medium text-text3 transition-colors hover:text-accent" @click="useThisSite">
          Использовать этот сайт (тот же адрес)
        </button>
      </div>
    </div>

    <p class="absolute bottom-3 left-1/2 z-10 w-full max-w-[94vw] -translate-x-1/2 px-4 text-center text-tiny leading-relaxed text-text3">
      © 2026 GradeBookAI · Технологический колледж ВСГУТУ · команда Synapse
    </p>
  </div>
</template>
