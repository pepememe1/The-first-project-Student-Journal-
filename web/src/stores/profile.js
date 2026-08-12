/**
 * profile.js — личный профиль пользователя (аватар, «о себе», цвет плашки, стиль никнейма).
 *
 * Аватарка и остальные публичные поля хранятся в синхронизируемых prefs (`prefs.avatar` =
 * data:URL обрезанной картинки 256×256 JPEG), как и тема: роумятся между устройствами через
 * /me/prefs + синк, работают офлайн, без отдельных эндпоинтов/таблиц.
 * ⚠️ load() кэширует результат (`loaded`) на время жизни вкладки — при смене аккаунта в ТОЙ ЖЕ
 * вкладке (SPA не перезагружается) без явного reset() он вернул бы данные ПРЕЖНЕГО аккаунта.
 * Поэтому reset() ОБЯЗАН вызываться из auth.logout()/clearSession(), как и у messenger/vector.
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
// ⚠️ Ходим через endpoints.js, а НЕ через голый `api.post('/me/prefs')`.
// Тот файл в своём же докстринге обещает держать ВЕСЬ контракт с сервером, и это
// обещание должно быть правдой: иначе смена адреса правится в пяти местах вместо
// одного, а карта связей репозитория просто не видит такой вызов — для неё эта
// страница с сервером не разговаривает вовсе.
import { meApi } from '@/api/endpoints'
import { PRESETS } from '@/theme/palette'

// Лимит «О себе» — тот же, что режет сервер (routers/me.py::_MAX_BIO_CHARS).
export const BIO_LIMIT = 400

export const useProfileStore = defineStore('profile', () => {
  const avatar = ref('')          // data:URL или ''
  const bio = ref('')             // «О себе» — видно другим в карточке профиля
  const color = ref('')           // id пресета палитры для плашки профиля ('' — стандарт)
  const font = ref('')            // §5.4: id стиля никнейма (@/config/nameFonts) — тоже видно другим
  const effect = ref('')          // 3.7: id эффекта имени (@/config/nameEffects) — публичный, как шрифт
  const nameColor = ref('')       // 3.7: id пресета палитры для эффекта; '' — «как цвет профиля»
  // ⚠️ Собственный id пользователя. Лежит ИМЕННО здесь, а не в auth: после входа сервер
  // отдаёт только логин/роль/ФИО, поэтому «визитка» в auth.user id не содержит и никогда
  // не содержала. Всё, что адресует человека путём (`/messenger/users/{id}/…`), без него
  // работать не может — на своей же карточке профиля так молча не сохранялась личная
  // заметка. Берём из /me/prefs (см. докстринг get_prefs на сервере): страница профиля
  // и так его дёргает, и уже выданные сессии чинятся без перезахода.
  const userId = ref('')
  const saving = ref(false)
  let loaded = false

  async function load(force = false) {
    if (loaded && !force) return
    try {
      const { data } = await meApi.getPrefs()
      const p = data?.prefs || {}
      userId.value = data?.user_id || ''
      avatar.value = p.avatar || ''
      bio.value = p.bio || ''
      color.value = p.profile_color || ''
      font.value = p.name_font || ''
      effect.value = p.name_effect || ''
      nameColor.value = p.name_color || ''
      // Живой запрос: новый аккаунт (или ещё не выбравший цвет) получает СЛУЧАЙНЫЙ цвет
      // из текущего пула палитры, а не всегда «стандарт ВСГУТУ». Выбирается ОДИН раз и
      // тут же сохраняется на сервер — дальше это обычный prefs.profile_color, roaming
      // между устройствами тем же путём, что и ручной выбор в палитре Profile.vue.
      if (!color.value) {
        const pick = PRESETS[Math.floor(Math.random() * PRESETS.length)]
        if (pick) await saveProfile({ color: pick.id })
      }
      // ⚠️ loaded — ТОЛЬКО при успехе (тот же класс бага, что у избранных гифок): внутри
      // десктопа запрос идёт через локальный прокси на бой, и на самый первый заход
      // сразу после холодного старта токен может быть ещё не готов — раньше один
      // неудачный запрос НАВСЕГДА (до перезапуска) оставлял профиль пустым/дефолтным.
      loaded = true
    } catch { /* офлайн — оставляем что есть, попробуем снова при следующем load() */ }
  }

  // dataUrl='' — удалить аватарку. Локально применяем сразу, на сервер — best-effort.
  async function save(dataUrl) {
    avatar.value = dataUrl || ''
    saving.value = true
    try { await meApi.setPrefs({ avatar: avatar.value }) }
    catch { /* офлайн — уедет позже с синком */ }
    finally { saving.value = false }
  }

  // Публичная часть профиля: «О себе» + цвет плашки + стиль никнейма. Обрезаем и здесь
  // (сервер режет тоже) — только те поля, что реально переданы, чтобы клик по одной
  // палитре не перезаписывал ещё не сохранённый черновик «О себе» в соседней карточке.
  async function saveProfile({ bio: newBio, color: newColor, font: newFont,
                               effect: newEffect, nameColor: newNameColor } = {}) {
    const payload = {}
    if (newBio != null) { bio.value = String(newBio).slice(0, BIO_LIMIT); payload.bio = bio.value }
    if (newColor != null) { color.value = newColor; payload.profile_color = color.value }
    if (newFont != null) { font.value = newFont; payload.name_font = font.value }
    if (newEffect != null) { effect.value = newEffect; payload.name_effect = effect.value }
    if (newNameColor != null) { nameColor.value = newNameColor; payload.name_color = nameColor.value }
    saving.value = true
    try { await meApi.setPrefs(payload) }
    catch { /* офлайн — уедет позже с синком */ }
    finally { saving.value = false }
  }

  // Вызывается из auth.logout()/clearSession() — без этого профиль ПРЕДЫДУЩЕГО
  // аккаунта (аватар/«о себе»/цвет/шрифт) оставался в памяти store до первого
  // load(force=true), а `loaded` не сбрасывался — значит следующий вход в ТОЙ ЖЕ
  // вкладке (SPA не перезагружается) вообще не перезапрашивал prefs и молча
  // показывал чужие данные как свои (тот же класс бага, что уже был у Вектора).
  function reset() {
    avatar.value = ''
    bio.value = ''
    color.value = ''
    font.value = ''
    effect.value = ''
    nameColor.value = ''
    userId.value = ''   //иначе заметка следующего вошедшего ушла бы под id предыдущего
    loaded = false
  }

  return { avatar, bio, color, font, effect, nameColor, userId, saving, load, save, saveProfile, reset }
})
