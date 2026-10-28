// locales.js — какие языки есть в интерфейсе. Отдельно от самих словарей: его читают
// экран входа и стор языка, а тянуть ради списка из трёх строк все словари незачем.

export const LOCALES = [
  //Флаг рисует components/ui/FlagIcon.vue по code: эмодзи-флаг тянул на экран входа весь
  //шрифт Twemoji (466 КБ). Новый язык — новая ветка там же.
  { code: 'ru', name: 'Русский', english: 'Russian' },
  { code: 'en', name: 'English', english: 'English' },
  { code: 'zh', name: '中文', english: 'Chinese' },
]

export const DEFAULT_LOCALE = 'ru'
