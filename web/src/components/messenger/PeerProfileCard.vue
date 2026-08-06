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
import { ref, computed, onMounted, watch } from 'vue'
import { Camera, Send } from '@lucide/vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useProfileStore, BIO_LIMIT } from '@/stores/profile'
import { useMessengerStore } from '@/stores/messenger'
import { useLocaleStore } from '@/stores/locale'
import { profilePlate } from '@/theme/palette'
import { nameFontFamily } from '@/config/nameFonts'
import { roleLabel } from '@/config/roles'
import { messengerApi } from '@/api/endpoints'
import Avatar from '@/components/ui/Avatar.vue'
import AvatarCropper from '@/components/AvatarCropper.vue'

const props = defineProps({
  editable: { type: Boolean, default: false },
  userId: { type: String, default: '' },
  peerData: { type: Object, default: null },
})
const emit = defineEmits(['messaged'])

const auth = useAuthStore()
const profile = useProfileStore()
const messenger = useMessengerStore()
const locale = useLocaleStore()
const router = useRouter()

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

// «Кого показываем» — три источника по приоритету: свой профиль (реактивно к сторам,
// живой предпросмотр без сохранения) → готовые данные от вызывающего → подгруженные сами.
const shown = computed(() => {
  if (props.editable) {
    return {
      id: auth.user?.id || '', full_name: auth.user?.name || '', role: auth.role,
      group_name: auth.user?.group_name || '', avatar: profile.avatar, bio: profile.bio,
      profile_color: profile.color, name_font: profile.font, login: auth.user?.login || '',
      subjects: auth.user?.subjects || [],
    }
  }
  return props.peerData || fetched.value || {}
})
const myUserId = computed(() => auth.user?.id || '')
const isSelf = computed(() => !!shown.value.id && shown.value.id === myUserId.value)

const plate = computed(() => profilePlate(shown.value.profile_color))
const fontFamily = computed(() => nameFontFamily(shown.value.name_font))
const metaLine = computed(() => {
  const u = shown.value
  const parts = [roleLabel(u.role)]
  if (u.role === 'teacher' && (u.subjects || []).length) parts.push(u.subjects.join(', '))
  else if (u.group_name) parts.push(u.group_name)
  return parts.filter(Boolean).join(' · ')
})

// ── Аватарка (только editable) ───────────────────────────────────────────────────────
const editingAvatar = ref(false)
async function onSaveAvatar(dataUrl) {
  editingAvatar.value = false
  await profile.save(dataUrl)
}

// ── «О себе» (только editable — у чужого профиля это чистый текст) ──────────────────
const draftBio = ref('')
const bioDirty = computed(() => props.editable && draftBio.value !== profile.bio)
onMounted(() => { draftBio.value = profile.bio })
watch(() => profile.bio, (v) => { if (!bioDirty.value) draftBio.value = v })
async function saveBio() { await profile.saveProfile({ bio: draftBio.value }) }

// ── Заметка (в ОБОИХ режимах — всегда про shown.value.id) ───────────────────────────
const note = ref('')
const noteSaved = ref('')
const noteDirty = computed(() => note.value !== noteSaved.value)
async function loadNote() {
  if (!shown.value.id) return
  try {
    const { data } = await messengerApi.note(shown.value.id)
    note.value = data.text || ''
    noteSaved.value = note.value
  } catch { note.value = ''; noteSaved.value = '' }
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

// ── Кнопка «Сообщение» ────────────────────────────────────────────────────────────────
async function sendMessage() {
  if (isSelf.value) return
  await messenger.openWith({ id: shown.value.id, full_name: shown.value.full_name })
  router.push(`/${auth.role}/messages`)
  emit('messaged')
}

// Левая колонка Profile.vue дублирует вход в тот же редактор аватарки (как в Discord —
// превью-аватар и «Изменить аватарку» слева ведут в ОДИН диалог), поэтому открывать его
// нужно и СНАРУЖИ, не только кликом по самой карточке.
defineExpose({ openAvatarEditor: () => { editingAvatar.value = true } })
</script>

<template>
  <div class="overflow-hidden rounded-xl border border-border2 bg-card">
    <div class="h-20" :style="{ background: plate }" />
    <div class="-mt-10 px-5 pb-5">
      <div class="group relative inline-block">
        <button v-if="editable" type="button" @click="editingAvatar = true"
                class="relative block size-20 overflow-hidden rounded-full ring-4 ring-card"
                :title="locale.t('profile.editAvatar', 'Изменить аватарку')">
          <Avatar :src="shown.avatar" :name="shown.full_name" :role="shown.role" :color="plate" :size="80" />
          <span class="absolute inset-0 grid place-items-center bg-black/40 opacity-0 transition-opacity group-hover:opacity-100">
            <Camera class="size-6 text-white" />
          </span>
        </button>
        <div v-else class="rounded-full ring-4 ring-card">
          <Avatar :src="shown.avatar" :name="shown.full_name" :role="shown.role" :color="plate" :size="80" />
        </div>
      </div>

      <div class="mt-3 flex items-start justify-between gap-3">
        <div class="min-w-0">
          <p class="truncate font-title text-xl font-extrabold text-text" :style="{ fontFamily }">
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
            <button type="button" @click="saveBio" :disabled="!bioDirty || profile.saving"
                    class="ml-auto rounded-md bg-accent px-3 py-1 text-xs font-semibold text-white hover:bg-accent2 disabled:opacity-50">
              {{ profile.saving ? locale.t('profile.saving', 'Сохранение…') : locale.t('common.save') }}
            </button>
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
        <textarea v-model="note" @blur="noteDirty && saveNote()" rows="2" maxlength="300"
                  :placeholder="locale.t('peerProfile.notePlaceholder', 'Личная заметка (не видна собеседнику)')"
                  class="w-full resize-none rounded-md border border-border2 bg-card px-2.5 py-1.5 text-sm text-text outline-none focus:border-accent" />
      </div>
    </div>

    <AvatarCropper v-if="editingAvatar" :current="profile.avatar" @save="onSaveAvatar" @close="editingAvatar = false" />
  </div>
</template>
