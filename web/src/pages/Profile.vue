<script setup>
// Profile — «Профиль», по образцу Discord (3.6): слева редактор (аватарка, цвет плашки,
// заготовки под эффекты/рамку, стиль никнейма), посередине — ЖИВОЙ предпросмотр, который
// и есть та самая карточка, что видят другие (PeerProfileCard editable — общий компонент
// с «чужим» профилем в мессенджере, см. его докстринг). Ниже — уведомления, как раньше.
import { ref } from 'vue'
import { useProfileStore } from '@/stores/profile'
import { useLocaleStore } from '@/stores/locale'
import { PRESETS } from '@/theme/palette'
import { NAME_FONTS } from '@/config/nameFonts'
import { useAuthStore } from '@/stores/auth'
import Card from '@/components/ui/Card.vue'
import NotificationsInbox from '@/components/NotificationsInbox.vue'
import PeerProfileCard from '@/components/messenger/PeerProfileCard.vue'
import { Camera, Check, Sparkles, SquareDashed } from '@lucide/vue'

const auth = useAuthStore()
const profile = useProfileStore()
const locale = useLocaleStore()
const cardRef = ref(null)

async function pickColor(id) { await profile.saveProfile({ color: id }) }
async function pickFont(id) { await profile.saveProfile({ font: id }) }
</script>

<template>
  <div class="space-y-6">
    <div class="grid grid-cols-1 gap-5 lg:grid-cols-[280px_1fr]">
      <!-- Левая колонка: редактор -->
      <div class="space-y-4 lg:order-1">
        <Card :title="locale.t('profile.avatarSection', 'Аватарка')" :pad="true">
          <button type="button" @click="cardRef?.openAvatarEditor()"
                  class="flex w-full items-center gap-3 rounded-lg border border-border2 bg-card2 px-3 py-2.5 text-left hover:border-accent">
            <span class="grid size-9 shrink-0 place-items-center rounded-full bg-accent-glow text-accent">
              <Camera class="size-4" />
            </span>
            <span class="text-sm font-medium text-text">{{ locale.t('profile.editAvatar', 'Изменить аватарку') }}</span>
          </button>
        </Card>

        <Card :title="locale.t('profile.color', 'Цвет профиля')" :subtitle="locale.t('profile.colorHint', 'Фон плашки с вашим именем')">
          <div class="flex flex-wrap gap-2">
            <button v-for="p in PRESETS" :key="p.id" type="button" @click="pickColor(p.id)"
                    :title="locale.t(`theme.preset.${p.id}`, p.name)" :aria-label="locale.t(`theme.preset.${p.id}`, p.name)"
                    class="grid size-8 place-items-center rounded-full ring-offset-2 ring-offset-[var(--gb-card)] transition-transform hover:scale-110"
                    :class="profile.color === p.id ? 'ring-2 ring-accent' : ''"
                    :style="{ background: p.accent }">
              <Check v-if="profile.color === p.id" class="size-3.5 text-white" />
            </button>
          </div>
        </Card>

        <!-- Стиль никнейма: список шрифтов, КАЖДЫЙ пункт написан ЭТИМ ЖЕ шрифтом текущим
             именем пользователя — так видно результат ДО выбора, не после сохранения. -->
        <Card :title="locale.t('profile.nameFont', 'Стиль никнейма')" :subtitle="locale.t('profile.nameFontHint', 'Видно всем — в сообщениях и в вашем профиле')">
          <div class="space-y-1">
            <button v-for="f in NAME_FONTS" :key="f.id" type="button" @click="pickFont(f.id)"
                    class="flex w-full items-center justify-between gap-2 rounded-lg border px-3 py-2 text-left transition-colors"
                    :class="profile.font === f.id ? 'border-accent bg-accent-glow' : 'border-border2 hover:bg-bg2'">
              <span class="min-w-0 flex-1">
                <span class="block truncate text-base text-text" :style="{ fontFamily: f.family }">
                  {{ auth.user?.name || f.label }}
                </span>
                <span class="text-[11px] text-text3">{{ f.label }}</span>
              </span>
              <Check v-if="profile.font === f.id" class="size-4 shrink-0 text-accent" />
            </button>
          </div>
        </Card>

        <!-- Заготовки — специально НЕ кнопки (без @click, без hover-состояния перехода
             в другой цвет): заказчик попросил оставить заголовки, но НЕ делать их
             кликабельными, эффекты/рамки — отдельная задача на будущее. -->
        <Card :pad="true">
          <div class="flex items-center justify-between gap-2 py-1">
            <span class="flex items-center gap-2 text-sm font-medium text-text3">
              <Sparkles class="size-4" />{{ locale.t('profile.effects', 'Эффекты профиля') }}
            </span>
            <span class="rounded-full bg-bg2 px-2 py-0.5 text-[11px] font-semibold text-text3">
              {{ locale.t('profile.soon', 'Скоро') }}
            </span>
          </div>
          <div class="mt-1 flex items-center justify-between gap-2 border-t border-border py-1 pt-2">
            <span class="flex items-center gap-2 text-sm font-medium text-text3">
              <SquareDashed class="size-4" />{{ locale.t('profile.frame', 'Рамка аватарки') }}
            </span>
            <span class="rounded-full bg-bg2 px-2 py-0.5 text-[11px] font-semibold text-text3">
              {{ locale.t('profile.soon', 'Скоро') }}
            </span>
          </div>
        </Card>
      </div>

      <!-- Центр: живой предпросмотр (= карточка, которую видят другие) -->
      <div class="lg:order-2">
        <PeerProfileCard ref="cardRef" editable />
      </div>
    </div>

    <Card :title="locale.t('settings.notifications', 'Уведомления')" :subtitle="locale.t('profile.notificationsHint', 'Оценки и изменения расписания')">
      <NotificationsInbox />
    </Card>
  </div>
</template>
