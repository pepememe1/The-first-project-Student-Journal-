// loginSelection.test.mjs — где текст выделяется мышью, а где нет (28.09.2026).
//
// Жалоба Ярослава: на странице входа мышкой выделялось всё — заголовок, подсказки,
// подписи. Экран входа — панель приложения, а не документ: выделять на нём можно только
// то, что человек вводит сам. «Расписание без входа» — наоборот, документ: там копируют
// аудиторию, время и фамилию преподавателя, и выделение обязано работать.
//
// ⚠️ Проверка текстовая, и это осознанно: `user-select` не видят ни сборка, ни линтер, а
// браузерная проверка потребовала бы живого стенда ради одного свойства CSS.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const WEB = dirname(dirname(fileURLToPath(import.meta.url)))
const login = readFileSync(join(WEB, 'src', 'pages', 'LoginPage.vue'), 'utf8')
const schedule = readFileSync(join(WEB, 'src', 'pages', 'PublicSchedule.vue'), 'utf8')
const router = readFileSync(join(WEB, 'src', 'router', 'index.js'), 'utf8')

//Корневой элемент шаблона — первый тег после <template>, минуя комментарии.
function rootTag(sfc) {
  const tpl = sfc.slice(sfc.indexOf('<template>') + '<template>'.length)
  const noComments = tpl.replace(/<!--[\s\S]*?-->/g, '')
  return noComments.match(/<([a-zA-Z][\w-]*)\b[^>]*>/)[0]
}

test('страница входа целиком запрещает выделение', () => {
  const root = rootTag(login)
  assert.match(root, /\bclass="[^"]*\bselect-none\b/, `корень: ${root}`)
  assert.match(root, /\bclass="[^"]*\blogin-screen\b/, 'нет класса, к которому привязано правило для полей')
})

test('поля ввода на странице входа выделяются (включая поля дочерних компонентов)', () => {
  const style = login.slice(login.indexOf('<style'))
  for (const what of ['input', 'textarea']) {
    const rule = new RegExp(`\\.login-screen\\s+:deep\\(${what}\\)[^{]*\\{[^}]*user-select:\\s*text`)
    assert.match(style, rule, `нет правила user-select: text для ${what}`)
  }
  assert.match(style, /-webkit-user-select:\s*text/, 'без префикса Safari на iOS поле останется невыделяемым')
})

test('«Расписание без входа» — отдельная страница, и выделение там не запрещено', () => {
  assert.match(router, /path:\s*'\/schedule',\s*component:\s*\(\)\s*=>\s*import\('@\/pages\/PublicSchedule\.vue'\)/)
  assert.doesNotMatch(schedule, /\bselect-none\b|user-select:\s*none/,
    'в расписании без входа выделение обязано работать — там копируют аудиторию и время')
  assert.doesNotMatch(login, /<PublicSchedule\b/, 'расписание встроено в страницу входа — запрет выделения заденет его')
})
