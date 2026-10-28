// overlayScroll.test.mjs — у окна своя прокрутка, страница под ним стоит (27.10.2026).
//
// Требование Влада: «отдельный скролл для окон оверлеев» и «починить скролл при открытии
// профиля юзера». Было: колесо над окном прокручивало журнал за подложкой; профиль
// открывался прокрученным к первой кнопке (фокус окна тянул за собой прокрутку), а на
// телефоне низ карточки профиля было не прокрутить вовсе.
//
// ⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН: `unlockFor`, отпирающий страницу на первом же закрытии, —
// краснеет «окно в окне»; убрать `preventScroll` — краснеет проверка фокуса.
import test from 'node:test'
import assert from 'node:assert/strict'
import { readSource } from './_readSource.mjs'

const { coversViewport, fitOverlay, scrollLockTargets, lockFor, syncLock, unlockFor } =
  await import('../src/utils/scrollLock.js')

test('во весь экран — только fixed почти на весь экран', () => {
  const vp = { width: 1000, height: 800 }
  assert.equal(coversViewport('fixed', { width: 1000, height: 800 }, vp), true)
  assert.equal(coversViewport('fixed', { width: 950, height: 760 }, vp), true)
  assert.equal(coversViewport('fixed', { width: 240, height: 300 }, vp), false, 'меню у кнопки')
  assert.equal(coversViewport('absolute', { width: 1000, height: 800 }, vp), false)
})

test('запирается корень, тело и прокручиваемая область оболочки', () => {
  const html = { id: 'html' }; const body = { id: 'body' }; const main = { id: 'gb-main' }
  const doc = { documentElement: html, body, getElementById: (id) => (id === 'gb-main' ? main : null) }
  assert.deepEqual(scrollLockTargets(doc), [html, body, main])
  assert.deepEqual(scrollLockTargets(null), [])
})

/** Поддельный DOM: ровно то, что трогает модуль. */
function fakeDom() {
  const node = (w = 0, cw = 0) => ({ style: { overflow: '', paddingRight: '' }, offsetWidth: w, clientWidth: cw })
  const html = node(); html.clientWidth = 985
  const body = node(); const main = node(800, 785)
  globalThis.window = { innerWidth: 1000, innerHeight: 800 }
  globalThis.document = { documentElement: html, body, getElementById: (id) => (id === 'gb-main' ? main : null) }
  globalThis.getComputedStyle = (el) => el.__cs || { position: 'static', paddingRight: '0px' }
  const overlay = () => ({ style: {}, __cs: { position: 'fixed', top: '0px', left: '0px', right: '0px', bottom: '0px', paddingRight: '0px' },
    getBoundingClientRect: () => ({ width: 1000, height: 800 }) })
  const menu = { style: {}, __cs: { position: 'fixed', top: '40px', left: '10px', right: 'auto', bottom: 'auto' },
    getBoundingClientRect: () => ({ width: 200, height: 160 }) }
  return { html, body, main, overlay, menu }
}

test('окно в окне: страница отпирается, только когда закрылось последнее', () => {
  const { html, main, overlay } = fakeDom()
  const a = overlay(); const b = overlay()
  assert.equal(lockFor(a), true)
  assert.equal(html.style.overflow, 'hidden')
  assert.equal(main.style.overflow, 'hidden')
  assert.equal(main.style.paddingRight, '15px', 'полоса прокрутки ушла — содержимое не прыгает')
  assert.equal(a.style.overscrollBehavior, 'contain', 'своя прокрутка окна не перетекает на страницу')
  lockFor(b)
  unlockFor(b)
  assert.equal(main.style.overflow, 'hidden', 'верхнее окно закрылось — нижнее ещё открыто')
  unlockFor(a)
  assert.equal(main.style.overflow, '')
  assert.equal(main.style.paddingRight, '')
  assert.equal(html.style.overflow, '')
})

test('спрятанный оверлей (v-show) страницу не запирает', () => {
  //Окно активности смонтировано всегда и только скрывается: запри оно страницу при
  //монтаже — журнал не прокручивался бы, пока идёт активность. Обратный ход: убрать
  //проверку `display` — краснеет.
  const { main, overlay } = fakeDom()
  const hidden = overlay()
  hidden.__cs = { ...hidden.__cs, display: 'none' }
  assert.equal(lockFor(hidden), false)
  assert.equal(main.style.overflow, '')
})

