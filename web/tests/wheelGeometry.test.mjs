/**
 * wheelGeometry.test.mjs — картинка активности не имеет права вылезти из своего куска
 * пирога и не имеет права схлопнуться в точку.
 *
 * Зачем тест вообще. Обрезку по форме сектора делает `clip-path`, и глазами она выглядит
 * правильной ВСЕГДА — даже когда прямоугольник картинки посчитан неверно: лишнее просто
 * срезается. То есть настоящая поломка («видно две плитки вместо экрана», «картинка
 * надрезана внутренней дугой») с виду неотличима от исправной работы, а сборка и линтер
 * геометрию не считают вовсе. Считаем числами.
 *
 * ⚠️ Тест зовёт ФУНКЦИИ ПРОДУКТА (`@/utils/wheelGeometry`), а не повторяет формулы у себя:
 * копия сверяла бы копию с копией и пережила бы любую правку компонента.
 */
import test from 'node:test'
import assert from 'node:assert/strict'
import {
  C, HALF, pt, sectorPath, sectorBBox, inSector, fitRectInSector,
  fitBlockInSector, shotAndCaption, CAPTION_GAP, CAPTION_H,
} from '../src/utils/wheelGeometry.js'

// Раскрытый сектор ровно такой, каким его строит ActivityWheel: SPREAD 96°, зазор 1.1°,
// радиусы 0.30 и 1.0 от половины стороны.
const R_IN = 0.30 * HALF
const R_OUT = 1.0 * HALF
const GAP = 1.1
const SPREAD = 96

/** Углы раскрытого сектора, центрированного на середине `mid`. */
function openSector(mid) {
  return [mid - SPREAD / 2 + GAP / 2, mid + SPREAD / 2 - GAP / 2]
}

// Шесть положений — по одному на каждую активность колеса. Проверять одно мало: сектор
// «на 12 часов» и сектор «на 7 часов» дают РАЗНЫЕ габариты, и ошибка знака в углах
// прошла бы незамеченной на симметричном случае.
const MIDS = [30, 90, 150, 210, 270, 330]
const ASPECTS = [336 / 252, 1063 / 548, 16 / 9, 1]   // схема, реальный снимок, широкий, квадрат

test('прямоугольник картинки целиком лежит внутри куска пирога', () => {
  for (const mid of MIDS) {
    const [a0, a1] = openSector(mid)
    for (const aspect of ASPECTS) {
      const r = fitRectInSector(aspect, a0, a1, R_IN, R_OUT)
      const x0 = r.cx - r.w / 2
      const y0 = r.cy - r.h / 2
      //Проверяем ГУСТУЮ сетку по всему прямоугольнику, а не четыре угла: внутренняя
      //дуга вогнутая, и угол может быть внутри, пока середина стороны уже во втулке.
      for (let i = 0; i <= 10; i++) {
        for (let j = 0; j <= 10; j++) {
          const x = x0 + (r.w * i) / 10
          const y = y0 + (r.h * j) / 10
          assert.ok(inSector(x, y, a0, a1, R_IN, R_OUT),
            `mid=${mid} aspect=${aspect.toFixed(2)}: точка (${x.toFixed(1)}, ${y.toFixed(1)}) вне сектора`)
        }
      }
    }
  }
})

test('картинка не схлопывается: занимает заметную долю сектора', () => {
  //Обратный ход к «вписали в ноль». Двоичный поиск, начатый с недостижимой верхней
  //границы, при ошибке в `fits` честно сходится к нулю — и обрезка это спрячет.
  for (const mid of MIDS) {
    const [a0, a1] = openSector(mid)
    const r = fitRectInSector(336 / 252, a0, a1, R_IN, R_OUT)
    assert.ok(r.w > 60, `mid=${mid}: ширина картинки ${r.w.toFixed(1)} — слишком мала`)
    assert.ok(r.h > 45, `mid=${mid}: высота картинки ${r.h.toFixed(1)} — слишком мала`)
  }
})

test('пропорция снимка сохраняется — картинка не растянута', () => {
  for (const aspect of ASPECTS) {
    const [a0, a1] = openSector(90)
    const r = fitRectInSector(aspect, a0, a1, R_IN, R_OUT)
    assert.ok(Math.abs(r.w / r.h - aspect) < 1e-6,
      `пропорция уехала: ${(r.w / r.h).toFixed(4)} вместо ${aspect.toFixed(4)}`)
  }
})

test('габарит сектора учитывает выпуклость дуги, а не только углы', () => {
  //Сектор, пересекающий направление «вправо» (угол 90° в системе колеса): дуга там
  //выпирает за хорду, и габарит ОБЯЗАН доставать до самой дальней точки дуги.
  const [a0, a1] = openSector(90)
  const b = sectorBBox(a0, a1, R_IN, R_OUT)
  const [farX] = pt(R_OUT, 90)
  assert.ok(b.x + b.w >= farX - 1e-6,
    'габарит обрезан по хорде: посчитан по углам, точки касания дуги пропущены')

  //Обратный ход: габарит, посчитанный ТОЛЬКО по четырём углам, до этой точки не достаёт.
  const corners = [pt(R_IN, a0), pt(R_OUT, a0), pt(R_IN, a1), pt(R_OUT, a1)]
  const naiveRight = Math.max(...corners.map((p) => p[0]))
  assert.ok(naiveRight < farX,
    'случай выбран неудачно: наивный габарит и правильный совпали, тест ничего не проверяет')
})

