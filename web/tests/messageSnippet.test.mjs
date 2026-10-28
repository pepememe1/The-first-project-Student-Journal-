// messageSnippet.test.mjs — сообщение одной строкой там, где раньше печаталось тело как
// есть: цитата в пузыре, плашка закрепа, полоса «Ответ» над полем ввода, окно напоминания
// (проверка конфликтов 28.10.2026).
//
// С 4.1.6 у изображения в теле подписанная ссылка `/media/avatar?k=m&…`, и эти четыре
// места показывали бы её текстом; у гифки там ссылка Klipy, у отчёта и активности — id
// («rpt:…», «act:…»), и это было ещё до 4.1.6. Подпись берётся из ТОГО ЖЕ разбора, что у
// списка чатов (`messagePreview`), — второй копии подписей нет.
//
// Обратный ход (проверен): вернуть в ChatThread `{{ topPinned.body }}` — краснеет «ни
// одно из четырёх мест не печатает тело»; убрать ветку текста в `messageSnippet` —
// краснеет «текст — само тело, как раньше».
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readSource } from './_readSource.mjs'

const { createPinia, setActivePinia } = await import('pinia')
setActivePinia(createPinia())
const { messageSnippet } = await import('../src/utils/messagePreview.js')

test('текст — само тело, как раньше: с разметкой и без префикса «Вы:»', () => {
  assert.equal(messageSnippet({ kind: 'text', body: '**важно** завтра', mine: true }), '**важно** завтра')
  assert.equal(messageSnippet({ body: 'старое сообщение без вида' }), 'старое сообщение без вида')
  assert.equal(messageSnippet(null), '')
})

test('у картинки, гифки, отчёта и файла без подписи — подпись, а не ссылка или id', () => {
  const cases = [
    [{ kind: 'image', body: '/media/avatar?k=m&i=5&v=a&s=b', mine: true }, 'Изображение'],
    [{ kind: 'gif', body: 'https://static.klipy.com/ii/x.gif' }, 'GIF'],
    [{ kind: 'report', body: 'rpt:К75/1|3' }, 'Отчёт по группе'],
    [{ kind: 'file', body: '', attachment: { name: 'план.pdf' } }, 'план.pdf'],
  ]
  for (const [msg, want] of cases) {
    const got = messageSnippet(msg)
    assert.equal(got, want, `${msg.kind}: «${got}»`)
  }
})

test('ни одно из четырёх мест не печатает тело сообщения как есть', () => {
  const feed = readSource('components/messenger/ChatThread.vue')
  const reminder = readSource('components/messenger/ReminderDialog.vue')
  assert.doesNotMatch(feed, /\{\{\s*topPinned\.body\s*\}\}/, 'плашка закрепа печатает тело')
  assert.doesNotMatch(feed, /replyQuote \|\| replyTo\.body/, 'полоса «Ответ» печатает тело')
  const quoted = feed.slice(feed.indexOf('function quoted(id)'), feed.indexOf('function quoteAuthor('))
  assert.ok(quoted.length > 0 && quoted.length < 2000, 'функция цитаты не найдена — сторож ослеп')
  assert.match(quoted, /messageSnippet\(src\)/, 'цитата в пузыре печатает тело')
  assert.doesNotMatch(reminder, /\{\{\s*message\.body\s*\}\}/, 'окно напоминания печатает тело')
  assert.match(reminder, /messageSnippet\(message\)/)
})
