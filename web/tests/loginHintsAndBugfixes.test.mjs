/**
 * loginHintsAndBugfixes.test.mjs — три правки по живым жалобам 15.09.2026 (Влад).
 *
 * ━━ ЧТО ИМЕННО ДЕРЖИМ ━━
 * 1. Пояснения под формой входа («Вход для студентов…», «Логин и пароль выдаёт
 *    колледж…», «настраивается в настройках профиля») занимали место и переехали в
 *    кнопку «i» рядом с выбором языка. Сторож нужен потому, что вернуть их обратно
 *    ничего не стоит: один <p> в шаблоне — и место снова занято, а заметит это только
 *    человек с телефоном.
 * 2. Кнопка «⚙ Сервер синхронизации» выключена, но НЕ УДАЛЕНА (прямое условие).
 *    Проверяем обе половины: её не видно И код на месте.
 * 3. Ответ Вектора больше не мелькает целиком перед побуквенной печатью: метка
 *    печати ставится в ТОТ ЖЕ тик, что и добавление сообщения.
 *
 * ⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН на каждом: вернуть <p> с `login.audience` под форму —
 * краснеет первый; заменить `v-if="SYNC_SERVER_BUTTON_ENABLED"` обратно — второй;
 * убрать `_armTyping` после push — третий.
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const read = (rel) => readFileSync(
  new URL(rel, import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1'), 'utf8')

const page = read('../src/pages/LoginPage.vue')
const vectorStore = read('../src/stores/vector.js')
const mods = read('../src/pages/admin/AdminModerators.vue')

/** Разметка страницы без комментариев: пояснение о том, ГДЕ раньше стоял текст, само
 *  содержит его название — разбор, считающий комментарий кодом, краснел бы на
 *  исправном файле и заставлял вычеркнуть урок. */
const pageCode = page.replace(/<!--[\s\S]*?-->/g, '').replace(/\/\/[^\n]*/g, '')

test('пояснения живут в подсказке «i», а не под формой', () => {
  const at = pageCode.indexOf('showLoginHelp')
  assert.ok(at > 0, 'нет состояния подсказки showLoginHelp')

  // Тексты обязаны остаться в продукте — их убрали с глаз, а не выбросили.
  assert.ok(pageCode.includes("loc.t('login.audience')"), 'пояснение про роли пропало вовсе')
  assert.ok(pageCode.includes('login.accountHelpIssued'), 'пояснение про логин/пароль пропало вовсе')
  assert.ok(pageCode.includes('login.passkeyHint'), 'пояснение про вход по ключу пропало вовсе')

  // …и все три обязаны лежать ВНУТРИ всплывающей подсказки. Границу берём по её же
  // разметке: от блока с role="tooltip" до его закрытия.
  const tipStart = pageCode.indexOf('role="tooltip"')
  assert.ok(tipStart > 0, 'подсказка не размечена как tooltip')
  const tip = pageCode.slice(tipStart, tipStart + 1400)
  for (const key of ["loc.t('login.audience')", 'login.accountHelpIssued', 'login.passkeyHint']) {
    assert.ok(tip.includes(key), `пояснение ${key} обязано быть внутри подсказки «i»`)
  }
  // Ровно один раз на всю страницу: вторая копия под формой — это и есть возврат дефекта.
  for (const key of ["loc.t('login.audience')", 'login.accountHelpIssued']) {
    assert.equal((pageCode.match(new RegExp(key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'g')) || []).length, 1,
      `${key} встречается дважды — значит текст вернули и под форму`)
  }
})

test('подсказка открывается не только наведением — иначе на телефоне её нет', () => {
  const at = pageCode.indexOf('aria-label="Как войти"') > 0
    ? pageCode.indexOf('aria-label="Как войти"')
    : pageCode.indexOf('login.helpAria')
  assert.ok(at > 0, 'у кнопки «i» нет доступного имени')
  const btn = pageCode.slice(at - 700, at + 700)
  assert.ok(/@mouseenter="openLoginHelp"/.test(btn), 'нет открытия по наведению (мышь)')
  assert.ok(/@click=/.test(btn), 'нет открытия по нажатию — на сенсорном экране подсказка недостижима')
})

test('кнопка «Сервер синхронизации» выключена, но код цел', () => {
  assert.ok(/const SYNC_SERVER_BUTTON_ENABLED = false/.test(page),
    'нет выключателя SYNC_SERVER_BUTTON_ENABLED = false')
  assert.ok(/v-if="SYNC_SERVER_BUTTON_ENABLED"/.test(page),
    'кнопка обязана сниматься v-if, а не прятаться классом: спрятанную ловит Tab и нажимает Enter')
  assert.ok(page.includes('Сервер синхронизации'),
    'разметку кнопки удалять нельзя — её вернут одной строкой при переезде сервера')
  // Маршрут /connect остаётся доступным по прямому адресу — это единственный способ
  // задать сервер, если адрес по умолчанию не подошёл.
  assert.ok(page.includes("router.push('/connect')"), 'переход на /connect не должен быть удалён')
})

test('ответ Вектора не мелькает целиком: метка печати ставится вместе с сообщением', () => {
  const pushes = [...vectorStore.matchAll(/messages\.value\.push\(\{ role: 'vector', text: answer[^\n]*\n/g)]
  assert.ok(pushes.length >= 2, 'не нашлись добавления ответа Вектора (онлайн и офлайн)')
  for (const m of pushes) {
    const after = vectorStore.slice(m.index + m[0].length, m.index + m[0].length + 400)
    assert.ok(/_armTyping\(msgIndex\)/.test(after),
      'после добавления ответа обязан идти _armTyping(msgIndex) — иначе пузырь успеет ' +
      'показать текст целиком до старта печати')
  }
  const arm = vectorStore.slice(vectorStore.indexOf('function _armTyping'), vectorStore.indexOf('function _startTyping'))
  assert.ok(/done: false/.test(arm), '_armTyping обязан помечать пузырь печатающимся')
})

test('новый модератор появляется в списке сразу, без перезагрузки страницы', () => {
  const save = mods.slice(mods.indexOf('async function save()'), mods.indexOf('function openPassword'))
  assert.ok(/rows\.value = \[/.test(save),
    'строка обязана добавляться в список сразу после подтверждения сервера')
  assert.ok(/reload\(\{ silent: true \}\)/.test(save),
    'перечитывание после действия обязано быть тихим — иначе список мигает «Загрузкой…»')
  assert.ok(/silent = false/.test(mods), 'у reload нет тихого режима')
})
