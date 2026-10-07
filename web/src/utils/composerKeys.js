// composerKeys.js — что делает клавиша в поле ввода сообщения и куда прокрутить поле.
//
// Вынесено из `ChatThread.vue` по обычной причине: решение в обработчике события без
// браузера не проверить, а ломается оно перестановкой двух условий. Здесь — чистые
// функции, их и держит `web/tests/composerKeys.test.mjs`.
//
// Правила взяты у Telegram и Discord (просьба Ярослава 05.10.2026: «бери ввод текста
// напрямую с передовых мессенджеров, иначе преимуществ в собственном мессенджере нет»):
//   • на компьютере Enter отправляет, Shift+Enter переносит строку;
//   • на телефоне Enter ПЕРЕНОСИТ строку, а отправляет кнопка — у экранной клавиатуры нет
//     Shift+Enter, и «Enter = отправить» делал многострочное сообщение невозможным вовсе;
//   • стрелка вверх в ПУСТОМ поле открывает правку своего последнего сообщения;
//   • Esc снимает то, что открыто последним: подсказку, правку, ответ.

/**
 * Действие по нажатой клавише.
 *
 * @param {{key:string, shiftKey?:boolean, ctrlKey?:boolean, metaKey?:boolean,
 *          altKey?:boolean, isComposing?:boolean, keyCode?:number}} e
 * @param {{handheld?:boolean, empty?:boolean, editing?:boolean, replying?:boolean,
 *          picker?:boolean}} ctx
 * @returns {''|'send'|'newline'|'edit-last'|'close-picker'|'cancel-edit'|'cancel-reply'}
 */
export function composerKeyAction(e, ctx = {}) {
  const ev = e || {}
  if (ev.key === 'Enter') {
    // 🔥 ИДЁТ НАБОР СОСТАВНОГО СИМВОЛА (иероглиф, буква с ударением). Этот Enter
    // подтверждает ВЫБОР ВАРИАНТА в окне ввода, а не сообщение. Без проверки китайский
    // студент отправлял бы недописанную фразу на каждом слове — у продукта есть
    // китайская локаль, и это его основной способ набора. `keyCode === 229` — то же
    // самое для движков, которые `isComposing` на keydown не выставляют (Safari).
    if (ev.isComposing || ev.keyCode === 229) return ''
    if (ev.shiftKey) return 'newline'
    // На телефоне отправляет КНОПКА. Ctrl/⌘+Enter оставлен отправкой: его нажимают
    // с подключённой клавиатуры (планшет), и там это осознанное «отправить».
    if (ctx.handheld && !(ev.ctrlKey || ev.metaKey)) return 'newline'
    return 'send'
  }
  if (ev.key === 'ArrowUp') {
    // Только в ПУСТОМ поле: в непустом стрелка двигает курсор, и перехват отнял бы у
    // человека навигацию по собственному тексту.
    if (ctx.empty && !ctx.editing
        && !ev.shiftKey && !ev.altKey && !ev.ctrlKey && !ev.metaKey) return 'edit-last'
    return ''
  }
  if (ev.key === 'Escape') {
    // Порядок = порядок «что открыто поверх»: подсказка лежит над полем, правка и ответ —
    // состояния самого поля. Один Esc снимает один слой.
    if (ctx.picker) return 'close-picker'
    if (ctx.editing) return 'cancel-edit'
    if (ctx.replying) return 'cancel-reply'
    return ''
  }
  return ''
}

/**
 * Новая позиция прокрутки поля, при которой курсор виден целиком.
 *
 * Координаты — экранные (как у `getBoundingClientRect`): верх и низ курсора, верх и низ
 * окна прокрутки. `pad` — поле, чтобы курсор не прилипал к самому краю.
 * Курсор уже виден — возвращается прежняя позиция (лишняя запись в `scrollTop` дёргала бы
 * страницу на каждом символе).
 */
export function scrollToRevealCaret({ caretTop, caretBottom, boxTop, boxBottom, scrollTop, pad = 6 }) {
  if (![caretTop, caretBottom, boxTop, boxBottom, scrollTop].every(Number.isFinite)) return scrollTop
  if (caretBottom > boxBottom - pad) return scrollTop + (caretBottom - (boxBottom - pad))
  if (caretTop < boxTop + pad) return Math.max(0, scrollTop - ((boxTop + pad) - caretTop))
  return scrollTop
}

/**
 * Годится ли файл по расширению. Пустой список разрешений — «ограничений нет»: так
 * отвечает сервер без настроенного хранилища, и отказ здесь подменил бы его причину.
 */
export function extensionAllowed(fileName, allowed) {
  const list = (allowed || []).map((x) => String(x).toLowerCase().replace(/^\./, ''))
  if (!list.length) return true
  const m = /\.([^.\\/]+)$/.exec(String(fileName || ''))
  return !!m && list.includes(m[1].toLowerCase())
}
