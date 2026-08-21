<script setup>
// PeerProfileCard — Discord-style карточка профиля (§5.4). ЕДИНАЯ реализация для ДВУХ
// контекстов, чтобы не разъезжались («о себе» и заметка должны выглядеть и вести себя
// одинаково, кто бы ни смотрел):
//   • editable=true  — СВОЙ профиль (Profile.vue): аватарка/«О себе» редактируются прямо
//     здесь, карточка сама читает useProfileStore — родителю передавать draft-значения не
//     нужно, живой предпросмотр получается сам собой (карточка И ЕСТЬ то, что видят другие).
//   • editable=false — ЧУЖОЙ профиль (PeerProfileModal, из мессенджера): данные приходят
//     готовым объектом (`peerData`, если он уже есть у вызывающего, например activePeer) или
//     подгружаются по `userId` через уже существующий, но раньше нигде не используемый
//     GET /web/messenger/users/{id}/profile.
// Заметка (§5.4 «заметка… видна только нам», Discord «Notes») — ОДИНАКОВО работает в ОБОИХ
// режимах: это всегда «моя личная запись про этого человека», и про самого себя тоже
// (памятка себе на своей же карточке — так в ТЗ, отдельно не выпиливаем).
// ⚠️ (живой отзыв Влада) «О себе» и заметка раньше сохранялись КАЖДАЯ ПО-СВОЕМУ — «о
// себе» отдельной кнопкой прямо тут, заметка ПО BLUR без единой кнопки вовсе (и терялась
// при уходе со вкладки, если blur не успевал). Обе САМИ по себе больше НЕ сохраняют —
// черновик копится здесь, а сохраняет ОБЩАЯ кнопка в Profile.vue через `commit()`
// (defineExpose ниже), одним действием со сменой цвета/шрифта. Компонент editable=false
// (чужой профиль) этого не касается — там ни «о себе», ни заметка не редактируются.
import { ref, computed, onMounted, watch } from 'vue'
import { Camera, Send, Pencil, ImageIcon, Film, Trash2 } from '@lucide/vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useProfileStore, BIO_LIMIT } from '@/stores/profile'
import { useMessengerStore } from '@/stores/messenger'
import { useLocaleStore } from '@/stores/locale'
import { profilePlate } from '@/theme/palette'
import { nameDecor } from '@/config/nameEffects'
import { roleLabel } from '@/config/roles'
import { messengerApi } from '@/api/endpoints'
import Avatar from '@/components/ui/Avatar.vue'
import AvatarCropper from '@/components/AvatarCropper.vue'
import GifPicker from '@/components/messenger/GifPicker.vue'
import { useToast } from '@/composables/useToast'

const props = defineProps({
  editable: { type: Boolean, default: false },
  userId: { type: String, default: '' },
  peerData: { type: Object, default: null },
  // Черновики цвета/шрифта живут В Profile.vue (там же, где сами пикеры) — картинка
  // предпросмотра обязана их видеть ДО сохранения, иначе смена цвета «не работала бы
  // на глаз», пока не нажата общая кнопка. null — использовать сохранённое значение стора.
  colorOverride: { type: String, default: null },
  fontOverride: { type: String, default: null },
  effectOverride: { type: String, default: null },
  nameColorOverride: { type: String, default: null },
})
const emit = defineEmits(['messaged'])

const auth = useAuthStore()
const profile = useProfileStore()
const messenger = useMessengerStore()
const locale = useLocaleStore()
const router = useRouter()
const toast = useToast()

// ── Данные карточки ──────────────────────────────────────────────────────────────────
const fetched = ref(null)
async function loadPeer() {
  if (props.editable || props.peerData || !props.userId) return
  try {
    const { data } = await messengerApi.profile(props.userId)
    fetched.value = data.profile
  } catch { fetched.value = null }
}
onMounted(loadPeer)
watch(() => props.userId, loadPeer)

// ⚠️ Свой id берём из стора профиля (он приходит в /me/prefs), а НЕ из auth.user —
// «визитка» после входа состоит из логина, роли и ФИО, id в ней нет и не было. Пока
// карточка читала `auth.user?.id`, свой id был пустой строкой ВСЕГДА, и всё, что
// адресует человека путём, тихо выключалось: заметка про себя не загружалась и не
// сохранялась (запрос не уходил вовсе — см. ранний выход по `!id` ниже), а кнопка
// «Написать» показывалась на собственном профиле, потому что isSelf не мог стать true.
const myUserId = computed(() => profile.userId)
// Стор грузится один раз за вкладку и обычно уже наполнен нижней панелью сайдбара; зовём
// на всякий случай и здесь — вызов идемпотентный (второго запроса не будет), а во
// встроенном режиме окна программы сайдбара нет вовсе и наполнить его больше некому.
// Не только для editable: без своего id и на ЧУЖОЙ карточке нельзя понять, что открыт
// собственный профиль, — тогда там появляется кнопка «Написать» самому себе.
onMounted(() => profile.load())

