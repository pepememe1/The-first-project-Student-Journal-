// cspMeta.test.mjs — CSP должна ехать В САМОМ БАНДЛЕ, а не только в заголовках Caddy.
//
// Заведён 21.08.2026 при разборе безопасности мобильной версии. До него в APK не
// действовало ни одной директивы CSP: заголовок ставит Caddy, а в приложении страницу
// отдаёт локальный сервер Capacitor из бандла (origin https://localhost) — ответы
// нашего сервера и его заголовки к ней отношения не имеют. Заметить это по коду нельзя
// никак: и сайт, и приложение собираются из одного index.html, и на сайте всё честно
// защищено.
//
// ⚠️ Проверяем ИМЕННО меты в исходнике, а не в web/dist: dist не в git, у сборки на
// машине разработчика он может быть старым, и тест краснел бы не по делу.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const WEB = dirname(dirname(fileURLToPath(import.meta.url)))
const html = readFileSync(join(WEB, 'index.html'), 'utf8')

function policy() {
  //⚠️ Значение атрибута берём ТОЛЬКО в двойных кавычках: сама политика полна одинарных
  //('self', 'none'), и класс [^"'] обрывал бы её на первой же — тест «проходил» бы на
  //строке «default-src » и ничего не проверял.
  const m = html.match(/<meta\s+http-equiv="Content-Security-Policy"\s+content="([^"]+)"/i)
  return m ? m[1] : ''
}

test('в index.html есть мета Content-Security-Policy', () => {
  assert.ok(policy(), 'мета CSP пропала — в мобильном приложении политика не действует вовсе')
})

test('директивы, ради которых мета и нужна, на месте', () => {
  const p = policy()
  //Ровно то, что закрывает исполнение постороннего кода. connect-src сюда НЕ входит
  //намеренно: CapacitorHttp уводит fetch/XHR мимо CSP, и требовать его — обманывать
  //себя (см. комментарий в index.html).
  assert.match(p, /(^|;\s*)default-src 'self'/, 'потеряна default-src')
  assert.match(p, /(^|;\s*)script-src 'self'/, "script-src должен быть строго 'self'")
  assert.match(p, /(^|;\s*)object-src 'none'/, 'потеряна object-src')
  assert.match(p, /(^|;\s*)base-uri 'self'/, 'потеряна base-uri')
})

test('в script-src нет послаблений, ради которых всё это теряет смысл', () => {
  const p = policy()
  const scriptSrc = (p.split(';').find((d) => d.trim().startsWith('script-src')) || '')
  assert.ok(!/unsafe-inline/.test(scriptSrc), "script-src 'unsafe-inline' сводит защиту к нулю")
  assert.ok(!/unsafe-eval/.test(scriptSrc), "script-src 'unsafe-eval' сводит защиту к нулю")
})

test('в самом index.html нет inline-скрипта (его же и запрещает политика)', () => {
  //Сборка Vite инлайнов не даёт (проверено на dist), но руками сюда дописать легко —
  //и тогда страница молча перестанет работать в приложении.
  const inline = [...html.matchAll(/<script(?![^>]*\ssrc=)[^>]*>/gi)]
  assert.equal(inline.length, 0, `inline-скрипт в index.html не переживёт script-src 'self': ${inline.map((m) => m[0]).join(' | ')}`)
})

test('мета не строже заголовка Caddy там, где сайту нужно больше', () => {
  //Браузер применяет ПЕРЕСЕЧЕНИЕ политик: если мета забудет разрешить то, что
  //разрешает Caddy, сломается САЙТ, а не приложение. Три места, где это уже нужно.
  const p = policy()
  assert.match(p, /style-src[^;]*'unsafe-inline'/, 'без inline-стилей не работает Tailwind/переменные темы')
  assert.match(p, /img-src[^;]*(https:|static\.klipy\.com)/, 'потеряны картинки Klipy (GIF в мессенджере)')
  assert.match(p, /frame-src[^;]*youtube\.com/, 'потеряны видео-эмбеды белого списка')
})

function directive(name) {
  return (policy().split(';').find((d) => d.trim().startsWith(name)) || '').trim()
}

test('открытый http РАЗРЕШЁН в connect-src — иначе ломается программа на ПК', () => {
  //Урок, купленный прямо в этом заходе (нашёл Полковник). У меты ТРИ потребителя:
  //сайт (https), приложение (https://localhost) и .exe, который раздаёт этот же бандл
  //со СВОЕГО локального сервера, то есть с origin http://127.0.0.1:<порт>. Плюс сервер
  //задаётся в рантайме, и сервер колледжа в своей сети — обычно http://192.168.x.x.
  //Запрет http означал бы, что у такого колледжа перестают ходить ВСЕ запросы —
  //молча, без единой ошибки на экране (консоли у человека за программой нет).
  //Строгость держится не здесь, а в network_security_config.xml мобильного APK.
  const conn = directive('connect-src')
  assert.match(conn, /(^|\s)http:(\s|$)/, 'connect-src без http: обрывает связь у программы и у сервера колледжа в ЛВС')
  assert.match(conn, /(^|\s)ws:(\s|$)/, 'connect-src без ws: рвёт мессенджер в программе на ПК')
  assert.match(conn, /(^|\s)wss:(\s|$)/, 'connect-src без wss: рвёт мессенджер на сайте и в приложении')
})

test('img-src не сужен до своего origin — вложения приезжают с адреса сервера', () => {
  //В приложении страница живёт на https://localhost, а картинки — на адресе сервера,
  //то есть на ЧУЖОМ origin. Сузив до 'self', получим пустые картинки при ответе 200:
  //отказ, которого не видно ни в одном логе.
  const img = directive('img-src')
  assert.match(img, /(^|\s)https:(\s|$)/, "img-src 'self' скроет вложения-картинки в приложении")
})
