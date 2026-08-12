/**
 * nameEffects.js — §5.4 «стиль никнейма», часть 2 (3.7): ЭФФЕКТ и ЦВЕТ отображаемого
 * имени (просьба Влада «эффекты для ника, ргб и тд», по образцу Discord).
 *
 * Три независимых поля настроек человека, и все три ПУБЛИЧНЫЕ (их видят другие в
 * мессенджере и в карточке профиля), поэтому у каждого есть список-близнец на сервере
 * (`server/app/routers/me.py`: NAME_FONTS / NAME_EFFECTS / NAME_COLORS) — проверка в UI
 * не защищает от подделанного запроса мимо UI:
 *   • prefs.name_font   — шрифт (nameFonts.js);
 *   • prefs.name_effect — эффект (здесь), CSS-классы — в web/src/style.css;
 *   • prefs.name_color  — цвет эффекта: id пресета палитры ИЛИ '' = «как цвет профиля».
 *
 * ⚠️ Цвет НЕ отдельная от палитры сущность: берём те же 16 пресетов, что и `profile_color`
 * (`theme/palette.js::PRESETS`). Свой второй список цветов означал бы, что человек красит
 * плашку профиля одной палитрой, а имя — другой, и они бы не сочетались; заодно сервер
 * валидирует оба поля одинаково. Пустое значение = наследовать цвет профиля, поэтому у
 * того, кто цвет имени не трогал, имя и плашка всегда одного цвета.
 *
 * ЕДИНАЯ точка применения — `nameDecor()` ниже. Все места, где рисуется чужое или своё
 * имя, зовут её и биндят результат целиком (`v-bind="nameDecor(...)"`), а не собирают
 * стиль руками: раньше каждое место делало `:style="{ fontFamily: nameFontFamily(x) }"`,
 * и добавление эффекта означало бы семь одинаковых правок и семь мест, где о новом
 * эффекте однажды забудут.
 */
import { useLocaleStore } from '@/stores/locale'
import { PRESETS, profilePlate } from '@/theme/palette'
import { nameFontFamily } from '@/config/nameFonts'

/**
 * Эффекты. `cls` — класс из style.css; `usesColor: false` у радуги (она и есть «все
 * цвета сразу», выбранный цвет к ней неприменим — так же и в Discord).
 */
export const NAME_EFFECTS = [
  { id: '', cls: '', usesColor: false,
    get label() { return useLocaleStore().t('nameEffect.none', 'Обычный') } },
  { id: 'solid', cls: 'gb-nfx-solid', usesColor: true,
    get label() { return useLocaleStore().t('nameEffect.solid', 'Цветной') } },
  { id: 'gradient', cls: 'gb-nfx-gradient', usesColor: true,
    get label() { return useLocaleStore().t('nameEffect.gradient', 'Градиент') } },
  { id: 'rainbow', cls: 'gb-nfx-rainbow', usesColor: false,
    get label() { return useLocaleStore().t('nameEffect.rainbow', 'Радуга') } },
  { id: 'shine', cls: 'gb-nfx-shine', usesColor: true,
    get label() { return useLocaleStore().t('nameEffect.shine', 'Блик') } },
  { id: 'neon', cls: 'gb-nfx-neon', usesColor: true,
    get label() { return useLocaleStore().t('nameEffect.neon', 'Неон') } },
  { id: 'outline', cls: 'gb-nfx-outline', usesColor: true,
    get label() { return useLocaleStore().t('nameEffect.outline', 'Контур') } },
  { id: 'highlight', cls: 'gb-nfx-highlight', usesColor: true,
    get label() { return useLocaleStore().t('nameEffect.highlight', 'Выделение') } },
]

const EFFECT_BY_ID = Object.fromEntries(NAME_EFFECTS.map((e) => [e.id, e]))
const PRESET_BY_ID = Object.fromEntries(PRESETS.map((p) => [p.id, p]))

/** Осветлённый напарник основного цвета — второй край градиента и полоса блика. */
function lighten(hex) {
  const h = String(hex || '').replace('#', '')
  if (h.length !== 6) return hex
  const mix = (v) => Math.round(v + (255 - v) * 0.42).toString(16).padStart(2, '0')
  return '#' + [0, 2, 4].map((i) => mix(parseInt(h.slice(i, i + 2), 16))).join('')
}

/**
 * Цвет имени в виде готового CSS-значения.
 * @param {string} nameColorId  prefs.name_color ('' — наследуем цвет профиля)
 * @param {string} profileColorId prefs.profile_color (тот же id пресета)
 */
export function nameColorValue(nameColorId, profileColorId) {
  return PRESET_BY_ID[nameColorId]?.accent || profilePlate(profileColorId)
}

/**
 * Класс + инлайновые переменные для ОДНОГО имени. Результат биндится целиком:
 *   <span v-bind="nameDecor(user)">{{ user.full_name }}</span>
 * Vue сливает class/style из v-bind с теми, что уже стоят на элементе, поэтому
 * существующие `truncate`/`font-bold` на месте рисования остаются в силе.
 *
 * @param {{name_font?: string, name_effect?: string, name_color?: string,
 *          profile_color?: string}} u — публичная часть профиля (ровно та, что приходит
 *          с сервера в messenger._safe_user; для себя — поля useProfileStore).
 */
export function nameDecor(u) {
  const font = u?.name_font || ''
  const effect = EFFECT_BY_ID[u?.name_effect || ''] || EFFECT_BY_ID['']
  const family = nameFontFamily(font)
  const style = {}
  if (family) style.fontFamily = family
  if (!effect.cls) return { class: '', style }

  //Переменные ставим ТОЛЬКО тем эффектам, которым цвет нужен: у радуги он ни на что не
  //влияет, и лишние инлайновые свойства на каждом имени в ленте — пустая работа.
  if (effect.usesColor) {
    const c1 = nameColorValue(u?.name_color, u?.profile_color)
    style['--gb-nc1'] = c1
    //Второй цвет производный, а не отдельная настройка: пара «цвет + его светлый
    //вариант» всегда сочетается, а два свободно выбранных цвета — почти никогда.
    style['--gb-nc2'] = c1.startsWith('#') ? lighten(c1) : 'var(--gb-accent2)'
  }
  return { class: ['gb-nfx', effect.cls], style }
}
