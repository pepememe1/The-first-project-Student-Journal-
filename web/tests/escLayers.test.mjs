// escLayers.test.mjs — Esc на ПК закрывает то же, что «назад» на телефоне (27.10.2026).
//
// Меню профиля, «+ Создать», «Удалить сообщение?» стоят на подложке `v-back-close` и
// раньше закрывались только мышью: Esc видел одни окна `v-dialog`.
import { test } from 'node:test'
import assert from 'node:assert/strict'

const handlers = new Set()
globalThis.window = {
  addEventListener: (type, fn) => { if (type === 'keydown') handlers.add(fn) },
  removeEventListener: (type, fn) => { if (type === 'keydown') handlers.delete(fn) },
}
const { pushLayer, removeLayer } = await import('../src/utils/backLayers.js')

const press = (key) => {
  const e = { key, defaultPrevented: false, preventDefault() { this.defaultPrevented = true } }
  for (const fn of [...handlers]) fn(e)
  return e
}
const el = (extra = {}) => ({ isConnected: true, getClientRects: () => [1], contains: () => false, ...extra })

test('Esc закрывает верхнее меню на подложке', () => {
  let closed = 0
  const menu = el()
  pushLayer(menu, () => { closed++ })
  const e = press('Escape')
  assert.equal(closed, 1)
  assert.equal(e.defaultPrevented, true)
  removeLayer(menu)
  assert.equal(handlers.size, 0, 'слоёв нет — слушатель снят')
})

test('окно v-dialog Esc из очереди не закрывает — это делает его директива', () => {
  let closed = 0
  const dlg = el({ __gbDialog: {} })
  pushLayer(dlg, () => { closed++ })
  const e = press('Escape')
  assert.equal(closed, 0)
  assert.equal(e.defaultPrevented, false)
  removeLayer(dlg)
})

test('другие клавиши и уже обработанное нажатие слой не трогают', () => {
  let closed = 0
  const menu = el()
  pushLayer(menu, () => { closed++ })
  press('Enter')
  const e = { key: 'Escape', defaultPrevented: true, preventDefault() {} }
  for (const fn of [...handlers]) fn(e)
  assert.equal(closed, 0)
  removeLayer(menu)
})
