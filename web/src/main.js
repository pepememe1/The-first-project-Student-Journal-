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

  // Пуш-уведомления. Три вещи по порядку:
  //  1) слушаем нажатия — нативная часть зовёт колбэк и при «холодном» старте тоже;
  //  2) подтверждаем токен устройства (сервер по нему держит владельца и метку «живо»);
  //  3) доигрываем отложенный переход — он мог остаться с прошлого запуска, если в
  //     момент нажатия сессия была просрочена и пользователь только что вошёл.
  import('./services/push')
    .then(async (push) => {
      push.onNotificationTap(router)
      await push.registerToken()
      await push.consumePendingEvent(router)
    })
    .catch(() => { /* вне приложения моста нет — это норма */ })
}

// PWA: регистрируем service worker (офлайн-оболочка + «установить приложение»).
// Только для https/localhost и если браузер поддерживает — иначе тихо пропускаем.
// ⚠️ ВНУТРИ ДЕСКТОПА не регистрируем вовсе (ни старый embed=1 — ui/messenger_web.py,
// ни новый embed=nav — ui/vue_dashboard.py/vue_shell.py, см. AppShell.vue). Там оболочка
// своя (QWebEngineView), офлайн обеспечивает локальный сервер приложения (ui/local_api.py),
// а «установить приложение» бессмысленно — оно уже установлено. Регистрация там только
// падала с DOMException и сыпала в лог.
const _inDesktop = (() => {
  try {
    const v = new URLSearchParams(window.location.search).get('embed')
      || localStorage.getItem('gb.embed') || ''
    return v === '1' || v === 'nav'
  } catch { return false }
})()

// ⚠️ В МОБИЛЬНОМ ПРИЛОЖЕНИИ service worker НЕ НУЖЕН И ВРЕДЕН — из-за него обновления
// «по воздуху» не доходили до людей МЕСЯЦ. Механика: Capgo подменяет веб-бандл, но
// адрес остаётся прежним (http://localhost), поэтому уже установленный worker
// продолжает отдавать СТАРУЮ оболочку и старые ассеты из своего кэша (`/assets/*` он
// отдаёт cache-first). Приложение исправно скачивало новый бандл при каждом запуске —
// это видно в логах сервера — и каждый раз показывало прежнюю версию.
//
// Оффлайн в приложении обеспечивает не worker, а сам Capacitor: файлы бандла лежат на
// устройстве и открываются без сети. Так что здесь worker не давал ничего и ломал всё.
//
// СНИМАЕМ уже установленный, а не просто «не регистрируем»: на телефонах он давно
// стоит, и без явного удаления новый бандл до них не доберётся никогда — его же
// собственный код не запустится, чтобы это исправить.
if (Capacitor.isNativePlatform()) {
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.getRegistrations()
      .then((regs) => Promise.all(regs.map((r) => r.unregister())))
      .then((done) => {
        if (done.some(Boolean)) console.info('[PWA] service worker снят (мешал OTA)')
      })
      .catch(() => { /* нет доступа — значит и worker'а нет */ })
  }
  if (typeof caches !== 'undefined') {
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k.startsWith('gb-')).map((k) => caches.delete(k))))
      .catch(() => { /* кэша нет — нечего чистить */ })
  }
} else if ('serviceWorker' in navigator && !_inDesktop) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch((e) => {
      console.warn('[PWA] service worker не зарегистрирован:', e)
    })
  })
}
