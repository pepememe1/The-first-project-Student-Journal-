// offerMeta.test.mjs — голова и структурированные данные одностраничника для комиссии.
//
// Заведён 24.08.2026. До него web/public/offer.html не имел НИ doctype, НИ <html lang>,
// НИ <meta viewport> — при том, что в его стилях лежат два медиазапроса (820px и 560px),
// то есть вся мобильная вёрстка страницы. Без viewport телефонный браузер раскладывает
// документ в 980 CSS-пикселей, и ни один из этих запросов не срабатывает НИКОГДА: на
// живом телефоне страница рисовалась настольной и ужималась до нечитаемого масштаба.
//
// ⚠️ ЭМУЛЯЦИЯ ЭТОТ ДЕФЕКТ НЕ ЛОВИТ — и это главная причина, по которой сторож текстовый,
// а не браузерный. Playwright задаёт ширину окна принудительно, поэтому и БЕЗ метатега
// медиазапросы у него срабатывают, скриншот выходит правильным, а продукт сломан. Ровно
// так у нас уже снимали мобильные скриншоты этой страницы и дефекта не увидели.
//
// Второе назначение файла — не дать разметке начать врать. Google показывает звёздочки
// только при aggregateRating/review/offers, и соблазн вписать их «чтобы работало» велик.
// Отзывов и цены на странице нет; выдуманный рейтинг — это ровно то, чего продукт
// обещает не делать (анти-галлюцинационный принцип «Вектора»), и прямое нарушение
// правил Google. Поэтому их отсутствие проверяется как ИНВАРИАНТ, а не подразумевается.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const WEB = dirname(dirname(fileURLToPath(import.meta.url)))
const PUBLIC = join(WEB, 'public')
const html = readFileSync(join(PUBLIC, 'offer.html'), 'utf8')

//Разбираем ВСЕ meta-теги одним проходом. Собирать регулярку из строки здесь нельзя:
//в шаблонной строке JS «\s» — не escape-последовательность, она молча схлопывается в
//букву «s», регулярка перестаёт совпадать с чем угодно, и половина проверок становится
//тривиально зелёной (assert.doesNotMatch по пустой строке проходит всегда).
const metas = { name: {}, property: {} }
for (const m of html.matchAll(/<meta\s+(name|property)="([^"]+)"\s+content="([^"]*)"/gi)) {
  metas[m[1].toLowerCase()][m[2]] = m[3]
}
const named = (n) => metas.name[n] || ''
const og = (n) => metas.property[n] || ''

test('документ объявлен целиком: doctype, язык, закрытые теги', () => {
  assert.match(html, /^<!doctype html>/i, 'потерян doctype — браузер уйдёт в режим совместимости')
  assert.match(html, /<html lang="ru">/, 'без lang="ru" переносы и озвучка идут по правилам чужого языка')
  assert.ok(html.includes('</body>'), 'не закрыт body')
  assert.ok(html.includes('</html>'), 'не закрыт html')
})

test('viewport есть и делает медиазапросы страницы рабочими', () => {
  const v = named('viewport')
  assert.ok(v, 'без meta viewport вся мобильная вёрстка offer.html мертва — см. шапку файла')
  assert.match(v, /width=device-width/, 'ширина должна равняться ширине устройства')
})

test('масштабирование НЕ запрещено — страницу читает комиссия', () => {
  //Осознанное расхождение с index.html: там зум выключен ради поля ввода мессенджера,
  //здесь он нужен — в таблице сравнения мелкий текст, и его увеличивают щипком.
  const v = named('viewport')
  //⚠️ Своими ногами: без этой строки обе проверки ниже — doesNotMatch по ПУСТОЙ строке,
  //то есть проходят всегда. Пропажу тега ловит соседний тест, но сторож, который держится
  //на соседе, замолкает молча, стоит соседу измениться.
  assert.ok(v, 'тег viewport не найден — проверять запрет зума не на чем')
  assert.doesNotMatch(v, /user-scalable\s*=\s*no/, 'запрет зума на странице-документе — барьер доступности')
  assert.doesNotMatch(v, /maximum-scale\s*=\s*1/, 'maximum-scale=1 тоже запрещает увеличение')
})

test('карточка ссылки: описание и Open Graph на месте', () => {
  //Работает независимо от robots.txt: Telegram и почтовые клиенты строят превью
  //по этим тегам и запрета индексации не читают.
  assert.ok(named('description').length > 60, 'нет описания страницы')
  assert.match(html, /<link rel="canonical" href="https:\/\/esstu-gradebook\.ru\/offer\.html">/, 'нет canonical')
  for (const p of ['og:title', 'og:description', 'og:url', 'og:image', 'og:type']) {
    assert.ok(og(p), `потерян ${p} — ссылка в мессенджере придёт голой`)
  }
})

