<script setup>
// AppUpdateBanner — авто-обновление самого приложения (нативный APK).
// Только в приложении: при старте сверяет versionCode с /app/apk-info; если на сервере
// версия новее — показывает баннер «Доступна новая версия» → «Обновить» открывает APK
// в системном браузере (скачивание → установка; нужно разрешение «неизвестные источники»).
// Веб-слой обновляется отдельно и незаметно (Capgo OTA) — тут только НАТИВНЫЕ апдейты.
import { ref, onMounted } from 'vue'
import { getApiBase } from '@/api/server'

const show = ref(false)
const url = ref('')
const versionName = ref('')

onMounted(async () => {
  let Capacitor
  try { ({ Capacitor } = await import('@capacitor/core')) } catch { return }
  if (!Capacitor?.isNativePlatform?.()) return
  let App
  try { ({ App } = await import('@capacitor/app')) } catch { return }
  try {
    const base = getApiBase()
    if (!base) return
    const res = await fetch(base + '/app/apk-info')
    if (!res.ok) return
    const info = await res.json()
    if (!info?.nativeVersion || !info?.url) return
    const cur = await App.getInfo()            // Android: build = versionCode
    const curCode = parseInt(cur.build, 10) || 0
    if (Number(info.nativeVersion) > curCode) {
      url.value = info.url
      versionName.value = info.versionName || ''
      show.value = true
    }
  } catch { /* офлайн / нет манифеста — молча */ }
})

async function update() {
  try {
    const { Browser } = await import('@capacitor/browser')
    await Browser.open({ url: url.value })     // системный браузер → скачивание → установка
  } catch { /* */ }
}
</script>

<template>
  <transition name="slide-up">
    <div v-if="show"
         class="fixed inset-x-0 z-[60] flex items-center gap-3 border-t border-accent2 bg-accent px-4 py-3 text-white shadow-lg"
         style="bottom: 0; padding-bottom: calc(0.75rem + env(safe-area-inset-bottom))">
      <span class="text-sm font-medium">
        Доступна новая версия приложения<span v-if="versionName"> ({{ versionName }})</span>
      </span>
      <button class="ml-auto shrink-0 rounded-md bg-white/20 px-3 py-1.5 text-sm font-semibold transition-colors hover:bg-white/30"
              @click="update">Обновить</button>
      <button class="shrink-0 rounded-md px-2 py-1 text-sm text-white/80 transition-colors hover:text-white"
              aria-label="Скрыть" @click="show = false">✕</button>
    </div>
  </transition>
</template>

<style scoped>
.slide-up-enter-active, .slide-up-leave-active { transition: transform 0.25s ease, opacity 0.25s ease; }
.slide-up-enter-from, .slide-up-leave-to { transform: translateY(100%); opacity: 0; }
</style>
