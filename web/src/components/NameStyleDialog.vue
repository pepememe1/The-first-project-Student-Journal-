<script setup>
// NameStyleDialog — «Изменение стиля отображаемого имени» (3.7, прямая просьба Влада с
// присланным макетом Discord: «при нажатии на эффекты ника в профиле надо такую менюшку»).
//
// Слева — три сетки выбора (шрифт, эффект, цвет), справа — ЖИВОЙ образец: карточка профиля
// и строка сообщения, то есть ровно те два места, где имя чаще всего и видят другие.
// Образец рисуется той же функцией `nameDecor()`, что и настоящие имена по всему
// приложению, — иначе «предпросмотр» показывал бы одно, а собеседники видели другое.
//
// ⚠️ Диалог НИЧЕГО не сохраняет сам. Он работает с v-model:-черновиком, а пишет на сервер
// общая кнопка «Сохранить» в Profile.vue — тот же порядок, что у цвета плашки, «о себе» и
// заметки (см. докстринг Profile.vue: три разных механизма сохранения на одной странице
// уже приводили к потерянным правкам). «Отмена» здесь возвращает то, с чем диалог открыли.
//
// ⚠️ Плитка каждого шрифта написана ЭТИМ ЖЕ шрифтом и РЕАЛЬНЫМ именем человека, а не
// образцом «Gg» из макета: у кириллицы и латиницы разный характер, и по «Gg» невозможно
// понять, как будет выглядеть «Иванов Пётр» (в макете Discord это и не нужно — там имена
// чаще латиницей). Цена — при открытии диалога браузер тянет все 19 файлов шрифтов
// (~1.1 МБ, кэшируется), поэтому они и подрезаны до латиницы с кириллицей при сборке.
import { ref, computed, watch } from 'vue'
import { X, Check } from '@lucide/vue'
import { useLocaleStore } from '@/stores/locale'
import { useAuthStore } from '@/stores/auth'
import { useProfileStore } from '@/stores/profile'
import { NAME_FONTS, NAME_FONT_GROUPS } from '@/config/nameFonts'
import { NAME_EFFECTS, nameDecor } from '@/config/nameEffects'
import { PRESETS, profilePlate } from '@/theme/palette'
import { roleLabel } from '@/config/roles'
import Avatar from '@/components/ui/Avatar.vue'
import AppButton from '@/components/ui/AppButton.vue'

const props = defineProps({
  font: { type: String, default: '' },
  effect: { type: String, default: '' },
  color: { type: String, default: '' },        // '' — «как цвет профиля»
})
const emit = defineEmits(['update:font', 'update:effect', 'update:color', 'close'])

const locale = useLocaleStore()
const auth = useAuthStore()
const profile = useProfileStore()

// Локальный черновик: пока диалог открыт, правки живут здесь и уходят наружу только по
// «Готово». Закрытие крестиком/фоном = отказ, поэтому родитель не должен видеть промежуточные
// значения — иначе «примерил и передумал» оставляло бы страницу грязной.
const draft = ref({ font: props.font, effect: props.effect, color: props.color })
watch(() => [props.font, props.effect, props.color], ([f, e, c]) => {
  draft.value = { font: f, effect: e, color: c }
})

const displayName = computed(() => auth.user?.name || auth.user?.login || 'Иванов Пётр')

// Что показывать в образцах — черновик поверх остальной публичной части своего профиля.
const previewUser = computed(() => ({
  name_font: draft.value.font,
  name_effect: draft.value.effect,
  name_color: draft.value.color,
  profile_color: profile.color,
}))
const previewDecor = computed(() => nameDecor(previewUser.value))
const plate = computed(() => profilePlate(profile.color))

