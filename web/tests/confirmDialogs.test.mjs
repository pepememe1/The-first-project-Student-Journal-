/**
 * confirmDialogs.test.mjs — вопросы перед непоправимым задаёт продукт, и задаёт по делу
 * (13.10.2026).
 *
 * ━━ ЧТО ДЕРЖИМ ━━
 * 1. Встроенных окон браузера `alert / confirm / prompt` в продукте нет. Встроенное окно
 *    выглядит чужим («Подтвердите действие на 127.0.0.1»), кнопки у него на языке системы,
 *    а после нескольких показов браузер предлагает галочку «не показывать больше» — и с
 *    ней `confirm()` МОЛЧА отвечает «нет»: удалить что-либо становится нельзя, и причины
 *    человеку не видно. Проверяется СВОЙСТВО по всему `src`, а не список файлов.
 * 2. Окна удаления у администратора называют последствия (числа считает сервер), а группу
 *    со студентами удалить можно, только набрав её название.
 * 3. В курсе материал и задание больше не удаляются одним нажатием.
 *
 * ⚠️ ОБРАТНЫЙ ХОД: `nativeDialogs` натравливается на строку с `window.confirm(` и на
 * голый `if (!confirm(` без своего окна — обе обязана найти.
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { impactRows, needsTyping, typedMatches, IMPACT_FIELDS } from '../src/utils/deleteImpact.js'

const SRC = new URL('../src/', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1')
//Окончания строк приводим к одному виду: часть файлов в рабочей копии лежит с CRLF.
const read = (rel) => readFileSync(join(SRC, rel), 'utf8').replace(/\r\n/g, '\n')

function walk(dir, acc = []) {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) walk(full, acc)
    else if (/\.(vue|js)$/.test(name)) acc.push(full)
  }
  return acc
}

/** Код без комментариев: пояснение «здесь стоял window.confirm» — не вызов. */
function codeOnly(text) {
  return text
    .replace(/<!--[\s\S]*?-->/g, '')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:'"`])\/\/[^\n]*/g, '$1')
}

/**
 * Вызовы встроенных окон в тексте файла.
 * `window.confirm(` — всегда встроенное. Голое `confirm(` / `prompt(` — встроенное, если в
 * файле нет своего окна под этим именем (`useConfirm` возвращает `confirm` и `prompt`).
 */
