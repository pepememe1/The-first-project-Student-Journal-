// composerKeys.test.mjs — клавиши поля ввода сообщения и прокрутка к курсору.
//
// Просьба Ярослава (05.10.2026): «бери ввод текста напрямую с передовых мессенджеров
// (Discord и Telegram), иначе преимуществ в собственном мессенджере нет». Правила — в
// `src/utils/composerKeys.js`; здесь они проверяются числами, потому что в обработчике
// события их без браузера не проверить, а ломаются они перестановкой двух условий.
import test from 'node:test'
import assert from 'node:assert/strict'
import { composerKeyAction, scrollToRevealCaret, extensionAllowed } from '../src/utils/composerKeys.js'
import { studentGroup } from '../src/utils/people.js'

const key = (k, extra = {}) => ({ key: k, ...extra })

test('ПК: Enter отправляет, Shift+Enter переносит строку', () => {
  assert.equal(composerKeyAction(key('Enter'), {}), 'send')
  assert.equal(composerKeyAction(key('Enter', { shiftKey: true }), {}), 'newline')
})

test('🔥 телефон: Enter переносит строку — отправляет кнопка', () => {
  // У экранной клавиатуры нет Shift+Enter: при «Enter = отправить» многострочное
  // сообщение с телефона было невозможно вовсе. Так же ведут себя Telegram и Discord.
  assert.equal(composerKeyAction(key('Enter'), { handheld: true }), 'newline')
  // С подключённой клавиатуры Ctrl/⌘+Enter — осознанное «отправить».
  assert.equal(composerKeyAction(key('Enter', { ctrlKey: true }), { handheld: true }), 'send')
  assert.equal(composerKeyAction(key('Enter', { metaKey: true }), { handheld: true }), 'send')
})

test('🔥 Enter во время набора иероглифа сообщение НЕ отправляет', () => {
  // У продукта есть китайская локаль. Enter в окне выбора иероглифа подтверждает
  // вариант — отправка в этот момент уносила бы недописанную фразу на каждом слове.
  assert.equal(composerKeyAction(key('Enter', { isComposing: true }), {}), '')
  assert.equal(composerKeyAction(key('Enter', { keyCode: 229 }), {}), '',
    'Safari не выставляет isComposing на keydown — его признак это код 229')
  // Обратный ход: тот же Enter без признака набора обязан отправлять.
  assert.equal(composerKeyAction(key('Enter', { keyCode: 13 }), {}), 'send')
})

test('стрелка вверх правит последнее сообщение ТОЛЬКО из пустого поля', () => {
  assert.equal(composerKeyAction(key('ArrowUp'), { empty: true }), 'edit-last')
  // В непустом поле стрелка двигает курсор — перехват отнял бы навигацию по тексту.
  assert.equal(composerKeyAction(key('ArrowUp'), { empty: false }), '')
  // Уже правим — вторая правка поверх первой съела бы отложенный черновик.
  assert.equal(composerKeyAction(key('ArrowUp'), { empty: true, editing: true }), '')
  // С модификатором это выделение или системное сочетание.
  assert.equal(composerKeyAction(key('ArrowUp', { shiftKey: true }), { empty: true }), '')
  assert.equal(composerKeyAction(key('ArrowUp', { altKey: true }), { empty: true }), '')
})

test('Esc снимает ОДИН слой, и сверху вниз', () => {
  const all = { picker: true, editing: true, replying: true }
  assert.equal(composerKeyAction(key('Escape'), all), 'close-picker')
  assert.equal(composerKeyAction(key('Escape'), { editing: true, replying: true }), 'cancel-edit')
  assert.equal(composerKeyAction(key('Escape'), { replying: true }), 'cancel-reply')
  // Снимать нечего — событие не трогаем: Esc должен дойти до окна над лентой.
  assert.equal(composerKeyAction(key('Escape'), {}), '')
})

test('остальные клавиши — дело браузера', () => {
  for (const k of ['a', 'Backspace', 'Tab', 'ArrowDown', 'Home', ' ']) {
    assert.equal(composerKeyAction(key(k), { empty: true }), '', `перехвачена клавиша «${k}»`)
  }
  assert.equal(composerKeyAction(null, {}), '')
})

