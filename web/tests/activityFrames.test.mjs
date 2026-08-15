/**
 * activityFrames.test.mjs — приём кадров состояния активности (PLAN-ACTIVITIES §7, §11).
 *
 * Проверяем НАСТОЯЩИЙ модуль правила (`src/utils/frameOrder.js`), который зовёт стор, а
 * не его копию: копия осталась бы зелёной при сломанном сторе, и такой «тест» в этом
 * проекте уже находили.
 */
import test from 'node:test'
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import fs from 'node:fs'

import { acceptsFrame, mergeFrame } from '../src/utils/frameOrder.js'

test('кадр с бо́льшим seq принимается', () => {
  assert.equal(acceptsFrame(-1, 0), true)
  assert.equal(acceptsFrame(3, 4), true)
})

test('кадр с МЕНЬШИМ seq отбрасывается — сеть переупорядочивает пакеты', () => {
  // Ровно та гонка, что дважды ломала расписание и категории портала: «свежесть» кадра
  // по содержимому не определить, поэтому решает монотонный счётчик.
  assert.equal(acceptsFrame(17, 16), false)
})

test('повторный кадр с тем же seq отбрасывается', () => {
  // Иначе дубль пакета применился бы дважды — для «добавленных штрихов» это удвоение
  // линий на доске у всех, кроме рисующего.
  assert.equal(acceptsFrame(5, 5), false)
})

test('нечисловой seq — не «нулевой кадр», а испорченные данные', () => {
  // Приняв его, счётчик сбился бы, и следующие НОРМАЛЬНЫЕ кадры пошли бы в отказ.
  for (const bad of [undefined, null, 'abc', NaN, {}, []]) {
    assert.equal(acceptsFrame(2, bad), false, `seq=${JSON.stringify(bad)}`)
  }
})

test('кадры неполные: слияние поверх, а не замена целиком', () => {
  // Сервер шлёт только изменившиеся поля. Замена целиком стёрла бы всё остальное
  // состояние первым же частичным кадром — например, вопрос опроса при обновлении
  // счётчика проголосовавших.
  const before = { question: 'Понятно?', voted_count: 1, sheet: 'grid' }
  const after = mergeFrame(before, { voted_count: 2 })
  assert.equal(after.voted_count, 2)
  assert.equal(after.question, 'Понятно?')
  assert.equal(after.sheet, 'grid')
})

test('mergeFrame не мутирует прежнее состояние', () => {
  // Vue отслеживает замену ссылки; правка на месте не перерисовала бы экран.
  const before = { a: 1 }
  const after = mergeFrame(before, { a: 2 })
  assert.equal(before.a, 1)
  assert.equal(after.a, 2)
})

test('стор действительно ходит через это правило, а не держит свою копию', () => {
  // ⚠️ Сторож на САМ ФАКТ использования. Без него правило можно продублировать внутри
  // стора «для скорости», тесты выше останутся зелёными, а продукт поедет по копии,
  // которая разойдётся с проверенной. Тот же класс, что «обещание без вызывающего».
  const here = path.dirname(fileURLToPath(import.meta.url))   // fileURLToPath, не .pathname:
  //на Windows `new URL(...).pathname` даёт «/C:/…», и обход каталога молча ничего не
  //проверял бы (эта грабля уже была со сторожем локалей).
  const store = fs.readFileSync(path.join(here, '..', 'src', 'stores', 'activity.js'), 'utf8')
  assert.match(store, /from '@\/utils\/frameOrder'/)
  assert.match(store, /acceptsFrame\(/)
  assert.match(store, /mergeFrame\(/)
})
