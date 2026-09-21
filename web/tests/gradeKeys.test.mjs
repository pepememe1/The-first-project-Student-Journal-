// gradeKeys.test.mjs — ввод оценки с клавиатуры (просьба тестеров, 20.09.2026).
//
// ━━ ЧТО ЗДЕСЬ ЗАЩИЩАЕТСЯ ━━
// Ошибка в этом правиле ставит НЕ ТУ оценку и делает это молча: журнал выглядит
// заполненным, ячейка не пустая, а балл чужой. Поэтому правило и вынесено из `.vue` —
// внутри компонента его не проверить без браузера, а глазами такое не ловится.
//
// ⚠️ Проверяются ТРИ измерения, и каждое куплено отдельной формулировкой тестера:
// шкала (5-балльная против 100-балльной), раскладка («О и J»), и то, что всё
// остальное игнорируется, а не «как-нибудь» попадает в журнал.
//
// ⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН: убрать карту KEYBOARD — краснеет тест про забытую
// раскладку; убрать проверку `longer` — краснеет тест про сотенную шкалу (там «5»
// применялось бы сразу, и набрать 50 стало бы нельзя).
import { test } from 'node:test'
import assert from 'node:assert/strict'

import { readFileSync } from 'node:fs'

import { letterFor, resolveKey } from '../src/utils/gradeKeys.js'

const FIVE = ['', '2', '3', '4', '5', 'Н', 'Б', 'О']
const HUNDRED = ['', ...Array.from({ length: 101 }, (_, i) => String(i)), 'Н', 'Б', 'О']

test('цифра пятибалльной шкалы ставится сразу', () => {
  for (const d of ['2', '3', '4', '5']) {
    assert.deepEqual(resolveKey(d, { allowed: FIVE }), { kind: 'set', value: d })
  }
})

test('единица и ноль в пятибалльной не значат ничего', () => {
  //Их нет в шкале: «1» в журнале не ставят, а «0» — это не оценка. Раньше нативный
  //`<select>` на такую клавишу выбрал бы первый пункт, начинающийся с неё.
  assert.equal(resolveKey('1', { allowed: FIVE }).kind, 'ignore')
  assert.equal(resolveKey('0', { allowed: FIVE }).kind, 'ignore')
})

test('в сотенной шкале цифра — это начало числа, а не готовая оценка', () => {
  const first = resolveKey('8', { allowed: HUNDRED })
  assert.deepEqual(first, { kind: 'buffer', buffer: '8' },
    'в сотенной шкале «8» применилась сразу — набрать 85 стало невозможно')
  assert.deepEqual(resolveKey('5', { allowed: HUNDRED, buffer: '8' }),
    { kind: 'set', value: '85' })
})

test('сотня набирается целиком', () => {
  assert.deepEqual(resolveKey('1', { allowed: HUNDRED }), { kind: 'buffer', buffer: '1' })
  assert.deepEqual(resolveKey('0', { allowed: HUNDRED, buffer: '1' }),
    { kind: 'buffer', buffer: '10' })
  assert.deepEqual(resolveKey('0', { allowed: HUNDRED, buffer: '10' }),
    { kind: 'set', value: '100' })
})

test('Enter применяет набранное, Escape его отменяет', () => {
  assert.deepEqual(resolveKey('Enter', { allowed: HUNDRED, buffer: '7' }),
    { kind: 'set', value: '7' })
  assert.deepEqual(resolveKey('Escape', { allowed: HUNDRED, buffer: '7' }),
    { kind: 'buffer', buffer: '' })
})

test('забытая раскладка: J ставит «О», Y — «Н»', () => {
  //Прямая формулировка тестера. Палец жмёт клавишу, на которой в ЙЦУКЕН стоит буква.
  assert.deepEqual(resolveKey('j', { allowed: FIVE }), { kind: 'set', value: 'О' })
  assert.deepEqual(resolveKey('y', { allowed: FIVE }), { kind: 'set', value: 'Н' })
  assert.deepEqual(resolveKey(',', { allowed: FIVE }), { kind: 'set', value: 'Б' })
})