// ── прокрутка к курсору ───────────────────────────────────────────────────────────────

test('🔥 курсор ниже окна — окно прокручивается ровно на недостающее', () => {
  // Тот самый случай из жалобы: текст перенёсся на строку ниже видимой.
  const top = scrollToRevealCaret({
    caretTop: 150, caretBottom: 171, boxTop: 100, boxBottom: 160, scrollTop: 0, pad: 6 })
  assert.equal(top, 17, 'низ курсора (171) обязан встать на 6 px выше низа окна (160)')
})

test('курсор выше окна — прокрутка назад, но не в минус', () => {
  assert.equal(scrollToRevealCaret({
    caretTop: 90, caretBottom: 111, boxTop: 100, boxBottom: 160, scrollTop: 40, pad: 6 }), 24)
  assert.equal(scrollToRevealCaret({
    caretTop: 60, caretBottom: 81, boxTop: 100, boxBottom: 160, scrollTop: 10, pad: 6 }), 0,
    'отрицательная прокрутка — это уже не «показать курсор», а мусор в scrollTop')
})

test('курсор виден — позиция не меняется', () => {
  // Лишняя запись в scrollTop на каждом символе дёргала бы поле.
  assert.equal(scrollToRevealCaret({
    caretTop: 120, caretBottom: 141, boxTop: 100, boxBottom: 160, scrollTop: 33 }), 33)
})

test('неполные замеры не превращаются в NaN', () => {
  // Узел зеркала мог быть не отрисован: NaN в scrollTop браузер молча превращает в 0,
  // и поле прыгало бы в начало текста.
  assert.equal(scrollToRevealCaret({
    caretTop: undefined, caretBottom: 141, boxTop: 100, boxBottom: 160, scrollTop: 33 }), 33)
})

// ── тип файла при вставке из буфера ───────────────────────────────────────────────────

test('расширение сверяется с белым списком сервера без учёта регистра и точки', () => {
  assert.equal(extensionAllowed('Отчёт.PDF', ['.pdf', '.docx']), true)
  assert.equal(extensionAllowed('doc.docx', ['pdf', 'docx']), true)
  assert.equal(extensionAllowed('снимок.png', ['.pdf', '.docx']), false,
    'снимок экрана из буфера — тот самый случай, ради которого проверка у вставки')
  assert.equal(extensionAllowed('без-расширения', ['.pdf']), false)
  assert.equal(extensionAllowed('архив.tar.gz', ['.gz']), true)
})

test('пустой список — ограничений нет, решает сервер', () => {
  // Так отвечает сервер без настроенного хранилища; отказ здесь подменил бы его причину.
  assert.equal(extensionAllowed('что-угодно.exe', []), true)
  assert.equal(extensionAllowed('что-угодно.exe', undefined), true)
})

// ── тег группы студента ───────────────────────────────────────────────────────────────

test('🔥 группа берётся у СТУДЕНТА, а роль в беседе с системной не путается', () => {
  // Карточка человека: системная роль лежит в `role`.
  assert.equal(studentGroup({ role: 'student', group_name: 'К74/1' }), 'К74/1')
  // Участник беседы: в `role` — роль В БЕСЕДЕ, системная — в `user_role`. Спроси мы
  // `role === 'student'`, тег не появился бы ни у одного участника.
  assert.equal(studentGroup({ role: 'member', user_role: 'student', group_name: 'К74/1' }), 'К74/1')
  assert.equal(studentGroup({ role: 'owner', user_role: 'student', group_name: ' К64/2 ' }), 'К64/2')
})

test('у преподавателя, родителя и человека без группы тега нет', () => {
  assert.equal(studentGroup({ role: 'teacher', group_name: '' }), '')
  // Родитель: «его группа» — это группа ребёнка; тег выдал бы его за учащегося.
  assert.equal(studentGroup({ role: 'parent', group_name: 'К74/1' }), '')
  assert.equal(studentGroup({ role: 'member', user_role: 'teacher', group_name: 'К74/1' }), '')
  assert.equal(studentGroup({ role: 'student', group_name: '' }), '')
  assert.equal(studentGroup(null), '')
  assert.equal(studentGroup(undefined), '')
})
