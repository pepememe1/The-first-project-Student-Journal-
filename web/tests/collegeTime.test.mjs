// collegeTime.test.mjs — часы колледжа на клиенте и проверка «разных часовых поясов».
//
// Просьба преподавателей колледжа (15.10.2026): проверить, как журнал ведёт себя у людей
// в разных часовых поясах. Здесь пояс УСТРОЙСТВА переключается прямо в процессе
// (`process.env.TZ`), и одни и те же моменты обязаны давать одни и те же числа, часы и
// сроки — те, что на часах в Улан-Удэ.
//
// ⚠️ Переменная TZ при ЗАПУСКЕ node на Windows работает только для «UTC» — «Нью-Йорк»
// молча остаётся поясом машины, и такой прогон ничего не доказывает (поймано 15.10.2026).
// Поэтому пояс меняется изнутри, а первой проверкой стоит «смещение действительно
// сменилось»: без неё тест был бы зелёным и на неработающем переключении.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import process from 'node:process'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import {
  COLLEGE_UTC_OFFSET_MIN, collegeParts, collegeDayKey, collegeDdmmyyyy, collegeHhmm,
  formatCollege, fromCollegeWall, fromCollegeInput, toCollegeInput, addDays, collegeDayDiff,
} from '../src/utils/collegeTime.js'
import { deadlineState, timeline } from '../src/utils/tracker.js'
import { freshness } from '../src/utils/freshness.js'
import { lessonDateIssue } from '../src/utils/lessonChecks.js'
import { DICT_FILES } from './_dict.mjs'

test('смещение совпадает с серверным college_clock.py', () => {
  const py = readFileSync(new URL('../../college_clock.py', import.meta.url), 'utf8')
  const m = /^UTC_OFFSET_H = (\d+)$/m.exec(py)
  assert.ok(m, 'в college_clock.py не найдено UTC_OFFSET_H')
  assert.equal(COLLEGE_UTC_OFFSET_MIN, Number(m[1]) * 60)
})

// 16.10.2026 00:30 в Улан-Удэ = 15.10 16:30 UTC = 15.10 19:30 в Москве.
const MIDNIGHT = new Date('2026-10-15T16:30:00Z')

const ZONES = {
  'Asia/Irkutsk': -480, 'Europe/Moscow': -180, 'America/New_York': 240,
  'Asia/Vladivostok': -600, UTC: 0,
}

