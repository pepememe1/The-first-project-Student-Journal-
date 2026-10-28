/**
 * scrollLock.js — пока открыт оверлей, страница под ним не прокручивается (27.10.2026,
 * требование Влада «отдельный скролл для окон оверлеев»).
 *
 * 🔥 Что было. Колесо и палец над окном прокручивали журнал ЗА подложкой: окно — это
 * `fixed` поверх страницы, а прокрутка уходит к ближайшему прокручиваемому предку по
 * разметке, то есть к `#gb-main` оболочки. Окно стояло, страница под ним ехала, а дойдя
 * до края списка внутри окна, жест перетекал на страницу.
 *
 * Одно место на оба вида оверлеев — `v-dialog` (окна) и `v-back-close` (панели, меню во
 * весь экран, пасхалки): копия в каждом разошлась бы на первой правке. Запирается только
 * то, что закрывает экран целиком (`fixed` и почти во всю ширину и высоту): выпадающее
 * меню у кнопки страницу не запирает — под ним её видно и её листают.
 *
 * ⚠️ Запирает первый оверлей, отпирает последний: окно поверх окна не должно отпереть
 * страницу, закрывшись раньше нижнего.
 */

/** Что запереть: корень документа, тело и прокручиваемую область оболочки. */
export function scrollLockTargets(doc) {
  if (!doc) return []
  return [doc.documentElement, doc.body, doc.getElementById?.('gb-main')].filter(Boolean)
}

/**
 * Закрывает ли элемент экран: `fixed` и не меньше 90 % окна по обеим сторонам.
 * Чистая функция над тем, что ей передали, — её проверяет тест без браузера.
 */
export function coversViewport(position, rect, viewport) {
  if (position !== 'fixed' || !rect || !viewport) return false
  return rect.width >= viewport.width * 0.9 && rect.height >= viewport.height * 0.9
}

const _holders = new Set()
let _saved = null

function _apply() {
  _saved = scrollLockTargets(document).map((n) => {
    const was = { n, overflow: n.style.overflow, paddingRight: n.style.paddingRight }
    //Полоса прокрутки исчезает — без поправки содержимое прыгнуло бы вбок на её ширину.
    const gap = n === document.documentElement
      ? window.innerWidth - document.documentElement.clientWidth
      : n.offsetWidth - n.clientWidth
    n.style.overflow = 'hidden'
    if (gap > 0 && n !== document.body) {
      const pad = parseFloat(getComputedStyle(n).paddingRight) || 0
      n.style.paddingRight = `${pad + gap}px`
    }
    return was
  })
}

function _restore() {
  for (const { n, overflow, paddingRight } of _saved || []) {
    n.style.overflow = overflow
    n.style.paddingRight = paddingRight
  }
  _saved = null
}

/** Запереть страницу, если элемент — оверлей во весь экран. Возвращает, запер ли. */
export function lockFor(el) {
  if (typeof document === 'undefined' || typeof getComputedStyle !== 'function' || !el) return false
  const cs = getComputedStyle(el)
  //🔥 Спрятанный оверлей (`v-show`) не запирает ничего: окно активности смонтировано
  //всегда и лишь скрывается, и запри оно страницу при монтаже — журнал перестал бы
  //прокручиваться навсегда, пока идёт активность.
  if (cs.display === 'none' || cs.visibility === 'hidden') return false
  const rect = typeof el.getBoundingClientRect === 'function' ? el.getBoundingClientRect() : null
  //`inset-0` — тоже «во весь экран», даже если окно ещё разворачивается анимацией и его
  //прямоугольник в момент появления меньше экрана.
  const insetZero = cs.position === 'fixed' && cs.top === '0px' && cs.left === '0px'
    && cs.right === '0px' && cs.bottom === '0px'
  if (!insetZero && !coversViewport(cs.position, rect,
    { width: window.innerWidth, height: window.innerHeight })) return false
  //Своя прокрутка окна не перетекает на страницу, дойдя до края.
  if (!el.style.overscrollBehavior) el.style.overscrollBehavior = 'contain'
  if (_holders.has(el)) return true
  if (!_holders.size) _apply()
  _holders.add(el)
  return true
}

/**
 * Пересчитать после перерисовки (хук `updated` обеих директив). Оверлей, смонтированный
 * видимым и потом спрятанный через `v-show` (окно активности сворачивают), не
 * размонтируется — и без пересчёта держал бы страницу запертой, пока идёт активность
 * (нашёл Полковник 28.10.2026). Спрятан — отпускаем, снова показан — запираем.
 */
export function syncLock(el) {
  if (typeof getComputedStyle !== 'function' || !el) return
  const cs = getComputedStyle(el)
  if (cs.display === 'none' || cs.visibility === 'hidden') unlockFor(el)
  else lockFor(el)
}

/** Отпустить: последний закрывшийся оверлей возвращает странице прокрутку. */
export function unlockFor(el) {
  if (!_holders.delete(el)) return
  if (!_holders.size) _restore()
}

/**
 * Окно выше экрана прокручивается САМО (только для окон `v-dialog`).
 *
 * Подложка окна — `fixed inset-0` с центровкой (`grid place-items-center` или flex), и у
 * неё не было своей прокрутки: окно, которое выше экрана (длинная форма на телефоне,
 * клавиатура заняла пол-экрана), обрезалось сверху и снизу без способа долистать. Подложка
 * получает вертикальную прокрутку, а центровка — `safe center`: при обычной центровке
 * верх высокого окна уезжает за край, куда прокрутка не достаёт.
 * ⚠️ Горизонтальную прокрутку гасим явно: иначе анимация появления окна (масштаб, сдвиг)
 * на миг показывала бы горизонтальную полосу. Панели `v-back-close` не трогаем — у
 * выдвижных панелей своя раскладка, и та же полоса появлялась бы на каждом выезде.
 */
export function fitOverlay(el, cs) {
  if (!el?.style || !cs) return
  if (cs.overflowY === 'visible') {
    el.style.overflowY = 'auto'
    el.style.overflowX = 'hidden'
  }
  //🔥 Раскладку, заданную ПО ШИРИНЕ (`items-end sm:items-center` — лист снизу на телефоне,
  //окно посередине на ПК), инлайн-стилем не трогаем (живой прогон 28.10.2026). Инлайн
  //замораживает ту ширину, на которой окно открылось: открыли редактор на ПК или в
  //альбомной ориентации, повернули телефон — лист так и висел посередине, а не у низа.
  //Такие окна держат высоту сами (`max-h` и своя прокрутка тела), `safe` им не нужен.
  const cls = typeof el.className === 'string' ? el.className : ''
  if (cs.alignItems === 'center' && !BY_WIDTH_ALIGN.test(cls)) el.style.alignItems = 'safe center'
  if (cs.justifyContent === 'center' && !BY_WIDTH_JUSTIFY.test(cls)) el.style.justifyContent = 'safe center'
}

const BY_WIDTH_ALIGN = /(?:^|\s)(?:max-)?(?:sm|md|lg|xl|2xl):items-/
const BY_WIDTH_JUSTIFY = /(?:^|\s)(?:max-)?(?:sm|md|lg|xl|2xl):justify-/
