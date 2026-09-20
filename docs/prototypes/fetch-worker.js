/**
 * Cloudflare Worker — разовый читатель страниц для разведки.
 *
 * ЗАЧЕМ. `gradebookai.com` (сайт-однофамилец, см. разбор 25.08.2026) не открывается
 * из России: соединение рвётся и в браузере, и у любого публичного ретранслятора
 * (r.jina.ai отдаёт 451, allorigins/codetabs/corsproxy — обрыв). Воркер крутится на
 * Cloudflare, её выход не российский, поэтому страницу он получает и отдаёт нам текстом.
 * VPN на весь компьютер не нужен.
 *
 * ⚠️ ЭТО НЕ ОТКРЫТЫЙ ПРОКСИ, И ЭТО ВАЖНО. Воркер, умеющий скачать ЛЮБОЙ адрес по
 * запросу кого угодно, — открытый релей: его находят сканерами за часы и начинают гонять
 * через него чужой трафик, пряча источник за твоим аккаунтом Cloudflare. Отвечать за это
 * будешь ты. Поэтому здесь две заслонки, и обе обязательны:
 *   1. БЕЛЫЙ СПИСОК хостов — что не в нём, то не скачивается;
 *   2. СЕКРЕТ в запросе — без него воркер молчит даже про разрешённый хост.
 *
 * КАК РАЗВЕРНУТЬ (5 минут, бесплатно):
 *   1. dash.cloudflare.com → Workers & Pages → Create → Create Worker → имя → Deploy.
 *   2. Edit code → удалить шаблон → вставить ВЕСЬ этот файл → Deploy.
 *   3. Settings → Variables → Add variable:  имя `SECRET`, значение — любая длинная
 *      строка (например `2f9c1a7b4e`). Отметить «Encrypt». Save and deploy.
 *   4. Проверить в браузере:  https://<имя>.<субдомен>.workers.dev/?secret=<секрет>
 *      Должен вернуться текст страницы.
 *
 * ⚠️ Если сам `workers.dev` у провайдера заблокирован (TLS рвётся до Cloudflare —
 * такое бывает), вариант не заработает в принципе. Тогда — Deno Deploy тем же приёмом,
 * как во втором скрипте того же проекта.
 *
 * ⚠️ ПОСЛЕ РАЗВЕДКИ ВОРКЕР УДАЛИТЬ. Инструмент разовый; оставленный «на всякий случай»
 * он живёт годами, и однажды секрет утечёт вместе со ссылкой.
 */

// Что вообще разрешено скачивать. Добавлять сюда — осознанно и по одному.
const ALLOW_HOSTS = [
  'gradebookai.com',
  'www.gradebookai.com',
]

export default {
  async fetch(request, env) {
    const url = new URL(request.url)

    // ⚠️ Секрет сверяем ПЕРВЫМ и постоянным по времени сравнением: обычное `!==` по
    // строке утекает её посимвольно, а секрет тут — единственное, что отделяет воркер
    // от роли открытого релея.
    const given = url.searchParams.get('secret') || ''
    const want = env.SECRET || ''
    if (!want) {
      return new Response('Не задана переменная SECRET — воркер выключен', { status: 503 })
    }
    if (!timingSafeEqual(given, want)) {
      // Отвечаем 404, а не 403: сканеру незачем знать, что здесь что-то есть.
      return new Response('Not found', { status: 404 })
    }

    const target = url.searchParams.get('url') || `https://${ALLOW_HOSTS[0]}/`
    let t
    try {
      t = new URL(target)
    } catch {
      return new Response('Плохой адрес', { status: 400 })
    }
    if (!ALLOW_HOSTS.includes(t.hostname)) {
      return new Response(`Хост ${t.hostname} не в белом списке`, { status: 403 })
    }
    if (t.protocol !== 'https:' && t.protocol !== 'http:') {
      return new Response('Только http(s)', { status: 400 })
    }

    // Обычный браузерный набор заголовков: часть сайтов отвечает 403 на запрос без
    // User-Agent, и тогда мы решили бы, что «сайт пустой», хотя он просто нас отшил.
    const resp = await fetch(t.toString(), {
      redirect: 'follow',
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                    + '(KHTML, like Gecko) Chrome/140.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
      },
    })

    const body = await resp.text()
    // Отдаём как ПРОСТОЙ ТЕКСТ: так его прочитает любой инструмент, и браузер не
    // выполнит чужие скрипты у тебя на вкладке.
    return new Response(
      `HTTP ${resp.status} ${resp.statusText}\n`
      + `Конечный адрес: ${resp.url}\n`
      + `Тип: ${resp.headers.get('content-type') || '—'}\n`
      + `Сервер: ${resp.headers.get('server') || '—'}\n`
      + '─'.repeat(60) + '\n'
      + body,
      { status: 200, headers: { 'content-type': 'text/plain; charset=utf-8' } },
    )
  },
}

/** Сравнение строк за постоянное время — чтобы секрет не утекал посимвольно. */
function timingSafeEqual(a, b) {
  if (a.length !== b.length) return false
  let diff = 0
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i)
  return diff === 0
}
