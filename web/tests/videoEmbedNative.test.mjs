// videoEmbedNative.test.mjs — ГЕЙТ встроенного плеера: внутри мобильного приложения
// <iframe> с чужим видеохостингом не рендерится вовсе.
//
// Почему это сторож, а не косметика. В Android-обёртке нативные мосты вешаются через
// `addJavascriptInterface` (MainActivity.java) — у этого метода НЕТ привязки к origin,
// поэтому Google и завела отдельный `addWebMessageListener` с `allowedOriginRules`.
// CSP на приложение не действует: страница отдаётся из бандла (https://localhost), а
// заголовки Caddy туда не доезжают. Значит внутри APK встроенный чужой фрейм — это
// выданная наружу возможность, которую мы никому давать не собирались: за мостом лежат
// токен устройства (`getToken`), текст виджета и — главное — `setEndpoint()`, адрес,
// по которому виджет рабочего стола потом сам ходит за расписанием МЕСЯЦАМИ, без
// токена и без запущенного приложения.
//
// Обратный ход (обязателен, §«обратный ход у каждого сторожа»): снять `v-if` с iframe
// в ChatThread.vue — тесты краснеют; заменить гейт на `true` — краснеют; убрать запасную
// карточку «смотреть на хостинге» — краснеют (в приложении видео пропало бы молча).
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { embedMode } from '../src/utils/videoEmbed.js'

const SRC = new URL('../src/', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1')

function walk(dir, acc = []) {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) walk(full, acc)
    else if (/\.(vue|js)$/.test(name)) acc.push(full)
  }
  return acc
}

test('в мобильном приложении встраивания нет — только ссылка', () => {
  assert.equal(embedMode(true), 'link')
})

test('в браузере плеер остаётся встроенным', () => {
  assert.equal(embedMode(false), 'iframe')
})

test('признак не передан — считаем, что мы в приложении (отказ в безопасную сторону)', () => {
  // Ошибка вызова не должна ОТКРЫВАТЬ дверь: пропущенный аргумент обязан вести к
  // более осторожному поведению, а не к менее.
  assert.equal(embedMode(), 'link')
  assert.equal(embedMode(undefined), 'link')
  assert.equal(embedMode(null), 'link')
})

test('ЛЮБОЙ <iframe> в разметке SPA стоит под гейтом videoIframeAllowed', () => {
  // Проверяем СВОЙСТВО, а не список файлов: новый встроенный фрейм, добавленный где
  // угодно завтра, обязан пройти через тот же гейт — иначе тест краснеет сразу.
  const offenders = []
  for (const file of walk(SRC)) {
    // ⚠️ Комментарии срезаем: сторож ловил слово «iframe» в ОБЪЯСНЕНИИ рядом с кодом
    // и краснел на файле, где никакого фрейма нет. Это наша давняя ловушка — искомая
    // строка нашлась в прозе, — и здесь она делала сторожа шумным, то есть его начали
    // бы обходить. Проверять надо КОД.
    const text = readFileSync(file, 'utf8')
      .replace(/\/\*[\s\S]*?\*\//g, '')
      .replace(/^\s*\/\/.*$/gm, '')
      .replace(/<!--[\s\S]*?-->/g, '')
    for (const tag of text.matchAll(/<iframe\b[^>]*>/g)) {
      if (!/v-if="videoIframeAllowed"/.test(tag[0])) offenders.push(file)
    }
  }
  assert.deepEqual(offenders, [], `<iframe> без гейта в: ${offenders.join(', ')}`)
})

test('гейт вычисляется из embedMode(isNativeApp()), а не из собственного признака', () => {
  // Второй признак «мы в приложении» разъехался бы с api/server.js — а расходятся такие
  // копии молча и именно в сторону «дверь снова открыта».
  const text = readFileSync(join(SRC, 'components/messenger/ChatThread.vue'), 'utf8')
  assert.ok(/videoIframeAllowed\s*=\s*computed\(\(\)\s*=>\s*embedMode\(isNativeApp\(\)\)\s*===\s*'iframe'\)/.test(text),
    'гейт должен считаться из общего признака натива, а не задаваться отдельно')
})

test('в приложении вместо плеера остаётся карточка «смотреть на хостинге»', () => {
  // Без запасной ветки ролик в приложении пропал бы БЕЗ СЛЕДА — со стороны это
  // читается как «сообщение пришло пустым», то есть как поломка мессенджера.
  const text = readFileSync(join(SRC, 'components/messenger/ChatThread.vue'), 'utf8')
  assert.ok(/<iframe[\s\S]{0,900}?v-else[\s\S]{0,900}?openExternalVideo/.test(text),
    'у гейта нет ветки v-else с openExternalVideo — в приложении видео исчезнет молча')
})

test('чужой origin не втаскивается в страницу МИМО разметки', () => {
  // ⚠️ Граница сторожа выше названа честно: он держит СТАТИЧЕСКИЙ тег в файлах SPA.
  // Фрейм, собранный из JS (`document.createElement('iframe')`), и теги <embed>/<object>
  // прошли бы мимо него с нулём падений — а для нативной оболочки это ровно тот же
  // чужой контекст исполнения рядом с мостами без origin-привязки (см. embedMode).
  // Сегодня таких мест в SPA нет ни одного; сторож не даёт им завестись молча.
  const offenders = []
  for (const file of walk(SRC)) {
    const text = readFileSync(file, 'utf8')
    if (/createElement\(\s*['"`](iframe|embed|object)['"`]/i.test(text)) offenders.push(file + ': createElement')
    if (/<(embed|object)\b/i.test(text)) offenders.push(file + ': тег')
  }
  assert.deepEqual(offenders, [],
    'чужой origin мимо гейта: ' + offenders.join(', ') +
    '. Нужен фрейм — заводи его через videoIframeAllowed, а не в обход.')
})