// «Кого показываем» — три источника по приоритету: свой профиль (реактивно к сторам,
// живой предпросмотр без сохранения) → готовые данные от вызывающего → подгруженные сами.
const shown = computed(() => {
  if (props.editable) {
    return {
      id: myUserId.value, full_name: auth.user?.name || '', role: auth.role,
      group_name: auth.user?.group_name || '', avatar: profile.avatar, bio: profile.bio,
      profile_banner: profile.banner,
      profile_color: props.colorOverride ?? profile.color,
      name_font: props.fontOverride ?? profile.font,
      name_effect: props.effectOverride ?? profile.effect,
      name_color: props.nameColorOverride ?? profile.nameColor,
      login: auth.user?.login || '',
      subjects: auth.user?.subjects || [],
    }
  }
  return props.peerData || fetched.value || {}
})
const isSelf = computed(() => !!shown.value.id && shown.value.id === myUserId.value)

const plate = computed(() => profilePlate(shown.value.profile_color))
// Имя рисуем ЕДИНОЙ nameDecor (шрифт + эффект + цвет), а не одним лишь семейством
// шрифта: иначе выбранный эффект был бы виден в диалоге выбора и нигде больше.
const nameDecoration = computed(() => nameDecor(shown.value))
const metaLine = computed(() => {
  const u = shown.value
  const parts = [roleLabel(u.role)]
  if (u.role === 'teacher' && (u.subjects || []).length) parts.push(u.subjects.join(', '))
  else if (u.group_name) parts.push(u.group_name)
  return parts.filter(Boolean).join(' · ')
})

// ── Баннер карточки ──────────────────────────────────────────────────────────────────
// Гифка с Klipy вместо однотонной плашки. Цвет профиля она НЕ отменяет: он по-прежнему
// красит подложку значка роли и участвует в оформлении имени — гифка ложится только на
// верхнюю полосу. Поэтому «убрать баннер» возвращает цвет, а не оставляет пустоту.
const bannerUrl = computed(() => shown.value.profile_banner || '')

// Фуллскрин-просмотр аватарки/баннера ЧУЖОГО профиля по клику (Влад): полноценный файл
// без круглой/квадратной обрезки. '' — закрыт. В своём (editable) профиле клик по картинке
// уже занят редактированием, поэтому лупа только на чужой карточке.
const lightbox = ref('')

// ── Аватарка и баннер: выбор источника (только editable) ─────────────────────────────
const editingAvatar = ref(false)
const avatarMenuOpen = ref(false)
// '' | 'avatar' | 'banner' — один и тот же пикер Klipy на два места назначения.
const gifPickerFor = ref('')

// Сохраняем СРАЗУ, а не черновиком под общую кнопку внизу страницы (как цвет и шрифт).
// Причина: и картинку, и гифку выбирают в отдельном окне, которое закрывается по выбору,
// — «выбрал и закрылось» человек читает как «применено». Копить это в черновике значит
// однажды потерять выбор, уйдя со страницы мимо кнопки.
async function applyAvatar(src) {
  const r = await profile.save(src)
  if (!r.ok) reportSaveFailure(r)
}
async function applyBanner(url) {
  const before = profile.banner
  const r = await profile.saveProfile({ banner: url })
  if (!r.ok) {
    profile.banner = before      // на экране не должно висеть то, чего нет на сервере
    reportSaveFailure(r)
  }
}
function reportSaveFailure(r) {
  toast.error(r.offline
    ? locale.t('profile.mediaOffline', 'Нет связи с сервером — изменение не сохранено.')
    : (r.detail || locale.t('profile.mediaFailed', 'Не удалось сохранить изображение.')))
}

