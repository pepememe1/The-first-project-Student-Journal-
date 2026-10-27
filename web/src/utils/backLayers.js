/**
 * backLayers.js — что закрывает системная кнопка «назад» раньше страницы.
 *
 * Без своего обработчика плагин @capacitor/app только листает историю WebView: открытое
 * окно «назад» не закрывал, а уводил страницу под ним (проверено на Android 16,
 * 23.10.2026). На Android принято, что «назад» сначала закрывает верхнее всплывающее окно.
 *
 * Слой — открытое поверх страницы: окно `v-dialog` (встаёт сюда само) и подложка или
 * панель с директивой `v-back-close`. Без значения директива щёлкает по своему элементу,
 * как щелчок мимо окна, и срабатывает `@click.self` самого компонента. Со значением-функцией
 * зовёт её — для панелей, которые закрываются не щелчком по подложке.
 * Закрывается только верхний слой, открытый последним.
 */

//Открытые слои по порядку открытия: последний — верхний.
const _layers = []

//Esc на ПК закрывает то же, что «назад» на телефоне. Меню и всплывашки на подложке
//(`v-back-close`) Esc раньше не видел вовсе: меню профиля, «+ Создать», «Удалить
//сообщение?» закрывались только мышью (живой прогон 27.10.2026). Окна `v-dialog`
//по-прежнему закрывает их директива — у неё свои условия (верхнее окно, обработано ли
//нажатие внутри).
function _onEscape(e) {
  if (e.key !== 'Escape' || e.defaultPrevented) return
  const top = topLayer()
  if (!top || top.el.__gbDialog) return
  e.preventDefault()
  top.close()
}

function _listen(on) {
  if (typeof window === 'undefined' || typeof window.addEventListener !== 'function') return
  if (on) window.addEventListener('keydown', _onEscape)
  else window.removeEventListener('keydown', _onEscape)
}

export function pushLayer(el, close) {
  if (!_layers.length) _listen(true)
  _layers.push({ el, close })
}

export function removeLayer(el) {
  for (let i = _layers.length - 1; i >= 0; i--) {
    if (_layers[i].el === el) {
      _layers.splice(i, 1)
      if (!_layers.length) _listen(false)
      return
    }
  }
}

//Слой, снятый со страницы или скрытый (`display: none` у боковой панели на широком
//экране), человек не видит, и закрывать его по «назад» нельзя: нажатие ушло бы в пустоту.
function visible(el) {
  if (!el || el.isConnected === false) return false
  return typeof el.getClientRects !== 'function' || el.getClientRects().length > 0
}

/**
 * Верхний видимый слой или null. `stack` передаёт тест.
 *
 * Слой внутри другого слоя главнее, даже если встал в очередь раньше: Vue монтирует
 * дочерние элементы раньше родителя, и когда окно и стрелка «Назад» в нём появляются
 * одной отрисовкой (выбор категории в меню активностей), окно оказывалось сверху и
 * закрывалось целиком, минуя шаг назад внутри себя.
 */
export function topLayer(stack = _layers) {
  let top = null
  for (let i = stack.length - 1; i >= 0; i--) {
    const layer = stack[i]
    if (!visible(layer.el)) continue
    if (!top || (top.el !== layer.el && typeof top.el.contains === 'function'
                 && top.el.contains(layer.el))) {
      top = layer
    }
  }
  return top
}

/** Закрыть верхний слой. false — закрывать нечего. */
export function closeTopLayer() {
  const top = topLayer()
  if (!top) return false
  top.close()
  return true
}

export const vBackClose = {
  mounted(el, binding) {
    el.__gbBack = binding.value
    pushLayer(el, () => {
      //Функцию берём в момент нажатия: шаблон пересоздаёт её при каждой отрисовке.
      if (typeof el.__gbBack === 'function') el.__gbBack()
      else el.click()
    })
  },
  updated(el, binding) {
    el.__gbBack = binding.value
  },
  unmounted(el) {
    removeLayer(el)
    delete el.__gbBack
  },
}
