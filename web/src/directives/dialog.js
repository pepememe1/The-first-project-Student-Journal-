/**
 * v-dialog — окно, которое понимают клавиатура и программа чтения с экрана.
 *
 * Зачем (docs/operations/ACCESSIBILITY.md, пробел №1; план «Золото», веха М2). Окна были
 * просто `div` поверх страницы: программа чтения с экрана не знала, что открыто окно, а
 * Tab уводил фокус ПОД него — человек с клавиатуры «терялся» в невидимой странице. Одна
 * директива вместо правки двадцати компонентов по отдельности: двадцать копий удержания
 * фокуса разошлись бы на первой же правке.
 *
 * Что делает, когда элемент появился:
 *   • `role="dialog"` и `aria-modal="true"`; подпись — первый заголовок внутри
 *     (`aria-labelledby`), если автор окна не подписал его сам;
 *   • запоминает, где был фокус, и ставит его внутрь окна — но только если окно не
 *     поставило его само (поле ввода с автофокусом важнее «первой кнопки»);
 *   • Tab и Shift+Tab ходят по кругу ВНУТРИ окна.
 * Когда элемент исчез — возвращает фокус туда, откуда окно открыли.
 *
 * Esc (02.10.2026, живой прогон: «Esc не закрывает Аттестацию, „Создать“, диалоги
 * преподавателя»). Решение о закрытии по-прежнему за КОМПОНЕНТОМ: Esc делает ровно то,
 * что щелчок мимо окна, — директива щёлкает по подложке, и срабатывает его же
 * `@click.self` (со всеми его условиями: «не во время сохранения», «отмена = resolve(false)»).
 * Окно без `@click.self` (щелчок мимо его не закрывает) не закроется и по Esc.
 *   • закрывается только ВЕРХНЕЕ окно (окно в окне — внутреннее);
 *   • нажатие, уже обработанное внутри (`preventDefault` — поле сбрасывает ввод, меню
 *     закрывает себя), окно не трогает.
 * Слушаем `window` в фазе всплытия: обработчики полей внутри окна срабатывают раньше.
 */

const FOCUSABLE = [
  'a[href]', 'button:not([disabled])', 'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])', 'textarea:not([disabled])', '[tabindex]:not([tabindex="-1"])',
].join(',')

/**
 * Куда перейти по Tab: индекс в списке фокусируемых.
 * `current` — индекс текущего (-1, если фокус вне окна), `back` — Shift+Tab.
 * Чистая функция: её и проверяет тест, без браузера.
 */
export function nextFocusIndex(count, current, back) {
  if (count <= 0) return -1
  if (current < 0) return back ? count - 1 : 0
  if (back) return current === 0 ? count - 1 : current - 1
  return current === count - 1 ? 0 : current + 1
}

/**
 * Нажатие адресовано ЭТОМУ окну, а не вложенному в него: ближайший предок цели с
 * `aria-modal` — само окно (или цель вне всякого окна, например фокус ещё снаружи).
 */
export function ownsEvent(el, target) {
  const inner = target && typeof target.closest === 'function'
    ? target.closest('[aria-modal="true"]') : null
  return !inner || inner === el
}

function focusables(el) {
  return Array.from(el.querySelectorAll(FOCUSABLE))
    .filter((n) => !n.closest('[inert]') && n.getClientRects().length > 0)
}

let _seq = 0

//Открытые окна по порядку открытия: последний — верхний.
const _open = []

/** Какое окно закрывает Esc: верхнее из ещё стоящих на странице, или null. */
export function topDialog(stack) {
  for (let i = stack.length - 1; i >= 0; i--) {
    if (stack[i] && stack[i].isConnected !== false) return stack[i]
  }
  return null
}

/**
 * Открыто ли сейчас хоть одно окно. Для обработчиков Esc на САМОЙ странице («Настройки»
 * закрываются по Esc, колесо активностей — тоже): они висят на `window` раньше слушателя
 * директивы и `preventDefault` от неё увидеть не успевают. Без этого вопроса Esc в окне
 * «Сеансы» закрывал и окно, и сами Настройки (нашёл Полковник 02.10.2026).
 */
export function hasOpenDialog() {
  return topDialog(_open) !== null
}

function _onEscape(e) {
  if (e.key !== 'Escape' || e.defaultPrevented) return
  const top = topDialog(_open)
  if (!top) return
  e.preventDefault()
  top.click()      //= щелчок по подложке: сработает `@click.self` самого окна
}

export const vDialog = {
  mounted(el) {
    el.setAttribute('role', 'dialog')
    el.setAttribute('aria-modal', 'true')
    if (!el.hasAttribute('aria-label') && !el.hasAttribute('aria-labelledby')) {
      const title = el.querySelector('h1, h2, h3, h4')
      if (title) {
        if (!title.id) title.id = `gb-dialog-title-${++_seq}`
        el.setAttribute('aria-labelledby', title.id)
      }
    }
    const opener = document.activeElement
    el.__gbDialog = { opener }
    el.__gbDialog.onKey = (e) => {
      if (e.key !== 'Tab') return
      //🔥 ОКНО В ОКНЕ (нашёл Полковник 30.09.2026): жалоба открывается поверх профиля
      //собеседника, и событие Tab всплывает от внутреннего окна к внешнему. Оба двигали
      //фокус: каждый Tab перепрыгивал через поле, а с конца жалобы фокус уходил на кнопки
      //ПОД ней. Ходит только ближайшее окно, в котором нажали.
      if (!ownsEvent(el, e.target)) return
      const items = focusables(el)
      if (!items.length) { e.preventDefault(); return }
      const i = nextFocusIndex(items.length, items.indexOf(document.activeElement), e.shiftKey)
      e.preventDefault()
      items[i].focus()
    }
    el.addEventListener('keydown', el.__gbDialog.onKey)
    _open.push(el)
    if (_open.length === 1) window.addEventListener('keydown', _onEscape)
    //Фокус внутрь — после того, как компонент отрисовал содержимое и, возможно, сам
    //поставил фокус в поле ввода (ConfirmDialog делает это в nextTick).
    requestAnimationFrame(() => {
      if (!el.isConnected || el.contains(document.activeElement)) return
      const items = focusables(el)
      if (items.length) items[0].focus()
      else { el.setAttribute('tabindex', '-1'); el.focus() }
    })
  },
  unmounted(el) {
    const st = el.__gbDialog
    if (!st) return
    el.removeEventListener('keydown', st.onKey)
    const at = _open.lastIndexOf(el)
    if (at >= 0) _open.splice(at, 1)
    if (!_open.length) window.removeEventListener('keydown', _onEscape)
    //Вернуть фокус туда, откуда окно открыли, — иначе после закрытия он оказывается в
    //начале страницы, и человек с клавиатуры заново проходит всю боковую панель.
    const back = st.opener
    if (back && typeof back.focus === 'function' && document.contains(back)) {
      try { back.focus() } catch { /* элемент ушёл вместе со страницей */ }
    }
    delete el.__gbDialog
  },
}
