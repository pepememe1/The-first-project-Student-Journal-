// Свои значки там, где в наборе lucide нет нужного смысла: Вектор (знак вектора) и
// приманка. Нарисованы по той же сетке, что и lucide (24×24, линия 2, скруглённые
// концы), поэтому стоят рядом с его значками без шва и красятся `currentColor`.
// Пути лежат данными: их же читает сборщик папки ассетов, чтобы не держать вторую копию.
import { h } from 'vue'

export const BRAND_ICON_PATHS = Object.freeze({
  vector: [
    // точка начала: без неё стрелка читается как «открыть внешнюю ссылку»
    'M4 18a2 2 0 1 0 4 0a2 2 0 1 0 -4 0',
    // стержень и наконечник
    'M7.5 16.5 18 6',
    'M11 6h7v7',
  ],
  honeypot: [
    // горлышко
    'M6 6.5h12',
    // тело горшка
    'M7.6 6.5C5.7 8 5 10.2 5 12.6 5 16.9 8 20 12 20s7-3.1 7-7.4c0-2.4-.7-4.6-2.6-6.1',
    // потёк мёда через край
    'M9.2 6.5v2.8a1.3 1.3 0 0 0 2.6 0V8',
    // ложка для мёда
    'M14.5 6.5l3-4',
    'M16.6 2.2l1.8 1.3',
  ],
})

function lineIcon(name) {
  const paths = BRAND_ICON_PATHS[name]
  const Icon = (_props, { attrs }) => {
    const { size, strokeWidth, 'stroke-width': sw, ...rest } = attrs
    return h(
      'svg',
      {
        xmlns: 'http://www.w3.org/2000/svg',
        width: size ?? 24,
        height: size ?? 24,
        viewBox: '0 0 24 24',
        fill: 'none',
        stroke: 'currentColor',
        'stroke-width': strokeWidth ?? sw ?? 2,
        'stroke-linecap': 'round',
        'stroke-linejoin': 'round',
        ...rest,
      },
      paths.map((d) => h('path', { d })),
    )
  }
  Icon.displayName = `Gb${name[0].toUpperCase()}${name.slice(1)}Icon`
  Icon.inheritAttrs = false
  return Icon
}

export const HoneyPot = lineIcon('honeypot')

// Вектор в меню и на кнопках — знак по его имени, а не тигр (28.10.2026). Линейная голова
// читалась как чужой зверь, а рисунок Арины в 16 пикселях превращался в пятно среди
// линейных значков. Сам тигр остаётся аватаром в чатах и на странице помощника.
export const VectorHead = lineIcon('vector')
