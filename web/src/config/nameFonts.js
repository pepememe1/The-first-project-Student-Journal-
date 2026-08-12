/**
 * nameFonts.js — §5.4 «стиль никнейма»: ЕДИНЫЙ список шрифтов для отображаемого имени.
 *
 * id должны совпадать 1:1 с server/app/routers/me.py::NAME_FONTS (сервер валидирует их
 * там же при сохранении — второй список на клиенте без проверки означал бы, что
 * подделанный запрос мимо UI мог бы записать произвольную строку). font-family — из
 * @font-face в web/src/style.css (см. tools/build_nickname_fonts.py про сборку и
 * проверку кириллицы). '' — «без стиля», обычный шрифт интерфейса.
 *
 * `label` — геттер (та же причина, что у status.js: реактивность к языку без смены формы
 * модуля).
 *
 * 3.7: список вырос с 7 до 19 (просьба Влада). `group` делит их на смысловые ряды в
 * диалоге выбора — 19 плиток подряд без деления читаются как свалка. Порядок групп и
 * порядок внутри группы = порядок в сетке, поэтому новые шрифты дописывать В СВОЮ группу,
 * а не в конец файла.
 */
import { useLocaleStore } from '@/stores/locale'

export const NAME_FONTS = [
  { id: '', family: '', group: 'basic',
    get label() { return useLocaleStore().t('nameFont.default', 'Обычный') } },

  // — Строгие: годятся куда угодно, включая официальную переписку —————————————
  { id: 'unbounded', family: "'GB Nick Unbounded', var(--font-title)", group: 'basic',
    get label() { return useLocaleStore().t('nameFont.unbounded', 'Жирный') } },
  { id: 'comfortaa', family: "'GB Nick Comfortaa', var(--font-title)", group: 'basic',
    get label() { return useLocaleStore().t('nameFont.comfortaa', 'Округлый') } },
  { id: 'oswald', family: "'GB Nick Oswald', var(--font-title)", group: 'basic',
    get label() { return useLocaleStore().t('nameFont.oswald', 'Узкий') } },
  { id: 'ptserif', family: "'GB Nick PT Serif', serif", group: 'basic',
    get label() { return useLocaleStore().t('nameFont.ptserif', 'Классический') } },
  { id: 'ptmono', family: "'GB Nick PT Mono', monospace", group: 'basic',
    get label() { return useLocaleStore().t('nameFont.ptmono', 'Моноширинный') } },
  { id: 'yeseva', family: "'GB Nick Yeseva', serif", group: 'basic',
    get label() { return useLocaleStore().t('nameFont.yeseva', 'Винтажный') } },

  // — Рукописные ——————————————————————————————————————————————————————————————
  { id: 'caveat', family: "'GB Nick Caveat', cursive", group: 'hand',
    get label() { return useLocaleStore().t('nameFont.caveat', 'От руки') } },
  { id: 'marckscript', family: "'GB Nick Marck', cursive", group: 'hand',
    get label() { return useLocaleStore().t('nameFont.marckscript', 'Каллиграфия') } },
  { id: 'pacifico', family: "'GB Nick Pacifico', cursive", group: 'hand',
    get label() { return useLocaleStore().t('nameFont.pacifico', 'Ретро') } },
  { id: 'lobster', family: "'GB Nick Lobster', cursive", group: 'hand',
    get label() { return useLocaleStore().t('nameFont.lobster', 'Вывеска') } },

  // — Характерные: техно, славянский, пиксель ————————————————————————————————
  { id: 'russo', family: "'GB Nick Russo', var(--font-title)", group: 'display',
    get label() { return useLocaleStore().t('nameFont.russo', 'Техно') } },
  { id: 'tektur', family: "'GB Nick Tektur', var(--font-title)", group: 'display',
    get label() { return useLocaleStore().t('nameFont.tektur', 'Гранёный') } },
  { id: 'ruslan', family: "'GB Nick Ruslan', serif", group: 'display',
    get label() { return useLocaleStore().t('nameFont.ruslan', 'Славянский') } },
  { id: 'pixel', family: "'GB Nick Pixel', monospace", group: 'display',
    get label() { return useLocaleStore().t('nameFont.pixel', 'Пиксельный') } },

  // — Озорные: рисованные, для тех, кто хочет выделиться ——————————————————————
  { id: 'glitch', family: "'GB Nick Glitch', var(--font-title)", group: 'fun',
    get label() { return useLocaleStore().t('nameFont.glitch', 'Глитч') } },
  { id: 'moonrocks', family: "'GB Nick Moonrocks', var(--font-title)", group: 'fun',
    get label() { return useLocaleStore().t('nameFont.moonrocks', 'Космос') } },
  { id: 'bubbles', family: "'GB Nick Bubbles', var(--font-title)", group: 'fun',
    get label() { return useLocaleStore().t('nameFont.bubbles', 'Пузыри') } },
  { id: 'wetpaint', family: "'GB Nick WetPaint', var(--font-title)", group: 'fun',
    get label() { return useLocaleStore().t('nameFont.wetpaint', 'Краска') } },
]

/** Порядок групп в диалоге + их заголовки (label — геттер, как у самих шрифтов). */
export const NAME_FONT_GROUPS = [
  { id: 'basic', get label() { return useLocaleStore().t('nameFont.groupBasic', 'Строгие') } },
  { id: 'hand', get label() { return useLocaleStore().t('nameFont.groupHand', 'Рукописные') } },
  { id: 'display', get label() { return useLocaleStore().t('nameFont.groupDisplay', 'Характерные') } },
  { id: 'fun', get label() { return useLocaleStore().t('nameFont.groupFun', 'Озорные') } },
]

const BY_ID = Object.fromEntries(NAME_FONTS.map((f) => [f.id, f]))

/** CSS font-family для id стиля никнейма. Неизвестный/пустой id → '' (наследуется обычный). */
export function nameFontFamily(id) {
  return BY_ID[id || '']?.family || ''
}
