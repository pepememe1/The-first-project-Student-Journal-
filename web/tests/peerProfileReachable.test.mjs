// peerProfileReachable.test.mjs — сторож достижимости чужого профиля из ленты чата.
//
// 🔥 ПОВОД (просьба Влада, 02.09.2026): «при нажатии на аватарку/ник другого юзера
// открывается его профиль». Оказалось, что механизм был готов давно — `PeerProfileModal`
// существует, в её же докстринге написано «открывается кликом по аватарке/имени человека
// ГДЕ УГОДНО в мессенджере», — а в ЛЕНТЕ его не звал никто: аватарка была простым
// `<Avatar>`, имя автора простым `<div>`. Классическое «обещание без вызывающего», и
// заметное здесь не по коду, а по документации, которая обещала больше, чем есть.
//
// ⚠️ ЧЕГО ЭТОТ СТОРОЖ НЕ ДЕЛАЕТ. Он не открывает браузер и не проверяет, что модалка
// действительно появилась — вёрстку тестами не проверить (§8.2, dev-browser запрещён).
// Он проверяет СВЯЗЬ: что обработчик существует, что его зовут из обеих точек, что клик
// по имени не открывает заодно меню сообщения и что для Вектора кнопки не появляется.
// Удали строку вызова — сторож покраснеет; это и есть его работа.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const root = resolve(here, '..', '..')
const threadPath = resolve(root, 'web/src/components/messenger/ChatThread.vue')
const thread = readFileSync(threadPath, 'utf-8')

// Шаблон отделяем от скрипта: вызов, живущий ТОЛЬКО в скрипте, — это функция без
// пользователя, ровно тот дефект, от которого сторож защищает. Проверять надо разметку.
const template = thread.slice(thread.indexOf('<template>'))

test('профиль автора открывается КЛИКОМ ПО АВАТАРКЕ в ленте', () => {
  assert.match(
    template,
    /<button[^>]*@click="openSenderProfile\(msg\)"/,
    'аватарка автора не ведёт в профиль: нет кнопки с openSenderProfile(msg) в шаблоне',
  )
})

test('профиль автора открывается КЛИКОМ ПО ЕГО ИМЕНИ над пузырём', () => {
  // Имя лежит ВНУТРИ пузыря, у которого свой @click (меню сообщения). Поэтому здесь
  // обязателен модификатор .stop — см. следующий тест, он про это же с другой стороны.
  assert.match(
    template,
    /@click\.stop="openSenderProfile\(msg\)"/,
    'имя автора не ведёт в профиль: нет обработчика @click.stop="openSenderProfile(msg)"',
  )
})

test('клик по имени НЕ открывает заодно меню сообщения', () => {
  // Без .stop событие всплывёт на пузырь (`role="button"` c @click="onMessageClick"),
  // и одно нажатие дало бы сразу профиль И меню. Такое не увидишь в коде глазами —
  // всплытие невидимо, — поэтому проверяется отдельно от самого наличия обработчика.
  const withoutStop = /@click="openSenderProfile\(msg\)"[^>]*class="[^"]*text-\[11px\]/
  assert.ok(
    !withoutStop.test(template),
    'у имени автора обработчик без .stop — клик откроет и профиль, и меню сообщения',
  )
})

test('у Вектора и системных сообщений кнопки профиля НЕТ', () => {
  // Отправитель системных реплик — строка 'system', человека за ней нет. Кнопка,
  // открывающая пустоту, хуже её отсутствия: человек жмёт и решает, что подвисло.
  assert.match(
    thread,
    /function canOpenSenderProfile\(msg\)\s*{[^}]*isVector\(msg\)/,
    'canOpenSenderProfile не исключает Вектора — кнопка появится на системных сообщениях',
  )
  assert.match(
    thread,
    /function canOpenSenderProfile\(msg\)\s*{[^}]*msg\.mine/,
    'canOpenSenderProfile не исключает свои сообщения',
  )
  // И обе точки входа обязаны спрашивать разрешение, а не только одна из них.
  const guarded = template.match(/canOpenSenderProfile\(msg\)/g) || []
  assert.ok(
    guarded.length >= 2,
    `условие показа стоит только в ${guarded.length} месте(ах) — аватарка и имя обе должны его спрашивать`,
  )
})

test('клик по ОТМЕТКЕ в тексте по-прежнему ведёт в профиль', () => {
  // Эта половина работала и раньше; тест стоит затем, чтобы переименование общей
  // переменной (`mentionProfileId` → `peerProfileId`) не отломило её молча.
  assert.match(
    thread,
    /mention\[data-mention-uid\]/,
    'разметка отметки потеряла data-mention-uid — клик по упоминанию перестанет работать',
  )
  assert.match(
    thread,
    /peerProfileId\.value = mention\.dataset\.mentionUid/,
    'клик по отметке больше не открывает профиль',
  )
})

test('модалка профиля подключена и получает того, кого выбрали', () => {
  assert.match(
    template,
    /<PeerProfileModal[^>]*:user-id="peerProfileId"/,
    'PeerProfileModal не привязана к peerProfileId — окно не откроется ни по одному из путей',
  )
})

// ────────────────────────────── обратный ход ──────────────────────────────
//
// Сторож, который не проверили откатом, скорее всего не работает — это правило куплено
// четырьмя зелёными версиями подряд при сломанном продукте (pollingRespectsVisibility).
// Здесь мы портим копию файла в памяти и требуем, чтобы проверки это заметили.

test('обратный ход: сторож замечает откат каждой из правок', () => {
  const cases = [
    {
      name: 'аватарку вернули в простой <Avatar> (кнопку убрали)',
      spoil: (s) => s.replace(/<button[^>]*@click="openSenderProfile\(msg\)"/g, '<div'),
      check: (s) => /<button[^>]*@click="openSenderProfile\(msg\)"/.test(s),
    },
    {
      name: 'у имени автора убрали обработчик',
      spoil: (s) => s.replace(/@click\.stop="openSenderProfile\(msg\)"/g, ''),
      check: (s) => /@click\.stop="openSenderProfile\(msg\)"/.test(s),
    },
    {
      name: 'модалку отвязали от выбранного человека',
      spoil: (s) => s.replace(/:user-id="peerProfileId"/g, ':user-id="\'\'"'),
      check: (s) => /<PeerProfileModal[^>]*:user-id="peerProfileId"/.test(s),
    },
    {
      name: 'клик по отметке перестал открывать профиль',
      spoil: (s) => s.replace(/peerProfileId\.value = mention\.dataset\.mentionUid/g, 'return'),
      check: (s) => /peerProfileId\.value = mention\.dataset\.mentionUid/.test(s),
    },
    {
      name: 'условие показа убрали (кнопка появится у Вектора)',
      spoil: (s) => s.replace(/canOpenSenderProfile\(msg\)/g, 'true'),
      check: (s) => ((s.match(/canOpenSenderProfile\(msg\)/g) || []).length >= 2),
    },
  ]
  for (const c of cases) {
    assert.ok(c.check(thread), `проверка «${c.name}» не проходит и на ЦЕЛОМ файле — она сломана`)
    assert.ok(
      !c.check(c.spoil(thread)),
      `откат «${c.name}» прошёл незамеченным — сторож не работает`,
    )
  }
})
