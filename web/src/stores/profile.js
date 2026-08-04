/**
 * profile.js — личный профиль пользователя (пока — аватарка).
 *
 * Аватарка хранится в синхронизируемых prefs (`prefs.avatar` = data:URL обрезанной
 * картинки 256×256 JPEG), как и тема: роумится между устройствами через /me/prefs + синк,
 * работает офлайн, без отдельных эндпоинтов/таблиц. load() при отсутствии аватарки ставит
 * '' — поэтому чужая (от прошлого аккаунта) не «залипает».
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/api/client'

// Лимит «О себе» — тот же, что режет сервер (routers/me.py::_MAX_BIO_CHARS).
export const BIO_LIMIT = 400

export const useProfileStore = defineStore('profile', () => {
  const avatar = ref('')          // data:URL или ''
  const bio = ref('')             // «О себе» — видно другим в карточке профиля
  const color = ref('')           // id пресета палитры для плашки профиля ('' — стандарт)
  const font = ref('')            // §5.4: id стиля никнейма (@/config/nameFonts) — тоже видно другим
  const saving = ref(false)
  let loaded = false

  async function load(force = false) {
    if (loaded && !force) return
    loaded = true
    try {
      const { data } = await api.get('/me/prefs')
      const p = data?.prefs || {}
      avatar.value = p.avatar || ''
      bio.value = p.bio || ''
      color.value = p.profile_color || ''
      font.value = p.name_font || ''
    } catch { /* офлайн — оставляем что есть */ }
  }

  // dataUrl='' — удалить аватарку. Локально применяем сразу, на сервер — best-effort.
  async function save(dataUrl) {
    avatar.value = dataUrl || ''
    saving.value = true
    try { await api.post('/me/prefs', { avatar: avatar.value }) }
    catch { /* офлайн — уедет позже с синком */ }
    finally { saving.value = false }
  }

  // Публичная часть профиля: «О себе» + цвет плашки + стиль никнейма. Обрезаем и здесь
  // (сервер режет тоже) — только те поля, что реально переданы, чтобы клик по одной
  // палитре не перезаписывал ещё не сохранённый черновик «О себе» в соседней карточке.
  async function saveProfile({ bio: newBio, color: newColor, font: newFont } = {}) {
    const payload = {}
    if (newBio != null) { bio.value = String(newBio).slice(0, BIO_LIMIT); payload.bio = bio.value }
    if (newColor != null) { color.value = newColor; payload.profile_color = color.value }
    if (newFont != null) { font.value = newFont; payload.name_font = font.value }
    saving.value = true
    try { await api.post('/me/prefs', payload) }
    catch { /* офлайн — уедет позже с синком */ }
    finally { saving.value = false }
  }

  return { avatar, bio, color, font, saving, load, save, saveProfile }
})
