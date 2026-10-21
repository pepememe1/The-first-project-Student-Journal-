// journalAnchors.test.mjs — якоря карточек предметов и оглавление журнала
// (UX-аудит 17.10.2026: «много прокрутки, перехода к нужному предмету нет»).
//
// ⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН: убрать `subjectAnchorId` из журнала (или поставить там свой
// `id`) — краснеет «чип указывает на карточку»; вернуть название предмета прямо в `id` —
// краснеет «id пригоден для getElementById».
import test from 'node:test'
import assert from 'node:assert/strict'
import { subjectAnchorId } from '../src/utils/journalAnchors.js'
//Через общий `readSource`: иначе на Windows (CRLF) регулярки с переводом строки
//краснеют при исправном коде — см. шапку `_readSource.mjs`.
import { readSource as src } from './_readSource.mjs'

test('один и тот же предмет — один и тот же якорь', () => {
  assert.equal(subjectAnchorId('Математика'), subjectAnchorId('Математика'))
})

test('разные предметы не схлопываются в один якорь', () => {
  const names = ['Математика', 'Физика', 'Техн-я разработки ПО', 'АФХД', 'Математика ']
  const ids = new Set(names.map(subjectAnchorId))
  assert.equal(ids.size, names.length, 'два предмета получили общий якорь — переход уведёт не туда')
})

test('в якоре нет символов, которые ломают поиск элемента', () => {
  //Пробел, точка, слэш и кавычка в `id` ломают `querySelector` без экранирования, причём
  //молча: элемент просто «не находится». Живые названия именно такие.
  for (const name of ['Техн-я разработки ПО', 'К74/1 — практика', "Физ'ра", 'Матем.анализ']) {
    const id = subjectAnchorId(name)
    assert.match(id, /^gb-subj-[0-9a-z]+$/, `опасный id: ${id}`)
  }
})

test('пустое имя не роняет функцию', () => {
  assert.match(subjectAnchorId(''), /^gb-subj-/)
  assert.match(subjectAnchorId(undefined), /^gb-subj-/)
})

for (const page of ['pages/student/StudentJournal.vue', 'pages/parent/ParentJournal.vue']) {
  test(`${page}: оглавление и карточка пользуются ОДНОЙ функцией якоря`, () => {
    const text = src(page)
    assert.match(text, /import SubjectJump from '@\/components\/journal\/SubjectJump\.vue'/,
      'в журнале нет оглавления предметов')
    assert.match(text, /<SubjectJump[\s\S]{0,120}:subjects="data\.subjects"/,
      'оглавлению не передан список предметов из ответа сервера')
    assert.match(text, /subjectAnchorId\(s\.subject\)/,
      'у карточки предмета нет якоря, на который указывает оглавление')
  })
}

test('прокрутка к карточке уважает запрет анимаций', () => {
  //Движение через весь журнал — крупнее любой нашей анимации; `prefers-reduced-motion`
  //в продукте уже уважают лента чата и появление сообщений.
  const jump = src('components/journal/SubjectJump.vue')
  assert.match(jump, /prefers-reduced-motion/)
  assert.match(jump, /scrollIntoView/)
})

test('оглавление не считает средний заново', () => {
  //§4.8: вторая методика среднего дала бы два разных числа на одном экране.
  const jump = src('components/journal/SubjectJump.vue')
  assert.doesNotMatch(jump, /reduce\(|\/ *lessons\.length|Math\.round/,
    'в оглавлении появился свой расчёт среднего')
})
