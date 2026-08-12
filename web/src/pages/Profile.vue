<script setup>
// Profile — «Профиль», по образцу Discord (3.6): слева редактор (аватарка, цвет плашки,
// заготовки под эффекты/рамку, стиль никнейма), посередине — ЖИВОЙ предпросмотр, который
// и есть та самая карточка, что видят другие (PeerProfileCard editable — общий компонент
// с «чужим» профилем в мессенджере, см. его докстринг). Ниже — уведомления, как раньше.
//
// ⚠️ (живой отзыв Влада) Раньше цвет/шрифт сохранялись МГНОВЕННО по клику, «о себе» —
// своей кнопкой, заметка — по blur без кнопки вовсе (и терялась при быстром уходе со
// вкладки). Три разных механизма сохранения на одной странице — путано и хрупко. Теперь
// ВСЁ — черновик до явного нажатия «Сохранить» здесь (цвет/шрифт — локально в этом
// файле, «о себе»/заметка — внутри PeerProfileCard через commit()/discard(), см. её
// докстринг). Уход со страницы с несохранённым черновиком — предупреждение с выбором
// «Сохранить»/«Отменить» (onBeforeRouteLeave ниже), а не молчаливая потеря правок.
import { ref, computed, watch } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { useProfileStore } from '@/stores/profile'
import { useLocaleStore } from '@/stores/locale'
import { useConfirm } from '@/composables/useConfirm'
import { PRESETS } from '@/theme/palette'
import { NAME_FONTS } from '@/config/nameFonts'
import { NAME_EFFECTS, nameDecor } from '@/config/nameEffects'
import { useAuthStore } from '@/stores/auth'
import Card from '@/components/ui/Card.vue'
import AppButton from '@/components/ui/AppButton.vue'
import NotificationsInbox from '@/components/NotificationsInbox.vue'
import PeerProfileCard from '@/components/messenger/PeerProfileCard.vue'
import NameStyleDialog from '@/components/NameStyleDialog.vue'
import { Camera, Check, Film, Sparkles, SquareDashed } from '@lucide/vue'

const auth = useAuthStore()
const profile = useProfileStore()
const locale = useLocaleStore()
const { confirm } = useConfirm()
const cardRef = ref(null)

// ── Черновик цвета/шрифта — синхронизируется с сохранённым значением, ПОКА человек
// его не тронул (см. lastSynced*: приход prefs с сервера ПОСЛЕ монтирования страницы
// не должен затирать уже начатую правку, но обязан подхватиться, если правки ещё нет). ──
const draftColor = ref(profile.color)
const draftFont = ref(profile.font)
const draftEffect = ref(profile.effect)
const draftNameColor = ref(profile.nameColor)
let lastSyncedColor = profile.color
let lastSyncedFont = profile.font
let lastSyncedEffect = profile.effect
let lastSyncedNameColor = profile.nameColor
watch(() => profile.color, (v) => { if (draftColor.value === lastSyncedColor) draftColor.value = v; lastSyncedColor = v })
watch(() => profile.font, (v) => { if (draftFont.value === lastSyncedFont) draftFont.value = v; lastSyncedFont = v })
watch(() => profile.effect, (v) => { if (draftEffect.value === lastSyncedEffect) draftEffect.value = v; lastSyncedEffect = v })
watch(() => profile.nameColor, (v) => { if (draftNameColor.value === lastSyncedNameColor) draftNameColor.value = v; lastSyncedNameColor = v })

function pickColor(id) { draftColor.value = id }

const colorFontDirty = computed(() =>
  draftColor.value !== profile.color
  || draftFont.value !== profile.font
  || draftEffect.value !== profile.effect
  || draftNameColor.value !== profile.nameColor)
const dirty = computed(() => colorFontDirty.value || !!cardRef.value?.isDirty)
const saving = ref(false)

async function saveAll() {
  saving.value = true
  try {
    const tasks = []
    // ⚠️ Отправляем ВСЕ четыре поля черновика, а не только цвет со шрифтом: эффект и
    // цвет имени входят в colorFontDirty, и стоило их забыть — кнопка «Сохранить»
    // оставалась гореть навсегда, потому что черновик так и не догонял сохранённое.
    if (colorFontDirty.value) {
      tasks.push(profile.saveProfile({
        color: draftColor.value, font: draftFont.value,
        effect: draftEffect.value, nameColor: draftNameColor.value,
      }))
    }
    if (cardRef.value?.isDirty) tasks.push(cardRef.value.commit())
    await Promise.all(tasks)
  } finally { saving.value = false }
}
function discardAll() {
  draftColor.value = profile.color
  draftFont.value = profile.font
  draftEffect.value = profile.effect          //по той же причине, что и в saveAll: иначе
  draftNameColor.value = profile.nameColor    //«Отменить» не снимало бы признак правки
  cardRef.value?.discard()
}

