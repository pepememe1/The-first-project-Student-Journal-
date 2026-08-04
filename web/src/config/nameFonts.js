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
 */
import { useLocaleStore } from '@/stores/locale'

export const NAME_FONTS = [
  { id: '', family: '',
    get label() { return useLocaleStore().t('nameFont.default', 'Обычный') } },
  { id: 'unbounded', family: "'GB Nick Unbounded', var(--font-title)",
    get label() { return useLocaleStore().t('nameFont.unbounded', 'Жирный') } },
  { id: 'comfortaa', family: "'GB Nick Comfortaa', var(--font-title)",
    get label() { return useLocaleStore().t('nameFont.comfortaa', 'Округлый') } },
  { id: 'caveat', family: "'GB Nick Caveat', cursive",
    get label() { return useLocaleStore().t('nameFont.caveat', 'От руки') } },
  { id: 'marckscript', family: "'GB Nick Marck', cursive",
    get label() { return useLocaleStore().t('nameFont.marckscript', 'Каллиграфия') } },
  { id: 'ptserif', family: "'GB Nick PT Serif', serif",
    get label() { return useLocaleStore().t('nameFont.ptserif', 'Классический') } },
  { id: 'ptmono', family: "'GB Nick PT Mono', monospace",
    get label() { return useLocaleStore().t('nameFont.ptmono', 'Моноширинный') } },
]

const BY_ID = Object.fromEntries(NAME_FONTS.map((f) => [f.id, f]))

/** CSS font-family для id стиля никнейма. Неизвестный/пустой id → '' (наследуется обычный). */
export function nameFontFamily(id) {
  return BY_ID[id || '']?.family || ''
}
