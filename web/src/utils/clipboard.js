/**
 * clipboard.js — копирование текста в буфер обмена с фолбэком.
 *
 * Зачем не просто `navigator.clipboard.writeText`: этот API есть НЕ везде, и оба
 * промаха у нас реальные, а не теоретические.
 *  • В десктопном веб-виде (QWebEngineView) доступ к буферу из JS по умолчанию ЗАПРЕЩЁН
 *    настройками движка — промис отклоняется (см. ui/messenger_web.py, там теперь
 *    выставлены JavascriptCanAccessClipboard/JavascriptCanPaste).
 *  • В браузере API доступен только в защищённом контексте (HTTPS/localhost): при заходе
 *    на сервер колледжа по локальному IP `navigator.clipboard` попросту undefined.
 * В обоих случаях кнопка «нажималась, но ничего не копировала» — ошибку глотал пустой
 * catch. Фолбэк на execCommand('copy') работает и без защищённого контекста, и в
 * QtWebEngine, поэтому оставляем его насовсем, а не «до лучших времён».
 *
 * Возвращает true при успехе — вызывающий код решает, показать «Скопировано» или ошибку.
 */
export async function copyText(text) {
  const value = String(text ?? '')
  if (!value) return false
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(value)
      return true
    }
  } catch { /* нет прав/не защищённый контекст — пробуем запасной путь ниже */ }
  // Запасной путь: временное поле вне зоны видимости + execCommand. Поле должно быть
  // именно в документе и в фокусе, иначе копировать нечего.
  try {
    const ta = document.createElement('textarea')
    ta.value = value
    ta.setAttribute('readonly', '')
    // Не position:fixed с opacity:0 — часть движков считает такое поле невыделяемым.
    // Уводим за левый край: элемент реален и фокусируем, но невидим и не двигает вёрстку.
    ta.style.cssText = 'position:absolute;left:-9999px;top:0;opacity:0;'
    document.body.appendChild(ta)
    ta.select()
    ta.setSelectionRange(0, value.length)   // iOS игнорирует select() без явного диапазона
    const ok = document.execCommand('copy')
    document.body.removeChild(ta)
    return !!ok
  } catch {
    return false
  }
}