test('меню у кнопки страницу не запирает', () => {
  const { main, menu } = fakeDom()
  assert.equal(lockFor(menu), false)
  assert.equal(main.style.overflow, '')
  unlockFor(menu)               //отпустить то, что не запирало, — не ошибка
  assert.equal(main.style.overflow, '')
})

test('обе двери оверлеев запирают страницу, и фокус окна — без прокрутки', () => {
  const dialog = readSource('directives/dialog.js')
  const back = readSource('utils/backLayers.js')
  for (const [name, src] of [['v-dialog', dialog], ['v-back-close', back]]) {
    assert.match(src, /lockFor\(el\)/, `${name}: не запирает страницу`)
    assert.match(src, /unlockFor\(el\)/, `${name}: не отпирает страницу`)
  }
  assert.match(dialog, /items\[0\]\.focus\(\{ preventScroll: true \}\)/,
    'фокус при открытии окна не должен прокручивать его к первой кнопке')
})

test('профиль: карточка прокручивается сама и на телефоне', () => {
  const modal = readSource('components/messenger/PeerProfileModal.vue')
  assert.match(modal, /<div class="max-h-\[inherit\] min-h-0 flex-1 overflow-y-auto/)
  assert.match(readSource('style.css'), /\.gb-profile-window \{[^}]*max-height: 90dvh;/)
})

test('окно выше экрана прокручивается само, и верх не уезжает за край', () => {
  //Обратный ход: оставить `align-items: center` — верх высокого окна недостижим.
  const el = { style: {} }
  fitOverlay(el, { overflowY: 'visible', alignItems: 'center', justifyContent: 'center' })
  assert.equal(el.style.overflowY, 'auto')
  assert.equal(el.style.overflowX, 'hidden', 'анимация появления не должна давать полосу вбок')
  assert.equal(el.style.alignItems, 'safe center')
  assert.equal(el.style.justifyContent, 'safe center')
  //Своё решение окна не перетираем.
  const own = { style: {} }
  fitOverlay(own, { overflowY: 'auto', alignItems: 'flex-start', justifyContent: 'normal' })
  assert.deepEqual(own.style, {})
  assert.match(readSource('directives/dialog.js'), /if \(lockFor\(el\)\) fitOverlay\(el, getComputedStyle\(el\)\)/)
})

test('раскладку по ширине (лист снизу на телефоне) инлайн-стиль не замораживает', () => {
  //Живой прогон 28.10.2026: редактор открыли на ПК (`sm:items-center` → `center`),
  //сузили окно до телефона — лист остался посередине, потому что `fitOverlay` записал
  //`safe center` в инлайн-стиль поверх класса `items-end`. Обратный ход: убрать проверку
  //`BY_WIDTH_ALIGN` — краснеет первая проверка.
  const sheet = { className: 'fixed inset-0 z-50 flex items-end justify-center sm:items-center sm:p-4', style: {} }
  fitOverlay(sheet, { overflowY: 'visible', alignItems: 'center', justifyContent: 'center' })
  assert.equal(sheet.style.alignItems, undefined, 'раскладка по ширине заморожена инлайн-стилем')
  assert.equal(sheet.style.justifyContent, 'safe center', 'горизонталь от ширины не зависит — её чиним')
  assert.equal(sheet.style.overflowY, 'auto')
  //Каркас редакторов именно такой — сторож смотрит на настоящий класс, а не на копию.
  assert.match(readSource('components/ui/EditorShell.vue'), /items-end justify-center[^"]*sm:items-center/)
})

test('оверлей, спрятанный через v-show после показа, страницу отпускает', () => {
  //Окно активности открыли во весь экран (заперло), потом свернули — `v-show` прячет его,
  //не размонтируя. Без пересчёта в `updated` журнал не прокручивался бы, пока идёт
  //активность (нашёл Полковник 28.10.2026). Обратный ход: убрать `syncLock` из
  //`updated` у `v-back-close` — краснеет последняя проверка.
  const { main, overlay } = fakeDom()
  const shell = overlay()
  assert.equal(lockFor(shell), true)
  shell.__cs = { ...shell.__cs, display: 'none' }
  syncLock(shell)
  assert.equal(main.style.overflow, '', 'свернули — страница снова прокручивается')
  shell.__cs = { ...shell.__cs, display: 'block' }
  syncLock(shell)
  assert.equal(main.style.overflow, 'hidden', 'развернули — снова заперта')
  unlockFor(shell)
  assert.match(readSource('utils/backLayers.js'), /updated\(el, binding\) \{[^}]*syncLock\(el\)/)
  assert.match(readSource('directives/dialog.js'), /updated\(el\) \{\s*syncLock\(el\)/)
})