test('латиница, похожая начертанием, тоже принимается', () => {
  assert.deepEqual(resolveKey('o', { allowed: FIVE }), { kind: 'set', value: 'О' })
  assert.deepEqual(resolveKey('h', { allowed: FIVE }), { kind: 'set', value: 'Н' })
})

test('кириллица работает в любом регистре', () => {
  assert.deepEqual(resolveKey('н', { allowed: FIVE }), { kind: 'set', value: 'Н' })
  assert.deepEqual(resolveKey('Б', { allowed: FIVE }), { kind: 'set', value: 'Б' })
})

test('буква, которой нет в ЭТОЙ ячейке, игнорируется', () => {
  //У домашнего задания «Б» и «О» нет вовсе: работа делается вне аудитории, и «болел»
  //там не значит ничего. Клавиатура не имеет права ставить то, чего нет в списке —
  //сервер такую строку отвергнет, а человек увидит «оценка не сохранилась».
  const homework = ['', '2', '3', '4', '5', 'Н']
  assert.equal(resolveKey('j', { allowed: homework }).kind, 'ignore')
  assert.deepEqual(resolveKey('y', { allowed: homework }), { kind: 'set', value: 'Н' })
})

test('всё прочее не попадает в журнал', () => {
  for (const key of ['a', 'z', 'ф', 'ы', '/', 'F5', 'Tab', 'ArrowDown', ' ']) {
    assert.equal(resolveKey(key, { allowed: FIVE }).kind, 'ignore',
      `клавиша ${key} что-то поставила в ячейку`)
  }
})

test('Backspace снимает оценку', () => {
  //Иначе поставить можно клавиатурой, а снять — только мышью, и рука тянется к ней
  //ровно в момент исправления ошибки.
  assert.deepEqual(resolveKey('Backspace', { allowed: FIVE }), { kind: 'clear' })
  assert.deepEqual(resolveKey('Delete', { allowed: FIVE }), { kind: 'clear' })
})

test('буква обрывает набор числа', () => {
  //«8» + «Н» — это отметка «Н», а не попытка собрать «8Н».
  assert.deepEqual(resolveKey('y', { allowed: HUNDRED, buffer: '8' }),
    { kind: 'set', value: 'Н' })
})

test('letterFor разводит две карты и не выдумывает третью', () => {
  assert.equal(letterFor('j'), 'О')      //клавиша
  assert.equal(letterFor('o'), 'О')      //начертание
  assert.equal(letterFor('b'), '',
    'латинской «B» назначили «Б» — это угадывание: её двойник в кириллице «В», а не «Б»')
  assert.equal(letterFor('Enter'), '')
})

// ── Клавиатура только на компьютере (уточнение тестеров, 20.09.2026) ────────────────
//
// На телефоне ввода с клавиатуры быть не должно: экранная клавиатура занимает половину
// экрана, а `<select>` там открывается системным барабаном — перехват нажатий отнял бы
// привычный способ и не дал взамен ничего.
//
// ⚠️ Проверяется СВЯЗЬ журнала с общим признаком устройства, а не сам признак: у
// `isHandheld` свои тесты (`haptics.test.mjs`), и повторять их здесь значило бы завести
// вторую копию правила — ровно то, от чего заведён `utils/device.js`.
test('журнал спрашивает про устройство, а не решает сам', () => {
  const src = readFileSync(new URL('../src/pages/teacher/TeacherJournal.vue', import.meta.url), 'utf8')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|\s)\/\/.*$/gm, '')

  assert.match(src, /import\s*\{[^}]*isHandheld[^}]*\}\s*from\s*'@\/utils\/device'/,
    'журнал не спрашивает общий признак устройства — значит завёл свой, и он разойдётся')
  assert.match(src, /isHandheld\(\)/, 'признак импортирован, но не вызван')

  //И признак действительно ГАСИТ обработчик, а не просто лежит рядом.
  const at = src.indexOf('function onCellKey')
  assert.ok(at > 0, 'обработчик клавиш исчез — сторож устарел вместе со страницей')
  const body = src.slice(at, at + 400)
  assert.match(body, /keyboardInput/,
    'обработчик не смотрит на признак устройства: на телефоне клавиатура останется живой')
})

