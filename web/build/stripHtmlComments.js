// stripHtmlComments.js — плагин сборки: убирает HTML-комментарии из index.html.
//
// Вынесен из `vite.config.js` отдельным файлом НЕ ради порядка: внутри конфига его не
// проверить тестом, не потянув за собой весь Vite с плагинами Vue и Tailwind. Здесь —
// чистая функция без зависимостей, и `web/tests/stripHtmlComments.test.mjs` зовёт её
// саму, а не повторяет регулярку у себя.

/**
 * Убирает HTML-комментарии, КРОМЕ условных комментариев IE (`<!--[if ...]>`).
 *
 * ⚠️ Условные исполняются браузером — это разметка, а не пояснение; вырезать их значило
 * бы менять поведение страницы. В нашем `index.html` их сейчас нет, но правило должно
 * пережить того, кто однажды их добавит.
 */
export function stripComments(html) {
  return String(html).replace(/<!--(?!\[if)[\s\S]*?-->/g, '')
}

/**
 * Плагин Vite. Работает ТОЛЬКО на сборке: в `npm run dev` комментарии остаются, иначе
 * отлаживать разметку пришлось бы по файлу без единого пояснения.
 *
 * Зачем вообще. В `web/index.html` комментарии длинные и содержательные — про CSP, про
 * viewport, про шрифты; каждый объясняет, ПОЧЕМУ сделано именно так. Vite их не трогает,
 * и весь текст уезжает в бой как есть. Две причины убрать:
 *   • это бесплатная подсказка постороннему о том, как устроена наша защита (не дыра
 *     сама по себе — вопрос Ярослава 28.08.2026, увидел блок про CSP через F12);
 *   • лишние байты в КАЖДОЙ первой загрузке страницы.
 *
 * ⚠️ Исходник не меняется: комментарии остаются в `web/index.html` для команды,
 * вырезается только копия, уходящая в `dist`.
 */
export default function stripHtmlComments() {
  return {
    name: 'gb-strip-html-comments',
    apply: 'build',
    transformIndexHtml(html) {
      return stripComments(html)
    },

    /**
     * 🔥 `transformIndexHtml` НЕ ВИДИТ СТРАНИЦ ИЗ `public/` — их Vite копирует в `dist`
     * ДОСЛОВНО, мимо всех плагинов. Обнаружено 29.08.2026: у нас там лежат три
     * самостоятельных документа (`offer.html` для комиссии, `privacy.html` и
     * `terms.html`), и в каждом длинные пояснения — в том числе про устройство CSP.
     * То есть починка 28.08 закрыла ровно одну страницу из четырёх, а про остальные
     * молчала: комментарии как уезжали в бой, так и уезжали.
     *
     * ⚠️ Проходим по УЖЕ ЗАПИСАННОМУ `dist`, а не по `public`: исходники трогать
     * нельзя, пояснения нужны команде. Повторная обработка `index.html` безвредна —
     * вырезать в нём уже нечего, функция идемпотентна.
     */
    async writeBundle(options) {
      const { readdir, readFile, writeFile } = await import('node:fs/promises')
      const { join } = await import('node:path')
      const dir = options?.dir || 'dist'
      let names = []
      try {
        names = await readdir(dir)
      } catch {
        return                      //каталога нет — сборка и так упадёт своим путём
      }
      for (const name of names.filter((n) => n.endsWith('.html'))) {
        const file = join(dir, name)
        const src = await readFile(file, 'utf8')
        const out = stripComments(src)
        if (out !== src) await writeFile(file, out)
      }
    },
  }
}
