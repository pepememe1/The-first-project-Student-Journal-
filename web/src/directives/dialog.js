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
 *
 * Кнопка «назад» на телефоне закрывает окно тем же щелчком по подложке (utils/backLayers.js).
 */
import { pushLayer, removeLayer, topLayer } from '../utils/backLayers.js'

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

const SEARCHY = /поиск|найти|search|搜索/i

/**
 * Считается ли ввод в этом поле «данными, которые жалко потерять». Поиск и фильтры —
 * нет: окно выбора человека не должно переспрашивать «закрыть без сохранения?» из-за
 * набранной в поиске фамилии. Чистая функция — её проверяет тест без браузера.
 */
export function countsAsEntry(node) {
  if (!node || !node.tagName) return false
  const tag = node.tagName.toLowerCase()
  if (node.isContentEditable) return true
  if (tag !== 'input' && tag !== 'textarea' && tag !== 'select') return false
  const raw = (n) => (typeof node.getAttribute === 'function' ? node.getAttribute(n) : null)
  const attr = (n) => raw(n) || ''
  if (raw('data-dialog-ignore') != null || attr('role') === 'combobox') return false
  const type = (attr('type') || 'text').toLowerCase()
  if (type === 'search' || type === 'hidden') return false
  return !SEARCHY.test(`${attr('placeholder')} ${attr('aria-label')}`)
}

/** «Закрыть без сохранения?» Модуль подтверждения грузится лениво: директиву импортируют
 *  и тесты под node, где стора языка нет. */
async function confirmDiscard() {
  const [{ useConfirm }, { useLocaleStore }] = await Promise.all([
    import('../composables/useConfirm.js'), import('../stores/locale.js')])
  const t = useLocaleStore().t
  return useConfirm().confirm({
    title: t('dialog.discardTitle', 'Закрыть без сохранения?'),
    message: t('dialog.discardMessage', 'Введённые данные пропадут.'),
    okText: t('dialog.discardOk', 'Закрыть без сохранения'),
    cancelText: t('dialog.discardBack', 'Вернуться'),
    danger: true,
  })
}

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
  //Поверх окна открыто меню (`v-back-close` внутри него) — Esc закрывает меню, а не окно.
  const layer = topLayer()
  if (layer && layer.el !== top && !layer.el.__gbDialog) return
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
    //Щелчок мимо окна, Esc и «назад» на телефоне закрывали форму вместе с введённым
    //(живой прогон 27.10.2026: ФИО набрано, тап у края — всё пропало). Если человек что-то
    //вводил, сначала спрашиваем. Окно со своей проверкой (`data-dialog-guard="self"`)
    //решает само — иначе вопрос прозвучал бы дважды. Ловим в фазе перехвата: на самом
    //элементе она срабатывает раньше `@click.self` компонента.
    const st0 = el.__gbDialog
    st0.dirty = false
    st0.onEntry = (e) => {
      if (ownsEvent(el, e.target) && countsAsEntry(e.target)) st0.dirty = true
    }
    el.addEventListener('input', st0.onEntry)
    el.addEventListener('change', st0.onEntry)
    if (typeof el.getAttribute !== 'function' || el.getAttribute('data-dialog-guard') !== 'self') {
      st0.onGuard = (e) => {
        if (e.target !== el || !st0.dirty || st0.bypass) return
        e.stopImmediatePropagation()
        e.preventDefault()
        if (st0.asking) return
        st0.asking = true
        confirmDiscard().then((ok) => {
          st0.asking = false
          if (!ok || !el.isConnected) return
          st0.bypass = true
          try { el.click() } finally { st0.bypass = false }
        }).catch(() => { st0.asking = false })
      }
      el.addEventListener('click', st0.onGuard, true)
    }
    _open.push(el)
    pushLayer(el, () => el.click())
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
    el.removeEventListener('input', st.onEntry)
    el.removeEventListener('change', st.onEntry)
    if (st.onGuard) el.removeEventListener('click', st.onGuard, true)
    const at = _open.lastIndexOf(el)
    if (at >= 0) _open.splice(at, 1)
    removeLayer(el)
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
