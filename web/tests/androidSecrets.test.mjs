// androidSecrets.test.mjs — в отслеживаемых файлах android-сборки нет секретов.
//
// Заведён 21.08.2026 при разборе безопасности мобильной версии. Находка была не в
// значении, а в ИНСТРУКЦИИ: `web/android/gradle.properties` лежит в git, а комментарий
// внутри него утверждал «держим вне git вместе с настройками подписи». Файл, которому
// приписана роль хранилища негитовых значений, рано или поздно получает настоящий
// секрет — по написанному, без злого умысла и без единого предупреждения.
//
// Проверяем СВОЙСТВО («в этом файле нет ничего, похожего на секрет»), а не список
// разрешённых ключей: слепок краснел бы на каждой законной настройке сборки и его
// научились бы обновлять не глядя — то есть он перестал бы защищать.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const WEB = dirname(dirname(fileURLToPath(import.meta.url)))     // .../web
const ROOT = dirname(WEB)

//Слова в ИМЕНИ настройки, после которых значение — не для git. `keyAlias`/`storeFile`
//включены не как секреты сами по себе, а как признак, что настройки подписи переехали
//не туда (пароли ходят с ними в одном файле).
//
//⚠️ ПЕРВАЯ ВЕРСИЯ ЭТОГО СПИСКА ПРОПУСКАЛА ГЛАВНЫЙ СЛУЧАЙ. В ней стояло `access[_-]?token`
//и `api[_-]?key` — то есть голое `TOKEN` и голое `KEY` не ловились, и строка
//`RUSTORE_SERVICE_TOKEN=eyJ…` (ровно то, что комментарий в gradle.properties называет
//запретным) давала ЗЕЛЁНЫЙ тест. Поймано Полковником; мой собственный обратный ход
//этого не увидел, потому что я подложил строку со словом «secret» в ЗНАЧЕНИИ и
//покраснело по другой причине. Урок ровно тот, что записан в CLAUDE.md: обратный ход
//надо делать тем случаем, ради которого сторож заведён, а не похожим на него.
const FORBIDDEN_NAME = /(password|passwd|secret|token|credential|private|keystore|signing|cert|api[_-]?key|keyAlias|keyPassword|storeFile|storePassword|\bkey\b)/i

//Значение, которое само себя выдаёт: JWT начинается с `eyJ` (base64 от `{"`). Ловит
//случай, когда настройку назвали безобидно (`RUSTORE_EXTRA=eyJ…`).
const LOOKS_LIKE_JWT = /^eyJ[A-Za-z0-9_-]{10,}/

function assertNoSecrets(relPath) {
  const full = join(ROOT, relPath)
  if (!existsSync(full)) return          //нет файла — нечего проверять
  const lines = readFileSync(full, 'utf8').split(/\r?\n/)
  for (const [i, line] of lines.entries()) {
    const t = line.trim()
    if (!t || t.startsWith('#') || t.startsWith('//')) continue   //комментарии — можно
    //`ключ=значение` (.properties) → судим по ИМЕНИ: слово «token» в значении бывает
    //законным. Строка без «=» (.gradle) → судим целиком: там `storePassword "…"`.
    const eq = t.indexOf('=')
    const name = eq > 0 ? t.slice(0, eq) : t
    const value = eq > 0 ? t.slice(eq + 1).trim() : ''
    assert.ok(!FORBIDDEN_NAME.test(name),
      `${relPath}:${i + 1} — похоже на секрет в файле, который лежит в git: «${t}»`)
    assert.ok(!LOOKS_LIKE_JWT.test(value),
      `${relPath}:${i + 1} — значение выглядит как JWT, а файл лежит в git: «${t}»`)
  }
}

test('gradle.properties не содержит секретов (он в git)', () => {
  assertNoSecrets('web/android/gradle.properties')
})

test('корневой build.gradle и variables.gradle не содержат секретов', () => {
  assertNoSecrets('web/android/build.gradle')
  assertNoSecrets('web/android/variables.gradle')
})

test('.gitignore закрывает ключ подписи и его пароли', () => {
  const ignore = readFileSync(join(ROOT, '.gitignore'), 'utf8')
  //Именно эти две строки: потеря ключа = невозможность обновлять приложение в RuStore,
  //а утечка = чужие сборки под нашим именем.
  assert.match(ignore, /^\*\.keystore\s*$/m, '.gitignore потерял правило *.keystore')
  assert.match(ignore, /^keystore\.properties\s*$/m, '.gitignore потерял правило keystore.properties')
})

test('пароли подписи читаются из файла ВНЕ git, а не зашиты в build.gradle', () => {
  const gradle = readFileSync(join(ROOT, 'web/android/app/build.gradle'), 'utf8')
  //Значения обязаны браться из keystoreProperties, а не стоять литералом.
  assert.match(gradle, /keystoreProperties\['storePassword'\]/,
    'пароль хранилища больше не читается из keystore.properties')
  assert.match(gradle, /keystoreProperties\['keyPassword'\]/,
    'пароль ключа больше не читается из keystore.properties')
  //Литерал вида storePassword "что-то" — это зашитый в git пароль.
  assert.ok(!/store[Pp]assword\s+["']/.test(gradle),
    'в build.gradle появился пароль литералом')
  assert.ok(!/key[Pp]assword\s+["']/.test(gradle),
    'в build.gradle появился пароль литералом')
})
