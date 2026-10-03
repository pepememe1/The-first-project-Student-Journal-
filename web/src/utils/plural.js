/**
 * plural.js — форма слова по числу для строк словаря.
 *
 * Значение в словаре задаёт формы через «|»: «{n} подписчик|{n} подписчика|{n} подписчиков».
 * Какую взять, решают правила ЯЗЫКА (`Intl.PluralRules`), а не наша таблица окончаний:
 * у русского три формы (1 подписчик, 2 подписчика, 5 подписчиков; 21 — снова «один»),
 * у английского две, у китайского одна. Живой прогон 01.10.2026: «502 подписчиков».
 *
 * Порядок форм в строке — как у CLDR: ru — one|few|many, en — one|other. Дробное число
 * в русском — категория `other`, ей отдаётся последняя форма («1,5 подписчика» тут не
 * встречается: считаем людей и сообщения).
 */
const ORDER = { ru: ['one', 'few', 'many'], en: ['one', 'other'] }

/** Выбрать форму из «форма1|форма2|…» по числу `n` для языка `lang`. Без «|» — как есть. */
export function pickPlural(text, n, lang) {
  if (typeof text !== 'string' || !text.includes('|')) return text
  const forms = text.split('|')
  const order = ORDER[lang] || ['other']
  let cat = 'other'
  try { cat = new Intl.PluralRules(lang).select(Number(n)) } catch { /* нет правил — последняя форма */ }
  const i = order.indexOf(cat)
  return forms[i < 0 ? forms.length - 1 : Math.min(i, forms.length - 1)]
}
