/**
 * mfaLoginNavigation.test.mjs — вход со вторым фактором обязан ДОВОДИТЬ до кабинета.
 *
 * ━━ ДЕФЕКТ, РАДИ КОТОРОГО ЗАВЕДЁН ЭТОТ ФАЙЛ (03.09.2026) ━━
 * Жалоба Ярослава дословно: «когда входим в админку и вводим код в акк не входит… а
 * после перезагрузки страницы все загружается нормально». Воспроизведено на стенде и
 * доказано записью навигаций: `router.beforeEach` не срабатывал ВООБЩЕ — то есть
 * переход даже не запрашивался.
 *
 * Причина. Окно ввода кода показывается по `v-if="auth.mfaChallenge"`, а стор гасил
 * этот флаг ВНУТРИ `verifyMfa`, до возврата управления. Перерисовка Vue и продолжение
 * `await` живут в одной очереди микрозадач, и перерисовка встаёт в неё первой:
 * компонент размонтируется, `emit('done')` уходит от уже удалённого компонента и не
 * доходит ни до кого. Токены при этом выданы — поэтому после F5 страж роутера видел
 * живую сессию и открывал кабинет, а дефект выглядел мистическим.
 *
 * ⚠️ Ни ошибки, ни предупреждения в консоли при этом нет. Ни сборка, ни линтер такого
 * не видят. Поэтому проверка здесь — на ПОРЯДОК ДЕЙСТВИЙ в исходниках, а не на
 * поведение: поведение это ловится только настоящим браузером.
 *
 * Правило, которое охраняется: КОМПОНЕНТ НЕ СНИМАЕТ СЕБЯ С ЭКРАНА, ПОКА НЕ СООБЩИЛ
 * О РЕЗУЛЬТАТЕ. Состояние, от которого зависит его собственный `v-if`, гасит тот, кто
 * получил управление, — то есть вызывающий.
 */
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const read = (p) =>
  readFileSync(new URL(p, import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1'), 'utf8')

/** Тело функции по её объявлению — до строки, где отступ вернулся на уровень объявления. */
function bodyOf(src, header) {
  const start = src.indexOf(header)
  //>= 0, а не > 0: в обратном ходе объявление стоит первой строкой образца.
  assert.ok(start >= 0, `не нашёл ${header} — образец устарел, и сторож проверяет пустоту`)
  const rest = src.slice(start)
  const lines = rest.split('\n')
  const indent = (lines[0].match(/^\s*/) || [''])[0].length
  const out = [lines[0]]
  for (let i = 1; i < lines.length; i++) {
    const l = lines[i]
    if (l.trim() && (l.match(/^\s*/) || [''])[0].length <= indent && /^\s*[}\w]/.test(l)) {
      out.push(l)
      break
    }
    out.push(l)
  }
  return out.join('\n')
}

const store = read('../src/stores/auth.js')
const page = read('../src/pages/LoginPage.vue')

test('стор не гасит окно кода до того, как сообщил об успехе', () => {
  const body = bodyOf(store, '  async function verifyMfa(code) {')
  // Успешная ветка — до первого `catch`. Именно в ней и стояло обнуление.
  const success = body.split('} catch')[0]
  assert.ok(
    !/mfaChallenge\.value\s*=\s*''/.test(success),
    'verifyMfa снова гасит mfaChallenge в успешной ветке. Это ровно тот дефект: Vue ' +
    'размонтирует окно ввода кода РАНЬШЕ, чем продолжится await у вызывающего, ' +
    "emit('done') уходит от удалённого компонента, и переход не запрашивает никто. " +
    'Наружу — «ввёл код, а меня выкинуло на форму входа» при выданных токенах.',
  )
})

test('незавершённый вход гасит тот, кто получил управление', () => {
  const body = bodyOf(page, 'async function onMfaDone(user) {')
  assert.match(body, /auth\.cancelMfa\(\)/,
    'onMfaDone не гасит незавершённый вход — окно ввода кода останется на экране ' +
    'поверх кабинета, потому что стор его больше не гасит')
  assert.match(body, /router\.push\(/,
    'onMfaDone больше не переводит человека в кабинет — вход второй раз никуда не ведёт')
  assert.ok(body.indexOf('auth.cancelMfa()') < body.indexOf('router.push('),
    'сначала гасим окно, потом переходим: иначе форма входа мелькнёт поверх кабинета')
})

test('обратный ход: сломанный порядок сторож обязан поймать', () => {
  /*
   * Дословно то, как выглядел стор ДО починки. Если такой текст пройдёт как
   * «исправный», проверка выше зелёная при любом откате.
   */
  const broken = [
    '  async function verifyMfa(code) {',
    '    const { data } = await authApi.mfaVerify(mfaChallenge.value, code)',
    '    const u = _afterLogin(data, mfaLogin.value)',
    "    mfaChallenge.value = ''",
    '    return u',
    '  }',
  ].join('\n')
  const success = bodyOf(broken, '  async function verifyMfa(code) {').split('} catch')[0]
  assert.equal(/mfaChallenge\.value\s*=\s*''/.test(success), true,
    'сторож не видит обнуления в сломанном образце — значит он не увидит его и в продукте')

  // И вторая половина: исправный текст обязан считаться исправным.
  const fixed = [
    '  async function verifyMfa(code) {',
    '    const { data } = await authApi.mfaVerify(mfaChallenge.value, code)',
    '    return _afterLogin(data, mfaLogin.value)',
    '  }',
  ].join('\n')
  assert.equal(
    /mfaChallenge\.value\s*=\s*''/.test(bodyOf(fixed, '  async function verifyMfa(code) {')),
    false,
    'сторож считает исправный код сломанным — он будет краснеть на рабочей правке')
})

test('окно кода показывает, сколько времени осталось', () => {
  /*
   * Вторая половина той же жалобы. Окно подтверждения живёт ограниченное время; пока
   * человек ищет нужную запись в аутентификаторе (а называются они одинаково), срок
   * выходит, сервер отвечает 401, окно ПРОПАДАЕТ — и это читается как «выкинуло».
   * Отсчёт превращает необъяснимое исчезновение в ожидаемое событие.
   */
  const prompt = read('../src/components/auth/MfaPrompt.vue')
  assert.match(prompt, /mfaExpiresAt/,
    'окно кода не знает своего срока — отсчёта не будет')
  assert.match(prompt, /setInterval/,
    'отсчёт не идёт: без тика на экране будет застывшее число')
  assert.match(store, /mfaExpiresAt\.value\s*=\s*Date\.now\(\)/,
    'стор не запоминает срок окна — брать его отсчёту неоткуда')
  assert.match(store, /Number\(data\.expires_in\)/,
    'срок окна больше не берётся у сервера. Зашитое в клиенте число разъедется с ' +
    'серверным при первой же правке, и отсчёт начнёт врать')
})