async function onSaveAvatar(dataUrl) {
  editingAvatar.value = false
  await applyAvatar(dataUrl)
}
function onGifPicked(item) {
  const target = gifPickerFor.value
  gifPickerFor.value = ''
  if (!item) return
  // ⚠️ Берём `url` (это gif, см. gif_service._simplify), а НЕ лёгкое превью `thumb_url`,
  // хотя аватарка рисуется размером 32–80 px и превью хватило бы по пикселям. Причина:
  // превью — webp, и АНИМИРОВАН ли он, проверить не удалось (ключ Klipy живёт только на
  // сервере, а доступа к нему в момент правки не было). Неподвижная «гифка-аватарка» —
  // это молчаливый отказ фичи, а лишние килобайты — всего лишь лишние килобайты.
  // Подтвердится, что превью анимировано, — здесь меняется одно слово.
  const src = item.url || item.thumb_url || ''
  if (target === 'avatar') applyAvatar(src)
  else if (target === 'banner') applyBanner(src)
}

// ── «О себе» (только editable — у чужого профиля это чистый текст) ──────────────────
const draftBio = ref('')
const bioDirty = computed(() => props.editable && draftBio.value !== profile.bio)
onMounted(() => { draftBio.value = profile.bio })
watch(() => profile.bio, (v) => { if (!bioDirty.value) draftBio.value = v })

// ── Заметка (в ОБОИХ режимах — всегда про shown.value.id) ───────────────────────────
const note = ref('')
const noteSaved = ref('')
const noteDirty = computed(() => note.value !== noteSaved.value)
async function loadNote() {
  if (!shown.value.id) return
  // ⚠️ Свой id теперь приезжает вместе с prefs, то есть ПОСЛЕ монтирования карточки —
  // значит загрузка заметки может застать человека уже печатающим. Набранный текст в
  // этом случае не трогаем: перезаписать его серверным ответом означало бы стереть
  // правку у того, кто просто начал печатать быстрее, чем ответила сеть.
  const hadDraft = noteDirty.value
  try {
    const { data } = await messengerApi.note(shown.value.id)
    noteSaved.value = data.text || ''
    if (!hadDraft) note.value = noteSaved.value
  } catch { if (!hadDraft) { note.value = ''; noteSaved.value = '' } }
}
onMounted(loadNote)
watch(() => shown.value.id, loadNote)
async function saveNote() {
  const id = shown.value.id
  if (!id) return
  try {
    const { data } = await messengerApi.saveNote(id, note.value)
    noteSaved.value = data.text || ''
  } catch { /* офлайн-мессенджер не бывает, но не роняем интерфейс */ }
}
// ⚠️ В editable-режиме заметка НЕ сохраняется сама по blur — это раньше и было
// причиной «написал, при перезаходе пропало» (уход со страницы кликом по сайдбару не
// гарантированно успевает довести blur→запрос до конца, а второй клик — уже не на этом
// компоненте). Теперь она копится черновиком и уходит ТОЛЬКО через commit() ниже, одним
// действием с «о себе»/цветом/шрифтом. В НЕ-editable режиме (чужой профиль в модалке —
// там нет общей кнопки сохранения) поведение прежнее: реальный blur сохраняет сразу.
function onNoteBlur() { if (!props.editable && noteDirty.value) saveNote() }

// ── Общее сохранение (вызывается ИЗВНЕ, из Profile.vue) ─────────────────────────────
const isDirty = computed(() => bioDirty.value || (props.editable && noteDirty.value))
async function commit() {
  const tasks = []
  if (bioDirty.value) tasks.push(profile.saveProfile({ bio: draftBio.value }))
  if (props.editable && noteDirty.value) tasks.push(saveNote())
  await Promise.all(tasks)
}
function discard() {
  draftBio.value = profile.bio
  note.value = noteSaved.value
}
// Левая колонка Profile.vue ведёт в те же самые действия — теперь их два вида (картинка
// и гифка), поэтому наружу отдаём открытие МЕНЮ, а не сразу обрезалки: иначе кнопка
// «Изменить аватарку» молча означала бы «только картинку», и гифку нашли бы лишь те, кто
// догадался нажать на саму аватарку.
defineExpose({
  openAvatarEditor: () => { avatarMenuOpen.value = true },
  openBannerPicker: () => { gifPickerFor.value = 'banner' },
  removeBanner: () => applyBanner(''),
  isDirty, commit, discard,
})

// ── Кнопка «Сообщение» ────────────────────────────────────────────────────────────────
async function sendMessage() {
  if (isSelf.value) return
  await messenger.openWith({ id: shown.value.id, full_name: shown.value.full_name })
  router.push(`/${auth.role}/messages`)
  emit('messaged')
}

