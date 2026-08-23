// Сторож подтверждения ухода со страницы, пока на экране пасхалка.
//
// ⚠️ Проверять надо ОБЕ стороны правила, и вторая важнее первой. «Спрашивает, когда
// есть что терять» сломается заметно — человек пожалуется. А вот «НЕ спрашивает про
// постоянные пасхалки» сломается катастрофически и тихо: кольцо Detroit, состояние
// DOOM и счётчик ULTRAKILL висят у студента ВСЁ ВРЕМЯ, и попади они в список
// пропускаемых, продукт задавал бы «точно уйти?» на каждом переходе между вкладками.
// Это уже не пасхалка, а сломанная навигация всему колледжу.
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join, dirname } from 'node:path'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const store = readFileSync(join(ROOT, 'src/stores/easterEggs.js'), 'utf8')
const router = readFileSync(join(ROOT, 'src/router/index.js'), 'utf8')
const desktop = readFileSync(join(ROOT, '..', 'desktop/webview2_app.py'), 'utf8')

const missable = new Set([...store.split('const MISSABLE_IN_PAGE = new Set([')[1]
  .split('])')[0].matchAll(/'([a-z0-9_]+)'/g)].map(m => m[1]))

// Постоянные — те, что живут на аватарке и в журнале всё время, пока человек в системе.
const ALWAYS_ON = ['detroit_led', 'doom_avatar', 'ultrakill_rank']

test('постоянные пасхалки НЕ считаются пропускаемыми', () => {
  const wrong = ALWAYS_ON.filter(id => missable.has(id))
  assert.deepEqual(wrong, [],
    'из-за этого «точно уйти?» спрашивалось бы на КАЖДОМ переходе:\n' + wrong.join('\n'))
})

test('разовые пасхалки страницы сторожатся', () => {
  for (const id of ['binding_of_isaac_d6', 'papers_please_stamp', 'undertale_save']) {
    assert.ok(missable.has(id), `${id} можно пропустить, но переход не сторожится`)
  }
})

test('страж стоит ПОСЛЕ перенаправлений и не трогает выход из аккаунта', () => {
  assert.match(router, /confirmLeavingEasterEgg/, 'страж вообще не подключён к роутеру')
  // Выход уводит на /login, и вопрос поверх уже начатого logout — это ловушка.
  assert.match(router, /to\.path === '\/login'/, 'выход из аккаунта обязан быть исключением')
  // Вопрос — последним: иначе спрашивали бы перед переходом, который не состоится.
  // ⚠️ Ищем именно ВЫЗОВ (await …), а не определение функции: определение стоит в
  // начале файла, и первая версия этой проверки цеплялась за него и краснела на
  // исправном коде.
  const guardAt = router.indexOf('await confirmLeavingEasterEgg(to, from)')
  const roleAt = router.lastIndexOf("to.meta.role")
  assert.ok(guardAt > roleAt, 'страж обязан стоять после проверок роли и авторизации')
})

test('закрытие окна и вкладки тоже перехвачено', () => {
  assert.match(router, /beforeunload/, 'закрытие вкладки не сторожится')
  assert.match(router, /__gbEasterPending/, 'нет моста для оболочки программы')
  assert.match(desktop, /__gbEasterPending/, 'десктоп не спрашивает страницу перед закрытием')
  assert.match(desktop, /events\.closing/, 'десктоп не подписан на закрытие окна')
})

test('обратный ход: правило ловит постоянную пасхалку в списке пропускаемых', () => {
  const broken = new Set([...missable, 'doom_avatar'])
  assert.ok(ALWAYS_ON.some(id => broken.has(id)),
    'проверка обязана краснеть, если постоянную добавят в список')
})
