/**
 * pageSingleRoot.test.mjs — у страницы внутри оболочки ОДИН корневой элемент (06.10.2026).
 *
 * ━━ ЗАЧЕМ ━━
 * Оболочка рисует страницу так: `<transition name="fade"><component :is="Component" /></transition>`
 * (`layouts/AppShell.vue`). `<transition>` умеет анимировать только один корневой ЭЛЕМЕНТ.
 * Страница с двумя корнями (сама страница + окно рядом с ней) становится фрагментом:
 * Vue пишет в консоль разработчика «Component inside <Transition> renders non-element
 * root node that cannot be animated» и молча отключает ей переход.
 *
 * Найдено при заведении трекера: его окно было поставлено РЯДОМ с корнем страницы
 * сообщений. Ни сборка, ни линтер, ни остальные тесты этого не видят — предупреждение
 * живёт только в консоли dev-сервера.
 *
 * ⚠️ Разбор — настоящим компилятором Vue (`vue/compiler-sfc`), а не регуляркой по тексту:
 * считать корни на глаз по отступам значило бы проверять формат иначе, чем его читает
 * потребитель (наш урок про валидатор граней).
 *
 * ОБРАТНЫЙ ХОД: самопроверка в конце файла — дословная разметка дефекта обязана считаться
 * нарушением; вынести `<TrackerOverlay>` обратно за корень MessengerPage — краснеет
 * первый тест.
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { parse } from 'vue/compiler-sfc'

const SRC = new URL('../src/', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1')

/** Корневые узлы шаблона: элементы и непустой текст (комментарии Vue в счёт не берёт). */
function rootNodes(source) {
  const ast = parse(source).descriptor.template?.ast
  if (!ast) return null
  return ast.children
    .filter((n) => n.type === 1 || (n.type === 2 && n.content.trim()))
    .map((n) => n.tag || 'текст')
}

function pages(dir = join(SRC, 'pages'), out = []) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) pages(p, out)
    else if (name.endsWith('.vue')) out.push(p)
  }
  return out
}
const FILES = pages().map((p) => ({ rel: relative(SRC, p).replace(/\\/g, '/'), roots: rootNodes(readFileSync(p, 'utf8')) }))

/** Страницы, которым правило не писано, — с причиной у каждой. */
const NOT_UNDER_TRANSITION = {
  'pages/LoginPage.vue': 'экран входа рисуется вне оболочки — перехода страниц у него нет',
}

/**
 * Известный долг: страницы, где второй корень появился раньше этого сторожа. Это НЕ
 * исключения — у них переход действительно отключён. Список обязан только убывать:
 * починенная страница краснеет здесь, пока её не вычеркнут.
 */
const KNOWN_DEBT = {
  'pages/admin/AdminGroups.vue': 'два окна (подсказки преподавателей, приглашения) стоят рядом с корнем страницы',
  'pages/Settings.vue': 'две сцены прощания стоят рядом с корнем окна настроек',
}

test('у каждой страницы оболочки один корневой элемент', () => {
  assert.ok(FILES.length >= 40, `страниц нашлось подозрительно мало: ${FILES.length}`)
  const offenders = FILES
    .filter((f) => f.roots && f.roots.length !== 1)
    .filter((f) => !NOT_UNDER_TRANSITION[f.rel] && !KNOWN_DEBT[f.rel])
    .map((f) => `${f.rel}: ${f.roots.map((t) => `<${t}>`).join(' ')}`)
  assert.deepEqual(offenders, [],
    'страница с несколькими корнями теряет переход: окно ставят ВНУТРЬ корневого блока, а не рядом')
})

test('в списках исключений и долга нет устаревших записей', () => {
  const byRel = Object.fromEntries(FILES.map((f) => [f.rel, f]))
  for (const [rel, why] of [...Object.entries(NOT_UNDER_TRANSITION), ...Object.entries(KNOWN_DEBT)]) {
    assert.ok(byRel[rel], `запись указывает на несуществующую страницу: ${rel}`)
    assert.ok(why.length > 15, `у записи ${rel} нет внятной причины`)
  }
  // Страницу из долга починили — её обязаны вычеркнуть, иначе список защищает то, чего нет.
  const fixed = Object.keys(KNOWN_DEBT).filter((rel) => byRel[rel]?.roots?.length === 1)
  assert.deepEqual(fixed, [], 'страница починена — вычеркни её из KNOWN_DEBT')
})

test('окно трекера стоит внутри корня страницы сообщений', () => {
  const src = readFileSync(join(SRC, 'pages/MessengerPage.vue'), 'utf8')
  assert.deepEqual(rootNodes(src), ['div'])
  assert.match(src, /<TrackerOverlay v-if="tracker\.open && TrackerOverlay" \/>/, 'окно трекера со страницы сообщений пропало вовсе')
})

test('самопроверка: дословная разметка дефекта считается нарушением', () => {
  // Сторож, зелёный и без починки, неотличим от исправного кода.
  const broken = '<template>\n  <div class="flex">\n    <ChatThread />\n  </div>\n  <!-- окно рядом -->\n  <TrackerOverlay v-if="tracker.open" />\n</template>\n'
  const fixed = '<template>\n  <div class="flex">\n    <ChatThread />\n    <TrackerOverlay v-if="tracker.open" />\n  </div>\n</template>\n'
  assert.deepEqual(rootNodes(broken), ['div', 'TrackerOverlay'])
  assert.deepEqual(rootNodes(fixed), ['div'])
  // Комментарий рядом с корнем — не второй корень: Vue его не считает, и сторож не должен.
  assert.deepEqual(rootNodes('<template>\n  <!-- пояснение -->\n  <div />\n</template>'), ['div'])
})
