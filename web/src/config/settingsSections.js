/**
 * settingsSections.js — ЕДИНЫЙ состав «Настроек»: категории и подкатегории.
 *
 * ━━ ЗАЧЕМ ОТДЕЛЬНЫМ ФАЙЛОМ ━━
 * Один и тот же состав нужен ТРЁМ потребителям: рельсу категорий на ПК, списку
 * категорий на телефоне (двухуровневый, как в Discord) и выпадающему списку
 * подкатегорий с прокруткой к нужному месту. Держать его в разметке страницы значило
 * бы три копии, которые обязаны разойтись: добавили настройку — забыли в двух.
 *
 * ⚠️ Категории ОБЩИЕ ДЛЯ ВСЕХ РОЛЕЙ (студент, преподаватель, админ, родитель). Роль
 * решает только видимость отдельных пунктов — через `role` у категории или подкатегории.
 * Свой набор на каждую роль означал бы четыре списка вместо одного.
 *
 * ⚠️ `id` подкатегории — это ЯКОРЬ в разметке (`id="set-<id>"`). Переименовал здесь —
 * переименуй и там, иначе переход по подкатегории тихо никуда не проскроллит: ошибки
 * не будет, просто ничего не произойдёт, и понять причину со стороны нельзя.
 */
import {
  User, Palette, Bell, AudioLines, GraduationCap, ShieldCheck, UserCog, Info,
} from '@lucide/vue'

/**
 * @typedef {Object} Sub
 * @property {string} id     якорь (`set-<id>` в разметке)
 * @property {string} i18n   ключ перевода
 * @property {string} label  запасной русский текст
 * @property {string} [role] показывать только этой роли
 */

export const SETTINGS_CATS = [
  {
    id: 'profile',
    icon: User,
    i18n: 'nav.profile',
    label: 'Профиль',
    subs: [
      { id: 'avatar', i18n: 'profile.avatarSection', label: 'Аватарка' },
      { id: 'banner', i18n: 'profile.bannerSection', label: 'Баннер' },
      { id: 'color', i18n: 'profile.color', label: 'Цвет профиля' },
      { id: 'namefont', i18n: 'profile.nameFont', label: 'Стиль имени' },
      { id: 'achievements', i18n: 'achievements.title', label: 'Достижения' },
    ],
  },
  {
    id: 'appearance',
    icon: Palette,
    i18n: 'settings.catAppearance',
    label: 'Внешний вид',
    subs: [
      { id: 'theme', i18n: 'settings.appearance', label: 'Оформление' },
      { id: 'language', i18n: 'settings.language', label: 'Язык интерфейса' },
    ],
  },
  {
    id: 'notifications',
    icon: Bell,
    i18n: 'settings.notifications',
    label: 'Уведомления',
    subs: [
      { id: 'notify', i18n: 'settings.notifications', label: 'Что присылать' },
    ],
  },
  {
    id: 'voice',
    icon: AudioLines,
    i18n: 'settings.catVoice',
    label: 'Голос и звук',
    subs: [
      { id: 'tts', i18n: 'settings.tts', label: 'Озвучка Вектора' },
      { id: 'mic', i18n: 'settings.voice', label: 'Голосовой ввод' },
    ],
  },
  {
    id: 'teaching',
    icon: GraduationCap,
    i18n: 'settings.catTeaching',
    label: 'Оценивание',
    role: 'teacher',
    subs: [
      { id: 'scale', i18n: 'settings.gradingScale', label: 'Шкала оценивания' },
    ],
  },
  {
    id: 'security',
    icon: ShieldCheck,
    i18n: 'settings.catSecurity',
    label: 'Безопасность',
    subs: [
      { id: 'mfa', i18n: 'settings.mfa', label: 'Второй фактор входа' },
      { id: 'biometric', i18n: 'settings.biometric', label: 'Вход по биометрии' },
    ],
  },
  {
    id: 'account',
    icon: UserCog,
    i18n: 'settings.account',
    label: 'Аккаунт',
    subs: [
      { id: 'logout', i18n: 'nav.logout', label: 'Выход' },
    ],
  },
  {
    id: 'about',
    icon: Info,
    i18n: 'settings.catAbout',
    label: 'О программе',
    subs: [
      { id: 'version', i18n: 'settings.appVersion', label: 'Версия приложения' },
      { id: 'legal', i18n: 'settings.legal', label: 'Документы' },
    ],
  },
]

/** Категории, доступные роли. */
export function catsForRole(role) {
  return SETTINGS_CATS.filter((c) => !c.role || c.role === role)
}
