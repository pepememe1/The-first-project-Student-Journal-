<script setup>
// Profile — «Профиль»: плашка (аватарка + ФИО на выбранном цвете), «О себе» и уведомления.
// Персональные настройки (оформление, биометрия, озвучка) — в отдельной вкладке «Настройки».
// Цвет плашки и «О себе» ПУБЛИЧНЫ: их видят другие в карточке профиля из мессенджера.
import { computed, onMounted, ref, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useProfileStore, BIO_LIMIT } from '@/stores/profile'
import { PRESETS, profilePlate } from '@/theme/palette'
import Card from '@/components/ui/Card.vue'
import NotificationsInbox from '@/components/NotificationsInbox.vue'
import AvatarCropper from '@/components/AvatarCropper.vue'
import { Camera, Check } from '@lucide/vue'

const auth = useAuthStore()
const profile = useProfileStore()
const ROLE = { student: 'Студент', teacher: 'Преподаватель', admin: 'Администратор' }
const initial = computed(() => (auth.user?.name || '?').trim().charAt(0).toUpperCase())

const editing = ref(false)
const draftBio = ref('')

onMounted(async () => {
  await profile.load()
  draftBio.value = profile.bio
})
// Профиль мог долиться после монтирования — подхватываем текст, пока его не правят.
watch(() => profile.bio, (v) => { if (!dirty.value) draftBio.value = v })

const left = computed(() => BIO_LIMIT - draftBio.value.length)
const dirty = computed(() => draftBio.value !== profile.bio)
// Цвет плашки: id пресета → hex (общий хелпер, см. palette.profilePlate).
const plateColor = computed(() => profilePlate(profile.color))

async function onSave(dataUrl) {
  editing.value = false
  await profile.save(dataUrl)
}
async function saveBio() { await profile.saveProfile({ bio: draftBio.value }) }
async function pickColor(id) { await profile.saveProfile({ color: id }) }
</script>

<template>
  <div class="space-y-6">
    <!-- Плашка профиля: цвет выбирает сам пользователь, его видят и другие. -->
    <Card>
      <div class="-m-5 mb-0 flex items-center gap-4 rounded-t-xl p-5"
           :style="{ background: plateColor }">
        <button type="button" @click="editing = true"
                class="group relative size-16 shrink-0 overflow-hidden rounded-full ring-2 ring-white/60"
                title="Изменить аватарку">
          <img v-if="profile.avatar" :src="profile.avatar" alt="Аватарка"
               class="size-full object-cover" />
          <span v-else class="grid size-full place-items-center bg-white/20 text-2xl font-extrabold text-white">{{ initial }}</span>
          <span class="absolute inset-0 grid place-items-center bg-black/40 opacity-0 transition-opacity group-hover:opacity-100">
            <Camera class="size-5 text-white" />
          </span>
        </button>
        <div class="min-w-0">
          <p class="truncate font-title text-xl font-extrabold text-white">{{ auth.user?.name }}</p>
          <p class="truncate text-sm text-white/80">{{ ROLE[auth.role] }} · {{ auth.user?.login }}</p>
        </div>
      </div>
      <p v-if="profile.bio" class="mt-4 whitespace-pre-wrap text-sm text-text2">{{ profile.bio }}</p>
    </Card>

    <!-- О себе -->
    <Card title="О себе" subtitle="Короткий текст — его видят другие в вашем профиле">
      <textarea v-model="draftBio" :maxlength="BIO_LIMIT" rows="3"
                placeholder="Например: куратор группы К-24, веду сети и базы данных."
                class="w-full resize-none rounded-lg border border-border2 bg-card2 px-3 py-2 text-sm text-text outline-none focus:border-accent focus:bg-card" />
      <div class="mt-2 flex items-center gap-3">
        <span class="text-xs" :class="left <= 20 ? 'text-red' : 'text-text3'">
          Осталось символов: {{ left }}
        </span>
        <button type="button" @click="saveBio" :disabled="!dirty || profile.saving"
                class="ml-auto rounded-lg bg-accent px-4 py-1.5 text-sm font-semibold text-white hover:bg-accent2 disabled:opacity-50">
          {{ profile.saving ? 'Сохранение…' : 'Сохранить' }}
        </button>
      </div>
    </Card>

    <!-- Цвет плашки — те же пресеты, что и у темы оформления -->
    <Card title="Цвет профиля" subtitle="Фон плашки с вашим именем">
      <div class="flex flex-wrap gap-2">
        <button v-for="p in PRESETS" :key="p.id" type="button" @click="pickColor(p.id)"
                :title="p.name" :aria-label="p.name"
                class="grid size-9 place-items-center rounded-full ring-offset-2 ring-offset-[var(--gb-card)] transition-transform hover:scale-110"
                :class="profile.color === p.id ? 'ring-2 ring-accent' : ''"
                :style="{ background: p.accent }">
          <Check v-if="profile.color === p.id" class="size-4 text-white" />
        </button>
      </div>
    </Card>

    <!-- Уведомления (оценки и изменения расписания). -->
    <Card title="Уведомления" subtitle="Оценки и изменения расписания">
      <NotificationsInbox />
    </Card>

    <AvatarCropper v-if="editing" :current="profile.avatar" @save="onSave" @close="editing = false" />
  </div>
</template>