// Левая колонка Profile.vue дублирует вход в тот же редактор аватарки (как в Discord —
// превью-аватар и «Изменить аватарку» слева ведут в ОДИН диалог), поэтому открывать его
// нужно и СНАРУЖИ, не только кликом по самой карточке. Экспортирован ВЫШЕ, вместе с
// isDirty/commit/discard — второй defineExpose Vue тихо проигнорировал бы.
</script>

<template>
  <div class="overflow-hidden rounded-xl border border-border2 bg-card">
    <!-- Баннер: гифка, если выбрана, иначе однотонная плашка цвета профиля. -->
    <div class="relative h-20 overflow-hidden" :style="bannerUrl ? undefined : { background: plate }">
      <img v-if="bannerUrl" :src="bannerUrl" alt="" class="size-full object-cover"
           :class="{ 'cursor-zoom-in': !editable }"
           @click="!editable && (lightbox = bannerUrl)" />
      <!-- Карандаш виден ВСЕГДА, а не только при наведении: на телефоне наведения не
           существует вовсе, и подсказка «здесь можно поменять» иначе не появилась бы
           никогда. При наведении просто становится заметнее. -->
      <button v-if="editable" type="button" @click="gifPickerFor = 'banner'"
              class="absolute right-2 top-2 grid size-8 place-items-center rounded-full bg-black/45
                     text-white opacity-80 transition hover:bg-black/70 hover:opacity-100"
              :title="locale.t('profile.editBanner', 'Сменить баннер')"
              :aria-label="locale.t('profile.editBanner', 'Сменить баннер')">
        <Pencil class="size-4" />
      </button>
      <button v-if="editable && bannerUrl" type="button" @click="applyBanner('')"
              class="absolute right-11 top-2 grid size-8 place-items-center rounded-full bg-black/45
                     text-white opacity-80 transition hover:bg-black/70 hover:opacity-100"
              :title="locale.t('profile.removeBanner', 'Убрать баннер')"
              :aria-label="locale.t('profile.removeBanner', 'Убрать баннер')">
        <Trash2 class="size-4" />
      </button>
    </div>
    <div class="-mt-10 px-5 pb-5">
      <div class="group relative inline-block">
        <button v-if="editable" type="button" @click="avatarMenuOpen = !avatarMenuOpen"
                class="relative block size-20 overflow-hidden rounded-full ring-4 ring-card"
                :title="locale.t('profile.editAvatar', 'Изменить аватарку')">
          <Avatar :src="shown.avatar" :name="shown.full_name" :role="shown.role" :color="plate" :size="80" />
          <span class="absolute inset-0 grid place-items-center bg-black/40 opacity-0 transition-opacity group-hover:opacity-100">
            <Camera class="size-6 text-white" />
          </span>
        </button>
        <button v-else-if="shown.avatar" type="button" @click="lightbox = shown.avatar"
                class="block cursor-zoom-in rounded-full ring-4 ring-card"
                :title="locale.t('peerProfile.viewAvatar', 'Открыть аватарку')">
          <Avatar :src="shown.avatar" :name="shown.full_name" :role="shown.role" :color="plate" :size="80" />
        </button>
        <div v-else class="rounded-full ring-4 ring-card">
          <Avatar :src="shown.avatar" :name="shown.full_name" :role="shown.role" :color="plate" :size="80" />
        </div>

        <!-- Выбор источника аватарки. Тот же приём, что у MyStatusPicker: список плюс
             прозрачная подложка на весь экран, закрывающая его кликом мимо, — иначе на
             телефоне меню нечем закрыть, не выбрав пункт. -->
        <template v-if="editable && avatarMenuOpen">
          <div class="fixed inset-0 z-30" @click="avatarMenuOpen = false" />
          <div class="absolute left-0 top-[calc(100%+0.375rem)] z-40 w-52 overflow-hidden rounded-lg
                      border border-border2 bg-card py-1 shadow-card">
            <button type="button" class="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-text hover:bg-bg2"
                    @click="avatarMenuOpen = false; editingAvatar = true">
              <ImageIcon class="size-4 shrink-0 text-text3" />{{ locale.t('profile.avatarImage', 'Изображение') }}
            </button>
            <button type="button" class="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-text hover:bg-bg2"
                    @click="avatarMenuOpen = false; gifPickerFor = 'avatar'">
              <Film class="size-4 shrink-0 text-text3" />{{ locale.t('profile.avatarGif', 'GIF') }}
            </button>
            <button v-if="shown.avatar" type="button"
                    class="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-red hover:bg-bg2"
                    @click="avatarMenuOpen = false; applyAvatar('')">
              <Trash2 class="size-4 shrink-0" />{{ locale.t('profile.avatarRemove', 'Убрать аватарку') }}
            </button>
          </div>
        </template>
      </div>

      <div class="mt-3 flex items-start justify-between gap-3">
        <div class="min-w-0">
          <p class="truncate font-title text-xl font-extrabold text-text" v-bind="nameDecoration">
            {{ shown.full_name || '…' }}
          </p>
          <p class="truncate text-sm text-text3">
            <span v-if="shown.login">@{{ shown.login }} · </span>{{ metaLine }}
          </p>
        </div>
        <button v-if="!isSelf" type="button" @click="sendMessage"
                class="flex shrink-0 items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-sm font-semibold text-white hover:bg-accent2">
          <Send class="size-3.5" />{{ locale.t('peerProfile.message', 'Сообщение') }}
        </button>
      </div>

      <!-- О себе -->
      <div class="mt-4 rounded-lg border border-border bg-card2 p-3">
        <p class="mb-1.5 text-[11px] uppercase tracking-wide text-text3">{{ locale.t('profile.about', 'О себе') }}</p>
        <template v-if="editable">
          <textarea v-model="draftBio" :maxlength="BIO_LIMIT" rows="3"
                    :placeholder="locale.t('profile.aboutPlaceholder', 'Например: куратор группы К-24, веду сети и базы данных.')"
                    class="w-full resize-none rounded-md border border-border2 bg-card px-2.5 py-1.5 text-sm text-text outline-none focus:border-accent" />
          <div class="mt-1.5 flex items-center gap-3">
            <span class="text-xs" :class="(BIO_LIMIT - draftBio.length) <= 20 ? 'text-red' : 'text-text3'">
              {{ locale.t('profile.charsLeft', { n: BIO_LIMIT - draftBio.length }) }}
            </span>
            <!-- Своей кнопки «Сохранить» тут больше нет — сохраняет общая кнопка в
                 Profile.vue (см. commit() выше), одним действием со всем профилем. -->
          </div>
        </template>
        <p v-else class="whitespace-pre-wrap text-sm text-text2">
          {{ shown.bio || locale.t('peerProfile.noBio', 'Пока ничего не написал(а).') }}
        </p>
      </div>

      <!-- Заметка — видна только автору, в обоих режимах. -->
      <div class="mt-3 rounded-lg border border-dashed border-border2 bg-card2 p-3">
        <p class="mb-1.5 text-[11px] uppercase tracking-wide text-text3">
          {{ locale.t('peerProfile.note', 'Заметка') }}
          <span class="normal-case text-text3">— {{ locale.t('peerProfile.noteHint', 'видна только вам') }}</span>
        </p>
        <textarea v-model="note" @blur="onNoteBlur" rows="2" maxlength="300"
                  :placeholder="locale.t('peerProfile.notePlaceholder', 'Личная заметка (не видна собеседнику)')"
                  class="w-full resize-none rounded-md border border-border2 bg-card px-2.5 py-1.5 text-sm text-text outline-none focus:border-accent" />
      </div>
    </div>

    <AvatarCropper v-if="editingAvatar" :current="profile.avatar" @save="onSaveAvatar" @close="editingAvatar = false" />
    <!-- Тот же пикер Klipy, что у поля ввода в чате; здесь по центру экрана — у карточки
         профиля нет поля ввода внизу справа, к которому он приклеен в мессенджере. -->
    <GifPicker v-if="gifPickerFor" anchor="center"
               :title="gifPickerFor === 'banner'
                 ? locale.t('profile.pickBannerGif', 'Гифка на баннер профиля')
                 : locale.t('profile.pickAvatarGif', 'Гифка на аватарку')"
               @pick="onGifPicked" @close="gifPickerFor = ''" />

    <!-- Фуллскрин аватарки/баннера чужого профиля: полноценный файл без обрезки,
         клик по фону закрывает (Влад). -->
    <div v-if="lightbox" class="fixed inset-0 z-[80] grid place-items-center bg-black/80 p-4"
         @click="lightbox = ''">
      <img :src="lightbox" alt="" class="max-h-[90vh] max-w-[90vw] rounded-lg object-contain shadow-2xl" />
    </div>
  </div>
</template>
