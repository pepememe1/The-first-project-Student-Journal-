// Пасхалки и правило «выход из аккаунта — это смена владельца».
//
// ⚠️ Куплено двумя настоящими дефектами (24.08.2026), и оба были НЕМЫМИ:
//   1. Метка аватарки (DOOM/Detroit) нигде не хранилась, зато разыгрывалась заново на
//      каждом монтаже оболочки при шансе 1/1 — то есть каждая новая вкладка выдавала
//      украшение гарантированно. Со стороны: «вышел, закрыл вкладку, а свечение всё то
//      же». Плюс обратная несуразность: после F5 замок броска не давал позвать
//      `afterLogin()`, и украшение ПРОПАДАЛО до конца сессии.
//   2. `gb.egg.tree` — общий ключ на всё устройство. На общем компьютере колледжа
//      студенту Б показывалась короткая реплика, потому что яйцо взял студент А, а
//      ачивку закрывает только полный диалог. Б не мог получить её НИКОГДА и молча.
//
// Поэтому здесь проверяется СВОЙСТВО, а не два конкретных ключа: любое, что пасхалки
// кладут в `localStorage`, обязано либо ключеваться логином, либо стираться при выходе.
// Новый ключ, забытый в обоих местах, покраснеет сам.
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join, dirname } from 'node:path'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const STORE = readFileSync(join(ROOT, 'src/stores/easterEggs.js'), 'utf8')
const SHELL = readFileSync(join(ROOT, 'src/layouts/AppShell.vue'), 'utf8')
const EASTER = join(ROOT, 'src/components/easter')

// ⚠️ Комментарии срезаем ВСЕГДА. На этом проекте сторожа уже трижды попадались на том,
// что искомая строка нашлась в объяснении рядом, а не в коде.
const code = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '')

/** Тело `reset()` — то, что выполняется при выходе. */
function resetBody() {
  const src = code(STORE)
  const i = src.indexOf('function reset(')
  assert.notEqual(i, -1, 'в сторе нет reset() — выход перестал что-либо чистить')
  return src.slice(i, src.indexOf('\n  }', i))
}

test('всё, что пасхалки пишут в localStorage, ключевано логином или стирается при выходе', () => {
  const reset = resetBody()
  const files = [['stores/easterEggs.js', STORE],
                 ...readdirSync(EASTER).filter((f) => f.endsWith('.vue'))
                   .map((f) => [f, readFileSync(join(EASTER, f), 'utf8')])]

  const bad = []
  for (const [name, raw] of files) {
    const src = code(raw)
    for (const m of src.matchAll(/localStorage\.setItem\(\s*([^,]+?)\s*,/g)) {
      const key = m[1].trim()

      // Ключ-выражение (`avatarKey()`, `eggKey`) — разворачиваем до объявления в этом
      // же файле и требуем, чтобы в нём участвовал логин.
      const id = key.replace(/\(\)$/, '')
      if (/^[A-Za-z_$][\w$]*$/.test(id)) {
        // ⚠️ БЕЗ шаблонной строки с `\s`/`\b`: в ней `\b` — это символ
        // backspace, а не граница слова, и регулярка молча перестаёт совпадать.
        // На этом уже попадался сторож в соседнем файле.
        const at = ['function ', 'const ', 'let ']
          .map((kw) => src.indexOf(kw + id)).filter((n) => n !== -1).sort((a, b) => a - b)[0]
        const found = at === undefined ? null : [src.slice(at, at + 240)]
        assert.ok(found, `${name}: не найдено объявление ключа ${id}`)
        if (/login/.test(found[0])) continue
        bad.push(`${name}: ключ ${id} не содержит логина`)
        continue
      }

      // Строковый литерал — тогда его обязан стирать выход.
      const lit = key.match(/^['"`]([^'"`]+)/)
      assert.ok(lit, `${name}: непонятный ключ ${key}`)
      const prefix = lit[1]
      const cleared = [...reset.matchAll(/startsWith\(\s*'([^']+)'/g)].map((r) => r[1])
        .some((p) => prefix.startsWith(p))
        || reset.includes(`removeItem('${prefix}`)
      if (!cleared) bad.push(`${name}: ключ '${prefix}' не ключеван логином и не стирается в reset()`)
    }
  }
  assert.deepEqual(bad, [], bad.join('\n'))
})

test('выход забывает взятое яйцо дерева и снимает замок броска', () => {
  // Обратный ход: убери любую из двух строк в reset() — тест краснеет.
  const reset = resetBody()
  assert.match(reset, /gb\.egg\.tree/, 'выход не забывает взятое яйцо дерева')
  assert.match(reset, /gb\.egg\.login:/, 'выход не снимает замок броска')
  // ⚠️ Метки аватарки тут быть НЕ ДОЛЖНО: клиент её не хранит вовсе. Появится ключ —
  // значит кто-то снова завёл клиентскую память, и вернётся дефект с протухшим следом.
  assert.doesNotMatch(reset, /gb\.egg\.avatar/,
    'клиент снова хранит метку аватарки — след протухнет раньше токена')
})

test('клиент НЕ хранит метку аватарки — её всегда выдаёт сервер', () => {
  // 🔥 Куплено находкой Полковника. Клиентская память о метке выглядела безобидно, но
  // след срабатывания живёт час, а токен пять: восстановленная из памяти метка след не
  // обновляла, и один неудавшийся `claim` означал, что ачивку до конца дня уже не
  // забрать — молча. Сервер выдаёт метку каждый раз и каждый раз обновляет след.
  const src = code(STORE) + code(readFileSync(join(ROOT, 'src/layouts/AppShell.vue'), 'utf8'))
  assert.doesNotMatch(src, /localStorage\.(get|set)Item\(\s*avatarKey/,
    'метка аватарки снова кладётся в localStorage')
  assert.doesNotMatch(src, /gb\.egg\.avatar/, 'снова заведён клиентский ключ метки')
})

test('перезагрузка гасит бросок сцены, но НЕ запрос метки', () => {
  // Раньше замок стоял вокруг всего `afterLogin()`, и после F5 клиент не спрашивал
  // сервер ни о чём: вместе с броском пропадала метка аватарки, хотя она не бросок.
  // Одно и то же украшение то появлялось само, то исчезало само.
  const src = code(SHELL)
  assert.match(src, /easter\.afterLogin\(\s*scene\s*\)/,
    'оболочка зовёт afterLogin() без признака «бросок нужен?»')
  const lock = src.indexOf('gb.egg.login:')
  const call = src.indexOf('easter.afterLogin(')
  assert.ok(lock !== -1 && call > lock,
    'вызов не после замка — признак сцены не успеет посчитаться')
  // Ключевое: под замком стоит ТОЛЬКО снятие признака, а не выход из функции.
  const between = src.slice(lock, call)
  assert.doesNotMatch(between, /\breturn\b/,
    'замок снова делает ранний выход — после F5 метка не приедет')
})

test('afterLogin умеет не просить бросок сцены', () => {
  const src = code(STORE)
  assert.match(src, /async function afterLogin\(scene = true\)/,
    'у afterLogin нет параметра сцены')
  assert.match(src, /onLogin\(scene \? \{\} : \{ scene: 0 \}\)/,
    'afterLogin не передаёт scene=0 после перезагрузки')
})