// Плитка эффекта — тот же эффект на коротком слове, но ВСЕГДА обычным шрифтом: иначе
// «Глитч» + «Радуга» сливались бы в кашу, и было бы не понять, что именно выбираешь.
function effectDecor(id) {
  return nameDecor({ name_effect: id, name_color: draft.value.color, profile_color: profile.color })
}
function fontsOf(groupId) {
  return NAME_FONTS.filter((f) => f.group === groupId)
}
// Цвет применим не ко всякому эффекту: у «Обычного» его нет вовсе, радуга цвет
// игнорирует (см. nameEffects.js). Палитру в этих случаях гасим, а не прячем — исчезающий
// на клик блок читается как поломка.
const colorUsed = computed(() => (NAME_EFFECTS.find((e) => e.id === draft.value.effect) || {}).usesColor === true)

function apply() {
  emit('update:font', draft.value.font)
  emit('update:effect', draft.value.effect)
  emit('update:color', draft.value.color)
  emit('close')
}
</script>

<template>
  <div class="fixed inset-0 z-50 grid place-items-center p-3 sm:p-4" style="background: var(--gb-overlay)"
       @click.self="emit('close')">
    <div class="flex max-h-[90vh] w-full max-w-4xl flex-col overflow-hidden rounded-xl border border-border2 bg-card shadow-card">
      <!-- Шапка -->
      <div class="flex items-center justify-between gap-3 border-b border-border px-5 py-3.5">
        <h2 class="font-title text-lg font-bold text-text">
          {{ locale.t('nameStyle.title', 'Изменение стиля отображаемого имени') }}
        </h2>
        <button type="button" @click="emit('close')" :aria-label="locale.t('common.close')"
                class="grid size-8 shrink-0 place-items-center rounded-lg text-text3 hover:bg-bg2 hover:text-text">
          <X class="size-5" />
        </button>
      </div>

      <div class="grid min-h-0 flex-1 grid-cols-1 gap-5 overflow-y-auto p-5 lg:grid-cols-[1fr_320px]">
        <!-- ЛЕВО: выбор -->
        <div class="min-w-0 space-y-5">
          <!-- Шрифты, по группам -->
          <section>
            <p class="mb-2 text-xs font-semibold uppercase tracking-wide text-text3">
              {{ locale.t('nameStyle.fontSection', 'Выбор шрифта') }}
            </p>
            <div v-for="g in NAME_FONT_GROUPS" :key="g.id" class="mb-3 last:mb-0">
              <p class="mb-1.5 text-[11px] text-text3">{{ g.label }}</p>
              <div class="grid grid-cols-2 gap-2 sm:grid-cols-3">
                <button v-for="f in fontsOf(g.id)" :key="f.id" type="button" @click="draft.font = f.id"
                        class="min-w-0 rounded-lg border px-3 py-2 text-left transition-colors"
                        :class="draft.font === f.id ? 'border-accent bg-accent-glow' : 'border-border2 hover:bg-bg2'">
                  <span class="block truncate text-[15px] leading-tight text-text" :style="{ fontFamily: f.family }">
                    {{ displayName }}
                  </span>
                  <span class="mt-0.5 block truncate text-[11px] text-text3">{{ f.label }}</span>
                </button>
              </div>
            </div>
          </section>

          <!-- Эффекты -->
          <section>
            <p class="mb-2 text-xs font-semibold uppercase tracking-wide text-text3">
              {{ locale.t('nameStyle.effectSection', 'Выбор эффекта') }}
            </p>
            <div class="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <button v-for="e in NAME_EFFECTS" :key="e.id" type="button" @click="draft.effect = e.id"
                      class="min-w-0 rounded-lg border px-3 py-2.5 text-center transition-colors"
                      :class="draft.effect === e.id ? 'border-accent bg-accent-glow' : 'border-border2 hover:bg-bg2'">
                <span class="block truncate text-[15px] font-semibold leading-tight text-text" v-bind="effectDecor(e.id)">
                  {{ e.label }}
                </span>
              </button>
            </div>
          </section>

          <!-- Цвет -->
          <section>
            <p class="mb-2 text-xs font-semibold uppercase tracking-wide text-text3">
              {{ locale.t('nameStyle.colorSection', 'Выбор цвета') }}
            </p>
            <div class="flex flex-wrap items-center gap-2" :class="colorUsed ? '' : 'pointer-events-none opacity-40'">
              <!-- «Как цвет профиля» — отдельная плитка, а не отсутствие выбора: так видно,
                   что цвет вообще-то задан, просто наследуется от плашки. -->
              <button type="button" @click="draft.color = ''"
                      :title="locale.t('nameStyle.colorInherit', 'Как цвет профиля')"
                      class="grid size-8 place-items-center rounded-full border-2 border-dashed transition-transform hover:scale-110"
                      :class="draft.color === '' ? 'border-accent' : 'border-border2'"
                      :style="{ background: plate }">
                <Check v-if="draft.color === ''" class="size-3.5 text-white" />
              </button>
              <button v-for="p in PRESETS" :key="p.id" type="button" @click="draft.color = p.id"
                      :title="locale.t(`theme.preset.${p.id}`, p.name)" :aria-label="locale.t(`theme.preset.${p.id}`, p.name)"
                      class="grid size-8 place-items-center rounded-full ring-offset-2 ring-offset-[var(--gb-card)] transition-transform hover:scale-110"
                      :class="draft.color === p.id ? 'ring-2 ring-accent' : ''"
                      :style="{ background: p.accent }">
                <Check v-if="draft.color === p.id" class="size-3.5 text-white" />
              </button>
            </div>
            <p v-if="!colorUsed" class="mt-1.5 text-[11px] text-text3">
              {{ locale.t('nameStyle.colorNotUsed', 'Выбранный эффект цвет не использует') }}
            </p>
          </section>
        </div>

        <!-- ПРАВО: живой образец — карточка профиля и сообщение в чате -->
        <div class="min-w-0 space-y-3">
          <p class="text-xs font-semibold uppercase tracking-wide text-text3">
            {{ locale.t('nameStyle.preview', 'Предпросмотр') }}
          </p>
          <div class="overflow-hidden rounded-xl border border-border2 bg-card2">
            <div class="h-14" :style="{ background: plate }" />
            <div class="-mt-7 px-4 pb-4">
              <div class="inline-block rounded-full ring-4 ring-card2">
                <Avatar :src="profile.avatar" :name="displayName" :role="auth.role" :color="plate" :size="56" />
              </div>
              <p class="mt-2 truncate font-title text-lg font-extrabold text-text" v-bind="previewDecor">
                {{ displayName }}
              </p>
              <p class="truncate text-xs text-text3">
                <span v-if="auth.user?.login">@{{ auth.user.login }} · </span>{{ roleLabel(auth.role) }}
              </p>
            </div>
          </div>

          <div class="rounded-xl border border-border2 bg-card2 p-3">
            <div class="flex gap-2.5">
              <Avatar :src="profile.avatar" :name="displayName" :role="auth.role" :color="plate" :size="32" />
              <div class="min-w-0">
                <p class="truncate text-sm font-semibold text-text" v-bind="previewDecor">{{ displayName }}</p>
                <p class="text-sm text-text2">{{ locale.t('nameStyle.previewMessage', 'Так ваше имя увидят в чате.') }}</p>
              </div>
            </div>
          </div>

          <p class="text-[11px] leading-snug text-text3">
            {{ locale.t('nameStyle.note', 'Шрифт, эффект и цвет имени видят все — в сообщениях, списке чатов и вашем профиле. Изменения применятся после сохранения профиля.') }}
          </p>
        </div>
      </div>

      <!-- Низ -->
      <div class="flex items-center justify-end gap-2 border-t border-border px-5 py-3">
        <AppButton variant="ghost" size="sm" @click="emit('close')">{{ locale.t('common.cancel', 'Отмена') }}</AppButton>
        <AppButton variant="green" size="sm" @click="apply">{{ locale.t('common.done', 'Готово') }}</AppButton>
      </div>
    </div>
  </div>
</template>
