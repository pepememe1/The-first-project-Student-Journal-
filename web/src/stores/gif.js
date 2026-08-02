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

export const useGifStore = defineStore('gif', () => {
  const favorites = ref([])
  const loaded = ref(false)
  const error = ref('')

  async function load() {
    if (loaded.value) return
    loaded.value = true
    try {
      const { data } = await meApi.getPrefs()
      favorites.value = data?.prefs?.gif_favorites || []
    } catch { /* избранное — дополнение к пикеру, без него GIF всё равно работают */ }
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
    const { data } = await messengerApi.gifCategories()
    return data.categories || []
  }

  async function trending(page = 1) {
    const { data } = await messengerApi.gifTrending(page)
    return data
  }

  async function search(q, page = 1) {
    const { data } = await messengerApi.gifSearch(q, page)
    return data
  }

  return { favorites, error, isFavorite, toggleFavorite, isFavoriteUrl, toggleFavoriteByUrl,
           load, categories, trending, search }
})