test('картинка превью не выдумана — файл лежит в public', () => {
  const url = og('og:image')
  assert.match(url, /^https:\/\/esstu-gradebook\.ru\//, 'og:image обязан быть абсолютным адресом')
  const rel = url.replace('https://esstu-gradebook.ru/', '')
  assert.ok(existsSync(join(PUBLIC, rel)), `og:image указывает на ${rel}, которого нет в web/public`)
})

const ld = () => {
  const blocks = [...html.matchAll(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/g)]
  assert.equal(blocks.length, 1, 'ожидался ровно один блок JSON-LD')
  return JSON.parse(blocks[0][1])
}

test('JSON-LD разбирается и содержит обе наши сущности', () => {
  const d = ld()
  assert.equal(d['@context'], 'https://schema.org')
  const types = d['@graph'].map((n) => n['@type'])
  assert.deepEqual(types, ['Organization', 'SoftwareApplication'])
})

test('издатель связан с организацией НАСТОЯЩИМ идентификатором', () => {
  //Разъехавшийся @id — молчаливый дефект: разметка валидна, а связь между
  //приложением и его издателем для Google не существует.
  const d = ld()
  const [org, app] = d['@graph']
  assert.ok(org['@id'], 'у организации нет @id')
  assert.equal(app.publisher['@id'], org['@id'], 'publisher ссылается не на нашу организацию')
})

test('адреса в разметке ведут на наши же ресурсы', () => {
  const [org, app] = ld()['@graph']
  assert.match(org.logo, /^https:\/\/esstu-gradebook\.ru\//)
  assert.match(app.downloadUrl, /^https:\/\/esstu-gradebook\.ru\/downloads\//)
  assert.match(app.installUrl, /^https:\/\/(www\.)?rustore\.ru\//)
  const logoRel = org.logo.replace('https://esstu-gradebook.ru/', '')
  assert.ok(existsSync(join(PUBLIC, logoRel)), `логотип ${logoRel} не найден в web/public`)
})

test('в разметке НЕТ рейтингов, отзывов и цены — их неоткуда взять', () => {
  const raw = JSON.stringify(ld())
  for (const forbidden of ['aggregateRating', 'reviewCount', 'ratingValue', 'review', 'offers', 'price']) {
    assert.ok(!raw.includes(forbidden), `в разметку попал ${forbidden}: на странице нет ни цены, ни отзывов — это выдумка`)
  }
})

test('версия продукта сюда не дублируется', () => {
  //Строка версии живёт в одном месте (desktop_update.py::APP_VERSION). Второй литерал
  //начал бы отставать молча — этой ошибкой уже платили дважды.
  assert.ok(!JSON.stringify(ld()).includes('softwareVersion'), 'softwareVersion завёл бы вторую копию номера версии')
})

// ── robots.txt и карта сайта ────────────────────────────────────────────────────
// Разметка выше имеет смысл ровно постольку, поскольку краулеру разрешено дойти до
// страницы И до её логотипа. Обе части проверяем ВМЕСТЕ: закрыть /icons/ можно одной
// строкой, страница при этом останется открытой, тесты разметки — зелёными, а Google
// молча перестанет получать логотип. Это наш обычный класс дефекта: обещание без того,
// что делает его выполнимым.
const robots = readFileSync(join(PUBLIC, 'robots.txt'), 'utf8')
const allows = robots
  .split(/\r?\n/)
  .filter((l) => /^Allow:/i.test(l.trim()))
  .map((l) => l.split(':')[1].trim())

test('robots.txt закрывает сайт целиком и открывает только одностраничник', () => {
  assert.match(robots, /^Disallow: \/$/m, 'потерян общий запрет — краулеру открылся кабинет с ПДн')
  assert.ok(allows.includes('/offer.html'), 'страница для комиссии снова закрыта от поиска')
})

test('ни одно Allow не ведёт за вход', () => {
  //Свойство, а не слепок списка: новые ресурсы страницы добавлять можно, а вот открыть
  //кабинет, API или раздачу .exe — нельзя. Слепок краснел бы на каждом законном
  //добавлении и его бы просто «обновляли», чего он и должен не допускать.
  const запрещено = ['/web', '/api', '/auth', '/login', '/me', '/chats', '/messenger', '/sync', '/admin', '/downloads', '/connect', '/desk']
  for (const a of allows) {
    assert.notEqual(a, '/', 'Allow: / открывает вообще всё')
    for (const bad of запрещено) {
      assert.ok(!a.startsWith(bad), `Allow ${a} открывает краулеру ${bad} — это данные за входом`)
    }
  }
})

test('логотип из JSON-LD краулеру доступен', () => {
  const path = ld()['@graph'][0].logo.replace('https://esstu-gradebook.ru', '')
  assert.ok(
    allows.some((a) => path.startsWith(a)),
    `логотип ${path} не покрыт ни одним Allow — Google не сможет его забрать, и разметка Organization обесценится`
  )
})

test('карта сайта ведёт ровно на ту же страницу, что canonical', () => {
  const sitemap = readFileSync(join(PUBLIC, 'sitemap.xml'), 'utf8')
  const loc = sitemap.match(/<loc>([^<]+)<\/loc>/g).map((s) => s.replace(/<\/?loc>/g, ''))
  assert.deepEqual(loc, ['https://esstu-gradebook.ru/offer.html'], 'в карте сайта не то, что открыто в robots.txt')
  assert.ok(html.includes(`<link rel="canonical" href="${loc[0]}">`), 'canonical и карта сайта разошлись')
})

// ── скрипты и политика самой страницы ───────────────────────────────────────────
// Найдено Полковником 24.08.2026: комментарий в offer.html ссылался на этот файл как
// на сторожа «инлайн-скрипт под CSP не блокируется», а проверки скриптов здесь не было
// вовсе — обещание без исполнителя, наш самый частый класс дефекта. Плюс сама страница
// была ЕДИНСТВЕННЫМ документом бандла без меты CSP: внутри программы (origin
// http://127.0.0.1) заголовки Caddy до неё не доходят, и политики там не было никакой.
test('на странице нет исполняемых скриптов — только данные разметки', () => {
  //Под нашей политикой (script-src 'none' в мете, 'self' в заголовке Caddy) дописанный
  //сюда инлайн-скрипт молча не выполнится: ни ошибки на экране, ни следа в логе — просто
  //кнопка, которая ничего не делает. Пусть это выясняется здесь, а не на бою у комиссии.
  const tags = [...html.matchAll(/<script\b[^>]*>/gi)].map((m) => m[0])
  for (const t of tags) {
    assert.match(t, /type="application\/ld\+json"/, `на странице появился исполняемый скрипт: ${t}`)
  }
})

test('у страницы есть СВОЯ мета CSP — заголовки Caddy до неё доходят не везде', () => {
  const p = html.match(/<meta http-equiv="Content-Security-Policy" content="([^"]+)"/i)
  assert.ok(p, 'мета CSP пропала — внутри программы страница остаётся без политики вовсе')
  assert.match(p[1], /script-src 'none'/, "script-src должен быть 'none': скриптов на странице нет")
  assert.match(p[1], /object-src 'none'/, 'потеряна object-src')
})

test('viewport-fit=cover не появляется без отступов под вырез', () => {
  //Связка, а не запрет: cover снимает автоматические поля под вырезом телефона, и без
  //env(safe-area-inset-*) в стилях он способен только загнать шапку под вырез.
  const v = named('viewport')
  assert.ok(v, 'тег viewport не найден — условие проверки не на чем вычислять')
  //⚠️ СТОРОЖ СПЯЩИЙ: пока cover нет, тело не исполняется. Это законно (он сработает в
  //день, когда cover вернут), но в счётчике зелёных он неотличим от работающего — помнить.
  if (/viewport-fit\s*=\s*cover/.test(v)) {
    //⚠️ Искать ПО СТИЛЯМ, а не по всему файлу: слова «safe-area-inset» есть в
    //комментарии к самому viewport, и проверка по html проходила бы всегда — этот
    //сторож уже был пойман зелёным без починки в день своего появления.
    const css = html.slice(html.indexOf('<style>'), html.indexOf('</style>'))
    assert.match(css, /env\(\s*safe-area-inset/, 'включён viewport-fit=cover, но отступов под вырез в стилях нет')
  }
})

// ── контакты: разметка обязана отражать ВИДИМЫЙ контент ─────────────────────────
// Правило Google, а не наша придумка: структурированные данные должны соответствовать
// тому, что человек видит на странице. Контакт, живущий только в JSON-LD, — это скрытая
// разметка, за неё принимают меры вручную. И наоборот: почта, поменянная в подвале и
// забытая в разметке, разошлась бы молча — в блок знаний уехал бы старый адрес.
test('почта и телефон из разметки видны на самой странице', () => {
  const org = ld()['@graph'][0]
  const body = html.slice(html.indexOf('<body>'))
  assert.ok(org.email, 'в разметке нет почты')
  assert.ok(body.includes(org.email), `почта ${org.email} есть в разметке, но не видна на странице`)
  const цифры = (t) => t.replace(/\D/g, '')
  assert.ok(org.telephone, 'в разметке нет телефона')
  assert.ok(
    цифры(body).includes(цифры(org.telephone)),
    `телефон ${org.telephone} есть в разметке, но не виден на странице`
  )
})

test('контактная точка не разошлась с контактами организации', () => {
  const org = ld()['@graph'][0]
  assert.equal(org.contactPoint.email, org.email, 'почта в contactPoint и у организации разная')
  assert.equal(org.contactPoint.telephone, org.telephone, 'телефон в contactPoint и у организации разный')
})
