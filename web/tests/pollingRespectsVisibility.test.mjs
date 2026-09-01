/**
 * pollingRespectsVisibility.test.mjs — ОПРОС НЕ ХОДИТ В СЕТЬ, ПОКА ЭКРАНА НЕ ВИДНО.
 *
 * ━━ ЗАЧЕМ ━━
 * В мобильном приложении таймеры WebView продолжают тикать после сворачивания: телефон
 * лежит в кармане с погашенным экраном, а мы каждые несколько секунд будим радиомодуль.
 * Это самый дорогой для батареи класс ошибок в продукте, и он невидим — приложение
 * работает правильно, просто телефон садится быстрее, и связать это с конкретным экраном
 * человек не может.
 *
 * 01.09.2026 таких мест нашлось три: заявки на устройства и мониторинг (по 5 с) и
 * подтверждение устройства (4 с). Ни одно не смотрело на `document.hidden`.
 *
 * ━━ ЧТО ПРОВЕРЯЕТСЯ ━━
 * Свойство: если в файле есть `setInterval`, внутри которого идёт обращение к сети, то в
 * том же файле обязана быть проверка видимости. Это грубая эвристика, и она намеренно
 * такая: точный разбор потребовал бы разбирать AST и всё равно ошибался бы, а цена
 * ложного срабатывания здесь — одна строка `if (document.hidden) return`, которая ничего
 * не портит.
 *
 * ⚠️ Таймеры БЕЗ сети (обратный отсчёт, часы, анимация) под правило не подпадают: они
 * ничего не будят, а гасить их по видимости — забота самого экрана.
 */
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'

const SRC = new URL('../src/', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1')

//Пасхалки и экраны активностей крутят таймеры анимации и обратного отсчёта — сети там
//нет по построению, а сами эффекты живут ровно пока открыт экран.
const SKIP = ['components\\easter', 'components/easter', 'components\\activity', 'components/activity']

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) walk(p, out)
    else if (/\.(vue|js)$/.test(name)) out.push(p)
  }
  return out
}

function code(path) {
  return readFileSync(path, 'utf8')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^\s*\/\/.*$/gm, '')
    .replace(/<!--[\s\S]*?-->/g, '')
}

/**
 * Аргументы каждого `setInterval(...)` — РОВНО до парной закрывающей скобки.
 *
 * ⚠️ Считаем скобки, а не «берём N символов вперёд». Первая версия хватала 400 символов
 * после вызова — и захватывала СОСЕДНИЙ код, в том числе обработчик `visibilitychange`,
 * стоящий строкой ниже. Сторож оставался зелёным на сломанном продукте дважды подряд, и
 * оба раза это поймал обратный ход, а не чтение кода.
 */
function intervalBodies(src) {
  const out = []
  let at = 0
  for (;;) {
    const i = src.indexOf('setInterval(', at)
    if (i < 0) break
    let depth = 0
    let end = i
    for (let j = i + 'setInterval'.length; j < src.length; j++) {
      const ch = src[j]
      if (ch === '(') depth++
      else if (ch === ')') {
        depth--
        if (depth === 0) { end = j; break }
      }
    }
    out.push(src.slice(i, end > i ? end + 1 : Math.min(src.length, i + 200)))
    at = i + 12
  }
  return out
}

