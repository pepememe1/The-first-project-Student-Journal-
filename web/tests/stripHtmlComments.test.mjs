/**
 * stripHtmlComments.test.mjs — пояснения из index.html не уезжают в бой.
 *
 * Комментарии в `web/index.html` подробные и содержательные: блок про CSP объясняет,
 * почему политика продублирована метой, блок про viewport — почему запрещено
 * масштабирование. Команде это нужно; постороннему, открывшему F12, — нет (вопрос
 * Ярослава 28.08.2026: «там даже есть комменты про CSP и тд»). Не дыра сама по себе, но
 * бесплатную подсказку об устройстве защиты отдавать незачем.
 *
 * ⚠️ Тест зовёт ФУНКЦИЮ ПРОДУКТА, а не повторяет регулярку у себя: копия сверяла бы
 * копию с копией и пережила бы любую правку плагина.
 */
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import plugin, { stripComments } from '../build/stripHtmlComments.js'

const INDEX = fileURLToPath(new URL('../index.html', import.meta.url))

test('из настоящего index.html комментарии исчезают полностью', () => {
  const src = readFileSync(INDEX, 'utf8')
  //Обратный ход: в исходнике комментарии ЕСТЬ. Если их однажды не станет, тест ниже
  //позеленеет сам собой и перестанет что-либо проверять — ловим это прямо здесь.
  assert.ok(src.includes('<!--'), 'в index.html не осталось комментариев — тест выродился')
  assert.ok(src.includes('CSP'), 'блок про CSP пропал из index.html — проверять больше нечего')

  const out = stripComments(src)
  assert.equal(out.includes('<!--'), false, 'комментарий уцелел и уедет в бой')
  assert.equal(out.includes('CSP ЖИВЁТ ЗДЕСЬ'), false, 'пояснение про CSP уцелело')
})

test('сама политика CSP остаётся — вырезаются пояснения, а не защита', () => {
  //Самая опасная ошибка здесь — снести вместе с комментариями META-тег политики: сайт
  //продолжит работать, а в мобильном приложении CSP не будет действовать вовсе (в APK
  //заголовки Caddy до страницы не доходят, там работает только мета).
  const out = stripComments(readFileSync(INDEX, 'utf8'))
  assert.ok(out.includes('Content-Security-Policy'), 'мета CSP вырезана вместе с пояснениями')
  assert.ok(out.includes('name="viewport"'), 'мета viewport вырезана вместе с пояснениями')
})

test('условные комментарии IE не трогаем — они исполняемые', () => {
  const html = '<!--[if IE]><p>старый браузер</p><![endif]--><!-- пояснение -->'
  const out = stripComments(html)
  assert.ok(out.includes('[if IE]'), 'условный комментарий вырезан — это уже смена поведения')
  assert.equal(out.includes('пояснение'), false, 'обычный комментарий уцелел')
})

test('плагин работает только на сборке, а в dev пояснения остаются', () => {
  //Иначе отлаживать разметку пришлось бы по файлу без единого объяснения.
  const p = plugin()
  assert.equal(p.apply, 'build')
  assert.equal(p.name, 'gb-strip-html-comments')
  assert.equal(p.transformIndexHtml('<!-- x -->a'), 'a')
})
