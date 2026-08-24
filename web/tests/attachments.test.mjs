// Вложения и панель беседы — правила, которые ломаются молча.
//
// Здесь проверяются СВОЙСТВА, а не отрисовка: у файла нет видимого признака, по
// которому сломанный путь заметили бы тесты вёрстки, а поймать это вручную можно
// только с настроенным хранилищем.
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join, dirname } from 'node:path'
import { previewKind, humanSize } from '../src/utils/docPreview.js'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const read = (f) => readFileSync(join(ROOT, f), 'utf8')

// ⚠️ Комментарии срезаем: искомая строка, найденная в объяснении рядом с кодом, —
// наша давняя ловушка, из-за которой сторож зеленеет на пустом месте.
const code = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/^\s*\/\/.*$/gm, '')
  .replace(/<!--[\s\S]*?-->/g, '')

const store = code(read('src/stores/messenger.js'))
const thread = code(read('src/components/messenger/ChatThread.vue'))
const panel = code(read('src/components/messenger/ConversationInfo.vue'))
const preview = code(read('src/components/messenger/FilePreview.vue'))

test('файл не проходит через наш сервер: подпись, прямой PUT, подтверждение', () => {
  // 🔥 Главное правило вложений и причина, по которой они устроены именно так: на
  // боевой машине ОДНО ядро и ОДИН процесс uvicorn, раздающий журнал. Прогони через
  // него файлы — лягут оценки и расписание (замеры в MESSENGER-ATTACHMENTS-PLAN.md).
  const send = store.split('async function sendFile(')[1].split('\n  }')[0]
  assert.match(send, /signUpload\(/, 'нет шага подписи — файл поедет через наш сервер')
  assert.match(send, /fetch\(sign\.url/, 'файл не кладётся напрямую в хранилище')
  assert.match(send, /confirmUpload\(/, 'нет подтверждения загрузки')
  // ⚠️ Подтверждение обязано идти ДО отправки сообщения: иначе в ленте появится
  // карточка файла, которого в хранилище может не быть.
  assert.ok(send.indexOf('confirmUpload(') < send.indexOf('messengerApi.send('),
    'сообщение отправляется раньше подтверждения загрузки')
})

test('к хранилищу не прикладывается наш заголовок авторизации', () => {
  // Подпись уже в ссылке; лишний заголовок ломает её проверку, и загрузка падает с
  // невнятной ошибкой на стороне провайдера.
  const send = store.split('async function sendFile(')[1].split('\n  }')[0]
  const put = send.split('fetch(sign.url')[1].split('})')[0]
  assert.ok(!/Authorization/i.test(put), 'к запросу в хранилище добавлен наш токен')
})

test('кнопка прикрепления стоит СЛЕВА от поля ввода', () => {
  // Просьба Влада 25.08.2026. Проверяем порядок в разметке, а не наличие: кнопка,
  // уехавшая вправо к «отправить», теряется среди действий отправки.
  // ⚠️ Ищем ИМЕННО композер: в файле несколько форм (есть ещё форма шаблонов), и
  // наивный поиск первой попавшейся проверял бы не то.
  const form = thread.split('sendPendingFile() : submit()')[1].split('</form>')[0]
  const clip = form.indexOf('pickFile')
  const area = form.indexOf('ref="composer"')
  assert.ok(clip >= 0, 'кнопки прикрепления нет вовсе')
  assert.ok(area >= 0, 'не нашли поле ввода')
  assert.ok(clip < area, 'кнопка прикрепления оказалась справа от поля')
})

test('файл показывают ДО отправки', () => {
  // Мессенджер, отправляющий документ по одному клику, рано или поздно отправит не тот
  // файл не в тот чат — а «удалить у всех» в учебной переписке уже не помогает.
  assert.match(thread, /pendingFile/, 'выбранный файл нигде не удерживается')
  assert.match(thread, /previewFile = pendingFile/, 'выбранный файл нельзя открыть до отправки')
})

test('предпросмотр не отправляет документ на сторону', () => {
  // Ни на наш сервер, ни к внешнему сервису: PDF рисует браузер, DOCX распаковывается
  // во вкладке. У нас уже есть один болезненный пункт с внешним обработчиком (перевод).
  assert.ok(!/docs\.google|view\.officeapps|mozilla\.github/.test(preview),
    'предпросмотр отдаёт документ стороннему сервису')
  assert.match(preview, /docxText/, 'DOCX больше не разбирается на месте')
})

test('встроенный фрейм — под общим гейтом натива', () => {
  // Правило не про видео: в мобильном приложении страницу отдаёт локальный сервер
  // Capacitor, и заголовки Caddy до неё не доходят. Второй признак «мы в приложении»
  // разошёлся бы с первым молча и в сторону «дверь снова открыта».
  assert.match(preview, /embedMode\(isNativeApp\(\)\)/,
    'гейт считается из собственного признака, а не из общего')
  const tag = preview.match(/<iframe\b[^>]*>/)
  assert.ok(tag, 'фрейма нет — проверять нечего (возможно, PDF перестал показываться)')
  assert.match(tag[0], /v-if="videoIframeAllowed"/, 'фрейм не под гейтом')
})

test('панель шлёт события, а не заводит вторую копию поиска и сводки', () => {
  // Поиск и сводка живут в ленте со своим состоянием. Вторая их копия в панели
  // разошлась бы с первой, и разошлась бы молча.
  assert.match(panel, /emit\('search'\)/, 'кнопка поиска ничего не сообщает наверх')
  assert.match(panel, /emit\('summary'\)/, 'сводка ничего не сообщает наверх')
  assert.ok(!/searchInActive|openSummary/.test(panel),
    'панель сама лезет в поиск/сводку — завелась вторая копия')
  assert.match(thread, /@search="/, 'лента не слушает событие поиска')
  assert.match(thread, /@summary="/, 'лента не слушает событие сводки')
})

test('вкладки грузятся по открытию, а не все сразу', () => {
  // Три лишних запроса на каждое открытие панели ради вкладок, в которые чаще всего не
  // заходят, — плохая сделка на одноядерном сервере.
  const open = panel.split('async function openTab(')[1].split('\n}')[0]
  assert.match(open, /if \(cache\.value\.length\) return/, 'вкладка перезапрашивается каждый раз')
  assert.ok(!/onMounted[\s\S]{0,200}chatMedia/.test(panel), 'медиа грузится до открытия вкладки')
})

test('разбор типов и размеров — общая функция, а не копия в каждом месте', () => {
  assert.equal(previewKind('application/pdf'), 'pdf')
  assert.equal(previewKind('text/csv'), 'text')
  assert.equal(previewKind('application/octet-stream', 'заметки.md'), 'text',
    'запасной признак по имени не работает — часть браузеров отдаёт пустой тип')
  assert.equal(previewKind('application/x-msdownload', 'вирус.exe'), '',
    'для неизвестного типа предпросмотр обязан быть пустым')
  assert.equal(humanSize(0), '0 Б')
  assert.equal(humanSize(2 * 1024 * 1024), '2.0 МБ')
  // Один источник правды: в компонентах своей копии форматирования быть не должно.
  for (const [name, src] of [['ChatThread', thread], ['ConversationInfo', panel]]) {
    assert.ok(/humanSize/.test(src), `${name} не пользуется общей humanSize`)
    assert.ok(!/1024 \* 1024/.test(src), `${name} считает размер сам — вторая копия формата`)
  }
})
