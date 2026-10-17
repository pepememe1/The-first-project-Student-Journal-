// gif.js — GIF-пикер мессенджера (Klipy).
//
// Категории/тренды/поиск идут ЧЕРЕЗ СЕРВЕР (server/app/gif_service.py) — ключ Klipy
// никогда не покидает бэкенд, клиент его не видит вовсе.
//
// «Избранное» — в prefs АККАУНТА, а не в localStorage: тот же принцип, что у настроек
// перевода (stores/translate.js) — человек заходит и с телефона, и с компьютера, и
// заново собирать список на каждом устройстве — та мелочь, из-за которой функцией
// перестают пользоваться. Сервер сам режет записи не с CDN Klipy (см. me.py
// ::_sanitize_gif_favorites) — здесь дополнительной проверки не дублируем.
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { meApi, messengerApi } from '@/api/endpoints'
import { isDesktopApp } from '@/utils/platform'
import { prefetchImages } from '@/utils/mediaSrc'

//Категории и первая страница «В тренде» одинаковы для всех и меняются медленно: держим их
//в памяти вкладки 10 минут, и пикер открывается сразу, без похода на сервер и в Klipy.
const MEMO_MS = 10 * 60 * 1000

export const useGifStore = defineStore('gif', () => {
  const favorites = ref([])
  const loaded = ref(false)
  const error = ref('')
  let memoCats = null
  let memoCatsAt = 0
  let memoTrend = null
  let memoTrendAt = 0
  let warmed = false

  async function load() {
    if (loaded.value) return
    try {
      const { data } = await meApi.getPrefs()
      favorites.value = data?.prefs?.gif_favorites || []
      // ⚠️ (живой отзыв: «избранные гифки не видно на десктопе») loaded ставим ТОЛЬКО
      // при успехе. Внутри десктопа этот запрос идёт через локальный прокси на бой (см.
      // ui/local_api.py), и на самый первый заход в мессенджер сразу после холодного
      // старта токен может быть ещё не готов — один неудачный запрос раньше НАВСЕГДА
      // (до перезапуска) оставлял избранное пустым, хотя данные на сервере есть.
      loaded.value = true
    } catch { /* избранное — дополнение к пикеру, без него GIF всё равно работают; не
                 отмечаем loaded — следующий вызов (открытие пикера) попробует снова */ }
  }

  function isFavorite(slug) {
    return favorites.value.some((f) => f.slug === slug)
  }

  // Оптимистично: список уже переключён на экране, ошибка сохранения только
  // выводится, а не откатывает локальное состояние (тот же приём, что в translate.js).
  async function toggleFavorite(gif) {
    error.value = ''
    favorites.value = isFavorite(gif.slug)
      ? favorites.value.filter((f) => f.slug !== gif.slug)
      : [...favorites.value, gif]
    try {
      await meApi.setPrefs({ gif_favorites: favorites.value })
    } catch (e) {
      error.value = e?.response?.data?.detail || 'Не удалось сохранить избранное'
    }
  }

  // Избранное с УЖЕ ОТПРАВЛЕННОГО сообщения (ChatThread.vue, наведение на картинку,
  // как в Discord) — у Message нет slug/title/thumb Klipy, только сама ссылка на CDN,
  // поэтому дедуп здесь по url, а не по slug (пикер продолжает работать по slug выше,
  // это отдельная, непересекающаяся пара функций).
  function isFavoriteUrl(url) {
    return favorites.value.some((f) => f.url === url)
  }

  async function toggleFavoriteByUrl(url) {
    error.value = ''
    favorites.value = isFavoriteUrl(url)
      ? favorites.value.filter((f) => f.url !== url)
      : [...favorites.value, { slug: '', title: '', thumb_url: url, url, width: 0, height: 0 }]
    try {
      await meApi.setPrefs({ gif_favorites: favorites.value })
    } catch (e) {
      error.value = e?.response?.data?.detail || 'Не удалось сохранить избранное'
    }
  }

  async function categories() {
    if (memoCats && Date.now() - memoCatsAt < MEMO_MS) return memoCats
    const { data } = await messengerApi.gifCategories()
    memoCats = data.categories || []
    memoCatsAt = Date.now()
    return memoCats
  }

  async function trending(page = 1) {
    if (page === 1 && memoTrend && Date.now() - memoTrendAt < MEMO_MS) return memoTrend
    const { data } = await messengerApi.gifTrending(page)
    if (page === 1) {
      memoTrend = data
      memoTrendAt = Date.now()
    }
    return data
  }

  // Программа: положить пикер в кэш картинок заранее — избранное, обложки категорий и
  // «В тренде» (просьба 17.10.2026: «зашёл в раздел гифок — они уже подгружены»). Окно
  // программы в приватном режиме, и без этого каждый запуск начинался с пустого пикера.
  // Один раз за вход; неудача — попробуем при следующем открытии мессенджера.
  async function warmup() {
    if (warmed || !isDesktopApp()) return
    warmed = true
    try {
      await load()
      const [cats, trend] = await Promise.all([
        categories().catch(() => []), trending(1).catch(() => ({})),
      ])
      prefetchImages([
        ...favorites.value.map((f) => f.thumb_url || f.url),
        ...cats.map((c) => c.preview_url),
        ...((trend && trend.items) || []).map((it) => it.thumb_url),
      ])
    } catch {
      warmed = false
    }
  }

  // Выход из аккаунта = смена владельца вкладки: избранное прежнего человека не должно ни
  // показаться следующему, ни уехать к нему в настройки первым же нажатием ⭐ (список
  // сохраняется ЦЕЛИКОМ из памяти). Зовёт `auth.logout`.
  function reset() {
    favorites.value = []
    loaded.value = false
    error.value = ''
    warmed = false
  }

  async function search(q, page = 1) {
    const { data } = await messengerApi.gifSearch(q, page)
    return data
  }

  return { favorites, error, isFavorite, toggleFavorite, isFavoriteUrl, toggleFavoriteByUrl,
           load, categories, trending, search, warmup, reset }
})