function nativeDialogs(text) {
  const code = codeOnly(text)
  const found = [...code.matchAll(/window\.(alert|confirm|prompt)\(/g)].map((m) => m[0])
  found.push(...[...code.matchAll(/(^|[^.\w])alert\(/gm)].map(() => 'alert('))
  for (const name of ['confirm', 'prompt']) {
    //Своё окно: имя взято у useConfirm (`{ confirm }`, `{ confirm, prompt }`) либо это
    //собственная функция файла (`function confirm()` — кнопка «подтвердить» в форме).
    const own = new RegExp(`\\{[^}]*\\b${name}\\b[^}:]*\\}\\s*=\\s*useConfirm\\(\\)`).test(code)
      || new RegExp(`function ${name}\\(`).test(code)
    if (own) continue
    if (new RegExp(`(^|[^.\\w])${name}\\(`, 'm').test(code)) found.push(`${name}(`)
  }
  return found
}

test('в продукте нет встроенных окон браузера', () => {
  const bad = []
  for (const file of walk(SRC)) {
    if (file.replace(/\\/g, '/').endsWith('composables/useConfirm.js')) continue
    const hits = nativeDialogs(readFileSync(file, 'utf8'))
    if (hits.length) bad.push(`${file.slice(SRC.length)}: ${hits.join(', ')}`)
  }
  assert.deepEqual(bad, [], `встроенные окна браузера:\n${bad.join('\n')}`)
})

test('обратный ход: проверка видит и window.confirm, и голый confirm', () => {
  assert.deepEqual(nativeDialogs("if (!window.confirm('Удалить?')) return"), ['window.confirm('])
  assert.deepEqual(nativeDialogs("async function f() { if (!confirm(t('x'))) return }"), ['confirm('])
  assert.deepEqual(nativeDialogs("window.alert('Не получилось')"), ['window.alert('])
  assert.deepEqual(nativeDialogs("const v = prompt('Заметка')"), ['prompt('])
  // …и не шумит на своём окне и на комментарии.
  assert.deepEqual(nativeDialogs("const { confirm, prompt } = useConfirm()\nif (await confirm({})) x()\nawait prompt({})"), [])
  assert.deepEqual(nativeDialogs("const { confirm: ask } = useConfirm()\nawait ask({})"), [])
  assert.deepEqual(nativeDialogs('// здесь стоял window.confirm(…)\nconst a = 1'), [])
})

test('окно удаления показывает только ненулевые числа, по порядку', () => {
  assert.deepEqual(impactRows('group', { students: 9, lessons: 12, marks: 134, teachers: 0 }),
    [{ field: 'students', n: 9 }, { field: 'lessons', n: 12 }, { field: 'marks', n: 134 }])
  assert.deepEqual(impactRows('student', { marks: 0, finals: 0, parents: 0 }), [])
  assert.deepEqual(impactRows('planet', { x: 1 }), [])
  assert.deepEqual(impactRows('group', null), [])
})

test('набор названия требуется только у группы, за которой кто-то стоит', () => {
  assert.equal(needsTyping('group', { students: 9, marks: 0 }), true)
  assert.equal(needsTyping('group', { students: 0, marks: 5 }), true)
  assert.equal(needsTyping('group', { students: 0, marks: 0 }), false, 'пустую группу удаляют без набора')
  assert.equal(needsTyping('student', { marks: 100 }), false)
  //Числа не пришли (нет связи) — набор не требуем: требовать его «на всякий случай»
  //значило бы приучить набирать название не читая.
  assert.equal(needsTyping('group', null), false)
})

test('набранное сверяется без учёта регистра и пробелов, пустое не подходит никогда', () => {
  assert.equal(typedMatches(' к74/1 ', 'К74/1'), true)
  assert.equal(typedMatches('К74/2', 'К74/1'), false)
  assert.equal(typedMatches('', ''), false)
  assert.equal(typedMatches('', 'К74/1'), false)
})

test('у каждого числа с сервера есть подпись в окне', () => {
  const composable = read('composables/useDeleteConfirm.js')
  for (const [kind, fields] of Object.entries(IMPACT_FIELDS)) {
    for (const field of fields) {
      assert.ok(composable.includes(`'deleteImpact.${kind}.${field}'`),
        `число ${kind}.${field} придёт с сервера, а показать его нечем`)
    }
  }
})

test('проводка: четыре раздела администратора спрашивают через окно с последствиями', () => {
  const pages = { 'pages/admin/AdminGroups.vue': 'group', 'pages/admin/AdminSubjects.vue': 'subject',
    'pages/admin/AdminStudents.vue': 'student', 'pages/admin/AdminTeachers.vue': 'teacher' }
  for (const [file, kind] of Object.entries(pages)) {
    assert.match(read(file), new RegExp(`confirmDelete\\(\\{ kind: '${kind}'`),
      `${file}: удаление снова спрашивает одной строкой «Удалить …?»`)
  }
  const dialog = read('components/ui/ConfirmDialog.vue')
  assert.match(dialog, /:disabled="locked"/, 'кнопка согласия не запирается набором названия')
  assert.match(dialog, /if \(locked\.value\) return/, 'Enter в поле обходит запертую кнопку')
})

test('проводка: в курсе материал и задание не удаляются одним нажатием', () => {
  const page = read('pages/CourseDetailPage.vue')
  for (const fn of ['delMaterial', 'delAssignment']) {
    const body = page.slice(page.indexOf(`async function ${fn}(`), page.indexOf('}\n', page.indexOf(`async function ${fn}(`)) + 1)
    assert.ok(body.indexOf('await ask(') > 0 && body.indexOf('await ask(') < body.indexOf('coursesApi.'),
      `${fn}: удаление идёт без вопроса`)
  }
})
