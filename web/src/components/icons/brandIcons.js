// Свои значки там, где в наборе lucide нет нужного смысла: Вектор (голова тигра) и
// приманка. Нарисованы по той же сетке, что и lucide (24×24, линия 2, скруглённые
// концы), поэтому стоят рядом с его значками без шва и красятся `currentColor`.
// Пути лежат данными: их же читает сборщик папки ассетов, чтобы не держать вторую копию.
import { h } from 'vue'

export const BRAND_ICON_PATHS = Object.freeze({
  vector: [
    // уши
    'M6.6 7.6c-.7-1.1-.9-2.4-.5-3.7 1.2.2 2.3.8 3.1 1.7',
    'M17.4 7.6c.7-1.1.9-2.4.5-3.7-1.2.2-2.3.8-3.1 1.7',
    // голова с «воротником» на щеках: по нему тигр не путается с медведем
    'M12 5c3.5 0 6.1 2 6.6 5.1l1.8 2.3-1.5 1C18.5 17.3 15.6 20 12 20s-6.5-2.7-6.9-6.6l-1.5-1 1.8-2.3C5.9 7 8.5 5 12 5Z',
    // полосы на лбу
    'M12 7.5v1.3',
    'M9.2 8.1l.6.9',
    'M14.8 8.1l-.6.9',
    // глаза
    'M9.3 11.6h.01',
    'M14.7 11.6h.01',
    // нос и пасть
    'M11 14.1h2l-1 1.1Z',
    'M12 15.2v.8c-.5.7-1.4.8-2 .3',
    'M12 16c.5.7 1.4.8 2 .3',
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

export const VectorHead = lineIcon('vector')
export const HoneyPot = lineIcon('honeypot')