for (const [zone, offset] of Object.entries(ZONES)) {
  test(`устройство в поясе ${zone}: числа и часы — колледжа`, () => {
    const before = process.env.TZ
    process.env.TZ = zone
    try {
      assert.equal(MIDNIGHT.getTimezoneOffset(), offset, `пояс ${zone} не включился — проверка была бы слепой`)

      assert.equal(collegeDayKey(MIDNIGHT), '2026-10-16')
      assert.equal(collegeDdmmyyyy(MIDNIGHT), '16.10.2026')
      assert.equal(collegeHhmm(MIDNIGHT), '00:30')
      assert.equal(collegeParts(MIDNIGHT).weekday, 5, 'пятница')
      const label = formatCollege(MIDNIGHT, 'ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
      assert.ok(label.includes('16.10') && label.includes('00:30'), label)

      //Поле напоминания: «10:00» — это десять утра в Улан-Удэ.
      assert.equal(fromCollegeInput('2026-10-17T10:00').toISOString(), '2026-10-17T02:00:00.000Z')
      assert.equal(toCollegeInput(new Date('2026-10-17T02:00:00Z')), '2026-10-17T10:00')

      //Срок трекера «до 18:00» наступает в 18:00 по Улан-Удэ — у всех одновременно.
      const task = { deadline: '2026-10-20T18:00' }
      assert.equal(deadlineState(task, new Date('2026-10-20T09:59:00Z')), 'today')
      assert.equal(deadlineState(task, new Date('2026-10-20T10:01:00Z')), 'overdue')
      //Срок без времени — до конца дня в Улан-Удэ.
      assert.equal(deadlineState({ deadline: '2026-10-20' }, new Date('2026-10-20T15:58:00Z')), 'today')
      assert.equal(deadlineState({ deadline: '2026-10-20' }, new Date('2026-10-20T16:01:00Z')), 'overdue')

      //Шкала сроков: «сегодня» — день колледжа.
      const tl = timeline([{ id: 'a', number: 1, deadline: '2026-10-16' }], MIDNIGHT)
      assert.equal(tl.rows[0].from, tl.today, 'срок «16-го» обязан стоять в сегодняшнем столбце')

      //«Обновлено вчера в 22:00»: 22:00 15-го и 00:30 16-го по Улан-Удэ.
      assert.deepEqual(freshness(Date.parse('2026-10-15T14:00:00Z'), MIDNIGHT.getTime()),
        { kind: 'yesterday', time: '22:00' })

      //Дата занятия «16.10.2026» в 00:30 по Улан-Удэ — сегодняшняя, не «далёкая».
      assert.equal(lessonDateIssue('16.10.2026', MIDNIGHT), '')
    } finally {
      if (before === undefined) delete process.env.TZ
      else process.env.TZ = before
    }
  })
}

test('сутки колледжа считаются по числам, а не по 24-часовым отрезкам', () => {
  assert.equal(collegeDayDiff(new Date('2026-10-15T15:59:00Z'), new Date('2026-10-15T16:01:00Z')), 1)
  assert.equal(collegeDayKey(addDays(MIDNIGHT, -1)), '2026-10-15')
  assert.equal(fromCollegeWall(2026, 10, 16).toISOString(), '2026-10-15T16:00:00.000Z')
})

test('мусор — пустая подпись, а не «сейчас»', () => {
  assert.equal(collegeHhmm('мусор'), '')
  assert.equal(collegeDayKey(''), '')
  assert.equal(formatCollege(undefined, 'ru-RU'), '')
  assert.ok(Number.isNaN(fromCollegeInput('не время').getTime()))
})

// ── свойство: фронт не читает календарь и часы устройства мимо collegeTime ───────────
// Исключения — С ПРИЧИНОЙ. Каждое обязано существовать (мёртвая запись — тоже ошибка).
const ALLOWED = {
  'theme/palette.js': 'тёмная тема «с 18:00 до 08:00» — про свет вокруг человека, а не про '
    + 'календарь колледжа: студенту на практике в Москве темнеет по-московски',
}
const FORBIDDEN = /toLocale(Date|Time)?String\(|toDateString\(|\.get(Hours|Minutes|Date|Day|Month|FullYear)\(|\.set(Hours|Date|Month|FullYear)\(|getTimezoneOffset\(/

export function deviceClockLines(text) {
  return text.split('\n').map((l, i) => [i + 1, l])
    .filter(([, l]) => FORBIDDEN.test(l) && !/^\s*(\/\/|\*)/.test(l))
}

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) walk(p, out)
    else if (/\.(js|vue)$/.test(name)) out.push(p)
  }
  return out
}

test('нигде, кроме collegeTime и исключений, нет часов устройства', () => {
  const src = new URL('../src/', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1')
  const found = []
  for (const file of walk(src)) {
    const rel = file.slice(src.length).replace(/\\/g, '/')
    if (rel === 'utils/collegeTime.js' || DICT_FILES.includes(rel) || ALLOWED[rel]) continue
    for (const [n, line] of deviceClockLines(readFileSync(file, 'utf8'))) found.push(`${rel}:${n}: ${line.trim()}`)
  }
  assert.deepEqual(found, [], 'Часы УСТРОЙСТВА вместо часов колледжа — возьми utils/collegeTime.js:\n' + found.join('\n'))
  for (const rel of Object.keys(ALLOWED)) {
    assert.ok(deviceClockLines(readFileSync(join(src, rel), 'utf8')).length,
      `исключение ${rel} больше не нужно — убери его из списка`)
  }
})

test('обратный ход: детектор видит каждую форму', () => {
  const sample = [
    "d.toLocaleString('ru')", 'd.toLocaleDateString()', 'd.toLocaleTimeString([], {})',
    'a.toDateString() === b.toDateString()', 'd.getHours()', 'd.getDate()', 'd.getDay()',
    'd.getMonth()', 'd.getFullYear()', 'd.getMinutes()', 'd.setHours(9)', 'd.setDate(1)',
    'new Date().getTimezoneOffset()',
    //законное — не находится:
    'd.getUTCDate()', 'd.toISOString()', 'formatCollege(d)', '// d.getHours() в комментарии',
  ].join('\n')
  assert.deepEqual(deviceClockLines(sample).map(([n]) => n), [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13])
})
