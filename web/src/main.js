import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { Capacitor } from '@capacitor/core'
import './style.css'
import App from './App.vue'
import { router } from './router'
import { useThemeStore } from './stores/theme'

const app = createApp(App)
app.use(createPinia())

// Тему применяем ДО монтирования (и до router), чтобы не мигал светлый кадр.
const theme = useThemeStore()
theme.apply()
theme.startScheduleWatcher()

app.use(router)
app.mount('#app')

// OTA-обновления (Capgo, только в приложении): подтверждаем, что новый бандл успешно
// загрузился — иначе плагин откатится на предыдущий (защита от «кирпича»). Сама
// проверка/скачивание/применение обновления идёт автоматически (autoUpdate в конфиге,
// updateUrl → https://esstu-gradebook.ru/app/updates).
if (Capacitor.isNativePlatform()) {
  import('@capgo/capacitor-updater')
    .then(({ CapacitorUpdater }) => CapacitorUpdater.notifyAppReady())
    .catch(() => { /* плагин недоступен — не критично */ })
}

// PWA: регистрируем service worker (офлайн-оболочка + «установить приложение»).
// Только для https/localhost и если браузер поддерживает — иначе тихо пропускаем.
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch((e) => {
      console.warn('[PWA] service worker не зарегистрирован:', e)
    })
  })
}