// Уход со страницы (клик по сайдбару/другому пункту меню) с несохранённым черновиком —
// та же плашка выбора «Сохранить»/«Отменить», что и везде в приложении (useConfirm), а
// не молчаливая потеря правок. Закрытие мимо кнопок (Esc/клик по фону) = «Отменить»,
// как и у любого другого confirm() в проекте — переход не блокируем в любом случае:
// плашка отвечает КАК уйти, а не блокирует уход целиком.
onBeforeRouteLeave(async () => {
  if (!dirty.value) return true
  const save = await confirm({
    title: locale.t('profile.unsavedTitle', 'Есть несохранённые изменения'),
    message: locale.t('profile.unsavedMessage', 'Сохранить их перед уходом со страницы?'),
    okText: locale.t('profile.saveAndLeave', 'Сохранить'),
    cancelText: locale.t('profile.discardAndLeave', 'Отменить'),
  })
  if (save) await saveAll()
  else discardAll()
  return true
})

// ── Стиль никнейма ───────────────────────────────────────────────────────────────────
// Сам выбор переехал в отдельный диалог (NameStyleDialog): шрифтов стало девятнадцать и
// добавились восемь эффектов, свёрнутым списком 3.6.1 это уже не показать. На странице
// осталась одна строка-кнопка с ТЕКУЩИМ стилем, написанная им же.
const styleDialogOpen = ref(false)
const currentFont = computed(() => NAME_FONTS.find((f) => f.id === draftFont.value) || NAME_FONTS[0])
const currentEffect = computed(() => NAME_EFFECTS.find((e) => e.id === draftEffect.value) || NAME_EFFECTS[0])
// Строка-кнопка показывает ЧЕРНОВИК, а не сохранённое: иначе примерка стиля не была бы
// видна до нажатия «Сохранить» — ровно та же причина, по которой карточка-предпросмотр
// получает colorOverride/fontOverride.
const draftDecor = computed(() => nameDecor({
  name_font: draftFont.value, name_effect: draftEffect.value,
  name_color: draftNameColor.value, profile_color: draftColor.value,
}))
//`label` у шрифта и эффекта — геттер, сам ходящий в словарь (см. nameFonts/nameEffects),
//поэтому подпись переводится вместе с языком без отдельного t() здесь.
const styleSummary = computed(() => {
  //«Обычный» эффект в подпись не выносим: он и есть отсутствие эффекта, и строка
  //«Классический · Обычный» сообщала бы читателю ровно ничего сверх названия шрифта.
  const font = currentFont.value.label
  return currentEffect.value.id ? `${font} · ${currentEffect.value.label}` : font
})
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

        <!-- Баннер вынесен и сюда, не только на карандаш поверх карточки: карандаш
             находят не все, а строка в редакторе слева стоит там же, где остальные
             настройки внешнего вида. -->
        <Card :title="locale.t('profile.bannerSection', 'Баннер')" :subtitle="locale.t('profile.bannerHint', 'Гифка вместо цветной полосы вверху карточки')" :pad="true">
          <div class="flex flex-col gap-2">
            <button type="button" @click="cardRef?.openBannerPicker()"
                    class="flex w-full items-center gap-3 rounded-lg border border-border2 bg-card2 px-3 py-2.5 text-left hover:border-accent">
              <span class="grid size-9 shrink-0 place-items-center rounded-full bg-accent-glow text-accent">
                <Film class="size-4" />
              </span>
              <span class="text-sm font-medium text-text">{{ locale.t('profile.pickBannerGif', 'Гифка на баннер профиля') }}</span>
            </button>
            <button v-if="profile.banner" type="button" @click="cardRef?.removeBanner()"
                    class="self-start text-xs text-text3 hover:text-red">
              {{ locale.t('profile.removeBanner', 'Убрать баннер') }}
            </button>
          </div>
        </Card>

        <Card :title="locale.t('profile.color', 'Цвет профиля')" :subtitle="locale.t('profile.colorHint', 'Фон плашки с вашим именем')">
          <div class="flex flex-wrap gap-2">
            <button v-for="p in PRESETS" :key="p.id" type="button" @click="pickColor(p.id)"
                    :title="locale.t(`theme.preset.${p.id}`, p.name)" :aria-label="locale.t(`theme.preset.${p.id}`, p.name)"
                    class="grid size-8 place-items-center rounded-full ring-offset-2 ring-offset-[var(--gb-card)] transition-transform hover:scale-110"
                    :class="draftColor === p.id ? 'ring-2 ring-accent' : ''"
                    :style="{ background: p.accent }">
              <Check v-if="draftColor === p.id" class="size-3.5 text-white" />
            </button>
          </div>
        </Card>

        <!-- Стиль имени: шрифт + эффект + цвет живут в ОДНОМ диалоге (3.7, просьба Влада
             с макетом Discord). Здесь остаётся одна строка-кнопка с текущим стилем,
             написанная им же — раньше тут был свёрнутый список из семи шрифтов, а с
             девятнадцатью шрифтами и восемью эффектами он занял бы всю колонку. -->
        <Card :title="locale.t('profile.nameFont', 'Стиль имени')" :subtitle="locale.t('profile.nameFontHint', 'Видно всем — в сообщениях и в вашем профиле')">
          <button type="button" @click="styleDialogOpen = true"
                  class="flex w-full items-center justify-between gap-2 rounded-lg border border-border2 px-3 py-2 text-left transition-colors hover:border-accent hover:bg-bg2">
            <span class="min-w-0 flex-1">
              <span class="block truncate text-base text-text" v-bind="draftDecor">
                {{ auth.user?.name || currentFont.label }}
              </span>
              <span class="text-[11px] text-text3">{{ styleSummary }}</span>
            </span>
            <span class="grid size-7 shrink-0 place-items-center rounded-lg bg-accent-glow text-accent">
              <Sparkles class="size-4" />
            </span>
          </button>
        </Card>

        <!-- Заготовка — специально НЕ кнопка (без @click, без hover-состояния перехода
             в другой цвет): заказчик попросил оставить заголовок, но НЕ делать его
             кликабельным, рамки аватарки — отдельная задача на будущее. -->
        <Card :pad="true">
          <div class="flex items-center justify-between gap-2 py-1">
            <span class="flex items-center gap-2 text-sm font-medium text-text3">
              <SquareDashed class="size-4" />{{ locale.t('profile.frame', 'Рамка аватарки') }}
            </span>
            <span class="rounded-full bg-bg2 px-2 py-0.5 text-[11px] font-semibold text-text3">
              {{ locale.t('profile.soon', 'Скоро') }}
            </span>
          </div>
        </Card>
      </div>

      <!-- Центр: живой предпросмотр (= карточка, которую видят другие). Цвет/шрифт —
           ЧЕРНОВИК (colorOverride/fontOverride): смена видна здесь сразу, не дожидаясь
           «Сохранить» — иначе предпросмотр не был бы предпросмотром. -->
      <div class="lg:order-2">
        <PeerProfileCard ref="cardRef" editable
                         :color-override="draftColor" :font-override="draftFont"
                         :effect-override="draftEffect" :name-color-override="draftNameColor" />
      </div>
    </div>

    <!-- Общая панель сохранения — ОДНА на весь профиль (цвет/шрифт/«о себе»/заметка),
         видна только когда есть что сохранять. -->
    <div v-if="dirty" class="sticky bottom-3 z-20 flex items-center justify-between gap-3 rounded-xl border border-accent/40 bg-card px-4 py-3 shadow-card">
      <span class="text-sm text-text2">{{ locale.t('profile.unsavedBar', 'Есть несохранённые изменения') }}</span>
      <div class="flex gap-2">
        <AppButton variant="ghost" size="sm" :disabled="saving" @click="discardAll">
          {{ locale.t('profile.discardAndLeave', 'Отменить') }}
        </AppButton>
        <AppButton variant="green" size="sm" :disabled="saving" @click="saveAll">
          {{ saving ? locale.t('profile.saving', 'Сохранение…') : locale.t('common.save') }}
        </AppButton>
      </div>
    </div>

    <Card :title="locale.t('settings.notifications', 'Уведомления')" :subtitle="locale.t('profile.notificationsHint', 'Оценки и изменения расписания')">
      <NotificationsInbox />
    </Card>

    <!-- Диалог правит ЧЕРНОВИК (v-model), сохраняет его общая кнопка выше — сам он на
         сервер не ходит, как и остальные три редактора на этой странице. -->
    <NameStyleDialog v-if="styleDialogOpen"
                     v-model:font="draftFont" v-model:effect="draftEffect"
                     v-model:color="draftNameColor" @close="styleDialogOpen = false" />
  </div>
</template>