test('контур сектора замкнут и построен вокруг центра колеса', () => {
  const [a0, a1] = openSector(210)
  const d = sectorPath(a0, a1, R_IN, R_OUT)
  assert.ok(d.trim().endsWith('Z'), 'путь не замкнут — clip-path обрежет не то')
  assert.equal((d.match(/A /g) || []).length, 2, 'у кольцевого сектора ровно две дуги')
  //Центр колеса лежит во ВТУЛКЕ, то есть ВНЕ сектора: если это перестанет быть правдой,
  //картинка полезет на кнопку «Журнал».
  assert.equal(inSector(C, C, a0, a1, R_IN, R_OUT), false)
})

test('раскрытие сектора даёт картинке больше места, чем покой', () => {
  //Проверяем ровно то, что подтверждается числами: раскрытие (96° и полный радиус) даёт
  //ощутимо больше места, чем покой (60° и радиус 0.94).
  //⚠️ Порог намеренно НЕ подогнан под текущее значение: выигрыш сейчас около 18 %, ждём
  //больше 10 %. Подгонка «чтобы прошло» превратила бы сторожа в снимок числа.
  const step = 360 / 6
  const calm = fitRectInSector(336 / 252, 0 + GAP / 2, step - GAP / 2, R_IN, 0.94 * HALF)
  const open = fitRectInSector(336 / 252, ...openSector(step / 2), R_IN, R_OUT)
  assert.ok(open.w > calm.w * 1.1,
    `раскрытие перестало давать выигрыш по месту: ${calm.w.toFixed(1)} -> ${open.w.toFixed(1)}`)
})

// Самое длинное название из шести («Срез понимания») — по той же формуле ширины, что в
// компоненте. Именно оно и вылезало за клин, когда подпись считали отдельно от снимка.
const LONGEST = 14 * 7.9 + 20
const EXTRA = CAPTION_GAP + CAPTION_H

/** Углы прямоугольника плюс середины сторон — где подпись и вылезала. */
function probes(r) {
  return [
    [r.x, r.y], [r.x + r.w, r.y], [r.x, r.y + r.h], [r.x + r.w, r.y + r.h],
    [r.x + r.w / 2, r.y + r.h], [r.x + r.w / 2, r.y],
    [r.x, r.y + r.h / 2], [r.x + r.w, r.y + r.h / 2],
  ]
}

test('снимок И подпись целиком лежат внутри своего куска пирога', () => {
  //Прототип утверждал «место под снимком свободно всегда» — это НЕ следует из того, что
  //снимок вписан в клин: снизу его подпирает вогнутая внутренняя дуга. Обратный ход
  //к дефекту: на 4:3 угол плашки уходил за край, и `clip-path` это молча срезал.
  for (const mid of MIDS) {
    const [a0, a1] = openSector(mid)
    for (const aspect of ASPECTS) {
      const block = fitBlockInSector(aspect, EXTRA, a0, a1, R_IN, R_OUT)
      const { shot, caption } = shotAndCaption(block, LONGEST)
      for (const [name, r] of [['снимок', shot], ['подпись', caption]]) {
        for (const [x, y] of probes(r)) {
          assert.ok(inSector(x, y, a0, a1, R_IN, R_OUT),
            `mid=${mid} aspect=${aspect.toFixed(2)}: ${name} — точка `
            + `(${x.toFixed(1)}, ${y.toFixed(1)}) вне клина`)
        }
      }
    }
  }
})

test('подпись не налезает на снимок и не шире его', () => {
  //Два обратных хода сразу: «сдвинули подпись вверх, чтобы влезла» (закроет картинку,
  //ради которой всё делалось) и «оставили плашку по ширине текста» (вылезет вбок).
  for (const mid of MIDS) {
    const [a0, a1] = openSector(mid)
    const block = fitBlockInSector(336 / 252, EXTRA, a0, a1, R_IN, R_OUT)
    const { shot, caption } = shotAndCaption(block, LONGEST)
    assert.ok(caption.y >= shot.y + shot.h,
      `mid=${mid}: подпись заехала на снимок (${caption.y.toFixed(1)} < ${(shot.y + shot.h).toFixed(1)})`)
    assert.ok(caption.w <= shot.w + 1e-6,
      `mid=${mid}: плашка ${caption.w.toFixed(1)} шире снимка ${shot.w.toFixed(1)}`)
  }
})

test('снимок остаётся крупным, хотя место делится с подписью', () => {
  //Обратный ход к «зарезервировали место и снимок схлопнулся»: запас под подпись съедает
  //часть клина, но картинка обязана остаться читаемой. Порог не подогнан — ждём заметно
  //меньше того, что получается сейчас (около 100 единиц ширины).
  for (const mid of MIDS) {
    const [a0, a1] = openSector(mid)
    const block = fitBlockInSector(336 / 252, EXTRA, a0, a1, R_IN, R_OUT)
    const { shot } = shotAndCaption(block, LONGEST)
    assert.ok(shot.w > 60, `mid=${mid}: снимок сузился до ${shot.w.toFixed(1)}`)
    assert.ok(shot.h > 45, `mid=${mid}: снимок сплющился до ${shot.h.toFixed(1)}`)
  }
})

test('запас под подпись реально уменьшает снимок — иначе его никто не резервирует', () => {
  //Сторож на само существование запаса: если `extraH` перестанет учитываться, блок
  //совпадёт с прямоугольником без запаса, и подпись снова окажется «на честном слове».
  const [a0, a1] = openSector(90)
  const withCap = fitBlockInSector(336 / 252, EXTRA, a0, a1, R_IN, R_OUT)
  const plain = fitRectInSector(336 / 252, a0, a1, R_IN, R_OUT)
  assert.ok(withCap.w < plain.w - 1,
    `запас под подпись не учитывается: ${withCap.w.toFixed(1)} против ${plain.w.toFixed(1)}`)
})
