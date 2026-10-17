// mentions.test.mjs — подсветка отметок в ленте (web/src/utils/mentions.js).
//
// До 16.10.2026 замена шла по всей строке HTML, включая атрибуты: у ссылки
// «https://medium.com/@user» в `href` попадал `<span class="mention">`, и по клику
// открывался не тот адрес; «ivan@mail.ru» подсвечивался как отметка человека «mail».
// Здесь — свойство «атрибуты и ссылки не трогаем» и то же правило границы, что у сервера.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { renderMarkdownLite } from '../src/utils/markdownLite.js'
import { highlightMentions } from '../src/utils/mentions.js'

const render = (body, uidFor) => highlightMentions(renderMarkdownLite(body, false), uidFor)

test('ссылка с «/@» остаётся ссылкой на тот же адрес', () => {
  for (const body of ['смотри https://medium.com/@user', '[статья](https://medium.com/@user)']) {
    const html = render(body)
    assert.ok(html.includes('href="https://medium.com/@user"'), html)
    assert.ok(!html.includes('mention'), html)
  }
})

test('адрес почты — не отметка', () => {
  assert.ok(!render('пишите на ivan@mail.ru').includes('mention'))
})

test('все шесть форм отметки узнаются после пробела и с начала текста', () => {
  for (const form of ['@', '/@', '/@!', '/!@', '@!', '!@']) {
    for (const body of [`${form}Иванов`, `привет ${form}Иванов`, `(${form}Иванов)`]) {
      const html = render(body)
      assert.ok(html.includes(`<span class="mention">${form}Иванов</span>`), `${body} → ${html}`)
    }
  }
})

test('отметка внутри выделения тоже подсвечивается', () => {
  assert.ok(render('**@Иванов**').includes('<span class="mention">@Иванов</span>'))
})

test('id участника экранируется в атрибуте', () => {
  const html = render('@Иванов', () => 'stud:a"b')
  assert.ok(html.includes('data-mention-uid="stud:a&quot;b"'), html)
})
