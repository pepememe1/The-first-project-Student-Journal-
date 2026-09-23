// accountFeatures40.test.mjs — клиентская половина выпуска 4.0: кому видны достижения,
// откуда страница настроек берёт список уведомлений, как живёт секрет доверенного
// устройства.
//
// Проверки — по тексту исходников (без браузера): каждая с обратным ходом на дословно
// сломанном образце, иначе сторож неотличим от сломанного разбора.
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const read = (p) =>
  readFileSync(new URL(p, import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1'), 'utf8')

// ── Достижения — только студенту ─────────────────────────────────────────────────
function achievementsCardIsStudentOnly(src) {
  const tag = (src.match(/<Card\b[^>]*id="set-achievements"[^>]*>/) || [''])[0]
  return /v-if="auth\.role === 'student'"/.test(tag)
}
function claimIsStudentOnly(src) {
  const body = src.split('async function claim(egg) {')[1] || ''
  const head = body.split('easterApi.claim')[0]
  return /role !== 'student'\) return false/.test(head)
}

test('раздел достижений виден только студенту', () => {
  assert.ok(achievementsCardIsStudentOnly(read('../src/pages/Profile.vue')),
    'карточка «Достижения» показывается не только студенту')
  assert.ok(claimIsStudentOnly(read('../src/stores/easterEggs.js')),
    'ачивка закрывается у любой роли — тост позовёт в раздел, которого у неё нет')
})

test('обратный ход: сторож достижений видит карточку без условия', () => {
  assert.equal(achievementsCardIsStudentOnly('<Card id="set-achievements" :title="x">'), false)
  assert.equal(claimIsStudentOnly('async function claim(egg) {\n  const { data } = await easterApi.claim()'), false)
})

// ── Уведомления: список роли приходит с сервера ─────────────────────────────────
function notifyListIsServerDriven(src) {
  const block = src.split('const NOTIFY_KINDS = computed(() => [')[1]?.split('])')[0] || ''
  const noLocalRoles = !/roles:\s*\[/.test(block)
  const filtered = /notifyAllowed\.value\.includes\(k\.key\)/.test(src)
  const fed = /data\?\.notify_categories/.test(src)
  return noLocalRoles && filtered && fed
}

test('какие переключатели уведомлений показать — решает сервер', () => {
  assert.ok(notifyListIsServerDriven(read('../src/pages/Settings.vue')),
    'страница настроек держит свой список категорий по ролям — он разойдётся с тем, ' +
    'по которому сервер решает, слать ли пуш')
})

test('обратный ход: сторож ловит возвращённый список ролей на странице', () => {
  const broken = "const NOTIFY_KINDS = computed(() => [\n  { key: 'risk', roles: ['teacher'] },\n])\n" +
    'notifyAllowed.value.includes(k.key)\ndata?.notify_categories'
  assert.equal(notifyListIsServerDriven(broken), false)
})

// ── Доверенное устройство ────────────────────────────────────────────────────────
test('секрет устройства ключуется логином и переживает выход', () => {
  const util = read('../src/utils/trustToken.js')
  assert.match(util, /PREFIX \+ String\(login/, 'ключ секрета без логина — общий на всех')
  const store = read('../src/stores/auth.js')
  //CRLF в рабочей копии Windows: граница функции — регуляркой, а не строкой с '\n'.
  const end = /\r?\n {2}\}\r?\n/
  const logout = store.split('async function logout() {')[1].split(end)[0]
  assert.doesNotMatch(logout, /dropTrustToken/,
    'выход стирает доверие — а обещано ещё 15 дней без кода из письма')
  //Вход по биометрии не должен снимать доверие: он галочки не видит.
  const passkey = store.split('async function loginPasskey() {')[1].split(end)[0]
  assert.doesNotMatch(passkey, /trustFlow: true/)
})

test('уведомление «пароль изменён» ведёт к сессиям', () => {
  const push = read('../src/services/push.js')
  assert.match(push, /case 'password_changed':\s*\n\s*return \{ path: `\$\{base\}\/settings`, query: \{ section: 'sessions' \} \}/)
  assert.match(read('../src/pages/Settings.vue'), /route\.query\.section === 'sessions'/)
})
