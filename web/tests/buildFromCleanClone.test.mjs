// buildFromCleanClone.test.mjs — сборка обязана воспроизводиться из ЧИСТОГО клона.
//
// 🔥 Заведён по настоящему дефекту (29.08.2026). `vite.config.js` импортирует
// `./build/stripHtmlComments.js`, а строка `build/` в корневом `.gitignore` —
// заведённая для питоновских каталогов сборки — глотала этот каталог целиком.
// Файл не был в git НИ РАЗУ: на машине автора он лежал локально и всё работало,
// а на чистом клоне `npm run build` падал «Cannot find module».
//
// Заметить это было нечем: сборка на рабочей машине зелёная, тесты зелёные,
// сайт на бою живой (его собирали там же, где файл уцелел). Увидел только CI —
// и то потому, что мы наконец прочитали, почему он красный.
//
// ⚠️ Проверяем СВОЙСТВО, а не конкретный файл: любой новый локальный модуль,
// который затянет в сборку конфиг, попадёт под ту же проверку. Сверять список
// со снимком нельзя — снимок краснеет на каждом законном добавлении и учит
// «просто обновить ожидание», то есть ровно тому, от чего защищает.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, existsSync } from 'node:fs'
import { dirname, resolve, relative, sep } from 'node:path'
import { fileURLToPath } from 'node:url'
import { execFileSync } from 'node:child_process'

const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')

/** Относительные импорты файла: `import x from './y'`, `export * from '../z'`. */
function relativeImports(code) {
  const out = []
  const re = /(?:^|[\s;])(?:import|export)\b[^'"]*?from\s*['"](\.[^'"]+)['"]/g
  let m
  while ((m = re.exec(code)) !== null) out.push(m[1])
  return out
}

/** Транзитивное замыкание локальных импортов от точки входа. */
function localClosure(entry) {
  const seen = new Set()
  const queue = [entry]
  while (queue.length) {
    const file = queue.pop()
    if (seen.has(file) || !existsSync(file)) continue
    seen.add(file)
    for (const spec of relativeImports(readFileSync(file, 'utf8'))) {
      let target = resolve(dirname(file), spec)
      if (!existsSync(target)) {
        //без расширения — как его дописал бы сборщик
        for (const ext of ['.js', '.mjs', '.cjs', '/index.js']) {
          if (existsSync(target + ext)) {
            target += ext
            break
          }
        }
      }
      queue.push(target)
    }
  }
  seen.delete(entry)
  return [...seen]
}

/** Лежит ли файл в git. Именно git, а не файловая система — в этом весь смысл. */
function trackedByGit(absPath) {
  try {
    execFileSync('git', ['ls-files', '--error-unmatch', '--', absPath], {
      cwd: webRoot,
      stdio: 'pipe',
    })
    return true
  } catch {
    return false
  }
}

test('всё, что тянет сборка веба, лежит в git', () => {
  const entry = resolve(webRoot, 'vite.config.js')
  assert.ok(existsSync(entry), 'нет web/vite.config.js — проверять нечего')

  const deps = localClosure(entry)
  //Само наличие связей важно: пустое замыкание означало бы, что регулярка
  //перестала находить импорты, и тест молча превратился бы в заглушку.
  assert.ok(
    deps.length > 0,
    'разбор импортов ничего не нашёл — сторож перестал сторожить, чинить его, а не сборку',
  )

  const missing = deps
    .filter((f) => !trackedByGit(f))
    .map((f) => relative(webRoot, f).split(sep).join('/'))

  assert.deepEqual(
    missing,
    [],
    'эти файлы нужны сборке, но их нет в git — на чистом клоне `npm run build` упадёт:\n  ' +
      missing.join('\n  ') +
      '\nПроверь .gitignore: правило `build/` уже проглатывало `web/build/` целиком.',
  )
})