//Признаки похода в сеть внутри таймера.
//⚠️ БЕЗ `\b` перед `Api`: клиенты называются `adminApi`, `messengerApi`, `connectApi` —
//перед «Api» стоит буква, границы слова там нет, и с `\b` не совпадало НИ ОДНО реальное
//обращение к серверу. Из-за этого сторож пропускал настоящее нарушение и оставался
//зелёным — поймано обратным ходом, а не чтением.
const NETWORK = /(Api\.|\bapi\.|fetch\(|axios|\.get\(|\.post\(|\bload\(|\btick\(|\brefresh\()/
//Колбэк, переданный ССЫЛКОЙ: `setInterval(load, 5000)`. Имя запоминаем, чтобы найти тело.
const BY_REFERENCE = /^setInterval\(\s*([A-Za-z_$][\w$]*)\s*,/
//Проверка видимости в любой из принятых в продукте форм.
const GUARD = /document\.hidden|isHidden|pageVisible/

/**
 * Тело функции по имени: `function name(…) {…}`, `const name = () => {…}`,
 * `async function name(…)`. Возвращает null, если определения в этом файле нет.
 *
 * ⚠️ Скобки считаем, а не берём «N символов»: на этом сторож уже дважды оставался
 * зелёным при сломанном продукте, захватывая соседний код вместе с его проверками.
 */
function fnBody(src, name) {
  const decl = new RegExp(
    `(?:async\\s+)?function\\s+${name}\\s*\\(|` +
      `(?:const|let|var)\\s+${name}\\s*=\\s*(?:async\\s*)?\\(`,
  )
  const m = decl.exec(src)
  if (!m) return null
  const open = src.indexOf('{', m.index)
  if (open < 0) return null
  let depth = 0
  for (let j = open; j < src.length; j++) {
    if (src[j] === '{') depth++
    else if (src[j] === '}') {
      depth--
      if (depth === 0) return src.slice(open, j + 1)
    }
  }
  return src.slice(open)
}

test('каждый сетевой опрос смотрит на видимость экрана', () => {
  const offenders = []
  for (const p of walk(SRC)) {
    const rel = p.slice(SRC.length)
    if (SKIP.some((s) => rel.includes(s))) continue
    const src = code(p)
    const bodies = intervalBodies(src)
    if (!bodies.length) continue
    //⚠️ Проверяем ТЕЛО таймера, а не весь файл. Первая версия искала `document.hidden`
    //где угодно в файле — и оставалась зелёной на сломанном продукте: в `onUnmounted`
    //есть `removeEventListener('visibilitychange', …)`, и этого хватало, чтобы сторож
    //счёл проверку существующей. Поймано собственным обратным ходом.
    const blind = bodies.filter((b) => {
      if (GUARD.test(b)) return false
      //🔥 КОЛБЭК, ПЕРЕДАННЫЙ ССЫЛКОЙ, НАДО РАЗВЕРНУТЬ — это третья попытка написать
      //сторож правильно, и первые две пропускали РОВНО ТУ форму, в которой дефект и был
      //написан. `setInterval(load, 5000)` не содержит ни признаков сети, ни проверки
      //видимости: всё интересное лежит в теле `load`. Считать такой таймер безопасным
      //нельзя, но и объявлять нарушением сразу — тоже: половина таймеров в продукте
      //ничего не грузит (окно офлайн-сессии, часы), и ложные срабатывания заставили бы
      //«просто добавить проверку» туда, где она бессмысленна.
      const ref = b.match(BY_REFERENCE)
      if (ref) {
        const fn = fnBody(src, ref[1])
        //Определения не нашли (импорт из другого модуля) — не выдумываем нарушение.
        if (!fn) return false
        return NETWORK.test(fn) && !GUARD.test(fn)
      }
      return NETWORK.test(b)
    })
    if (blind.length) offenders.push(rel)
  }
  assert.deepEqual(
    offenders,
    [],
    'Опрос ходит в сеть, не проверяя, видит ли его человек. В свёрнутом приложении ' +
      'таймеры WebView продолжают тикать и будят радиомодуль при погашенном экране. ' +
      'Добавьте `if (document.hidden) return` в тик и обновление по `visibilitychange`.\n' +
      offenders.join('\n'),
  )
})

test('правило записано там, где его прочитают', () => {
  //Сторож без объяснения превращается в препятствие: следующий человек обойдёт его,
  //переименовав переменную. Причина должна лежать рядом с кодом.
  const shell = readFileSync(new URL('../src/layouts/AppShell.vue', import.meta.url), 'utf8')
  assert.match(
    shell,
    /свёрнутой вкладке|document\.hidden/,
    'из оболочки пропало объяснение, почему опрос молчит в скрытой вкладке',
  )
})