// ── Владение набором в журнале (починка 21.09.2026, два настоящих дефекта) ──────────
//
// Оба жили в ИНТЕГРАЦИИ, а не в правиле, поэтому тесты чистой функции выше их не
// видели: она про «что значит клавиша», а ломалось «чья это клавиша».
//
// ⚠️ Проверка ТЕКСТОВАЯ и это её честная граница: поведение `.vue` без браузера не
// воспроизвести — ровно поэтому правило и вынесено в utils. Сторож ловит ВОЗВРАТ
// дефекта (обе формулировки дословно описывают то, что было), а не проверяет работу.
//
// ⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН: вернуть строковый ключ `${s.student_id || s.surname}` —
// краснеет первый тест; заменить flush при переходе на обнуление буфера — второй.
test('набор принадлежит СТУДЕНТУ, а не его фамилии', () => {
  //У двух полных тёзок без student_id (записи до миграции, ревью J08) строковый ключ
  //совпадал, и цифра, начатая у первого, доклеивалась к цифре второго: «85» уезжало не
  //тому человеку — молча и с правдоподобным видом.
  const src = readFileSync(new URL('../src/pages/teacher/TeacherJournal.vue', import.meta.url), 'utf8')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|\s)\/\/.*$/gm, '')

  assert.doesNotMatch(src, /keyBufferCell/,
    'владелец набора снова строковый ключ — у полных тёзок он совпадёт, и оценка уедет не тому')
  assert.match(src, /owner\.s === s/,
    'владельца набора больше не сверяют по ССЫЛКЕ на студента')
})

test('переход в другую ячейку применяет набранное, а не выбрасывает', () => {
  //Раньше буфер здесь обнулялся, а таймер оставался жить: набранная «8» пропадала
  //молча, стоило нажать клавишу в соседней строке.
  const src = readFileSync(new URL('../src/pages/teacher/TeacherJournal.vue', import.meta.url), 'utf8')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|\s)\/\/.*$/gm, '')

  const at = src.indexOf('function onCellKey')
  assert.ok(at > 0, 'обработчик клавиш исчез — сторож устарел вместе со страницей')
  const head = src.slice(at, at + 600)
  assert.match(head, /!sameCell\([^)]*\)\)\s*flushKeyBuffer\(\)/,
    'при переходе в другую ячейку набранное не применяется — значит теряется молча')
})

test('буквенная шкала набирается своими же буквами', () => {
  //Найдено фаззингом 21.09.2026: во всей шкале «A–F» (`grading.SCALES['letter']`)
  //клавиатура не работала ВООБЩЕ — `letterFor` знает только отметки посещаемости, и
  //нажатие «A» не делало ничего при живом выпадающем списке рядом.
  const LETTER = ['', 'A', 'B', 'C', 'D', 'F', 'Н', 'Б', 'О']
  for (const [key, want] of [['a', 'A'], ['B', 'B'], ['c', 'C'], ['d', 'D'], ['f', 'F']]) {
    assert.deepEqual(resolveKey(key, { allowed: LETTER }), { kind: 'set', value: want },
      `в буквенной шкале клавиша «${key}» не ставит «${want}»`)
  }
  //«E» в этой шкале НЕТ (A, B, C, D, F) — и выдумывать её нельзя.
  assert.equal(resolveKey('e', { allowed: LETTER }).kind, 'ignore')
  //Отметки посещаемости в той же ячейке продолжают работать по картам.
  assert.deepEqual(resolveKey('j', { allowed: LETTER }), { kind: 'set', value: 'О' })
})

test('прямое совпадение НЕ действует на цифры', () => {
  //Иначе в сотенной шкале «5» применялась бы сразу и набрать 50…59 стало бы нельзя —
  //ровно тот дефект, от которого заведён буфер.
  const HUNDRED_ONLY = ['', ...Array.from({ length: 101 }, (_, i) => String(i))]
  assert.deepEqual(resolveKey('5', { allowed: HUNDRED_ONLY }), { kind: 'buffer', buffer: '5' })
})
