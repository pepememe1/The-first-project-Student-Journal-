// otaVerify.test.mjs — телефон ставит только подписанный и более новый бандл
// (аудит 22.09.2026, находка F-24).
//
// Что держится:
//   • подпись питона (`tools/sign_ota.py`) сходится в JS — общий образец из фикстуры;
//   • подменённая версия, сумма или чужой ключ — отказ, и НИЧЕГО не скачивается;
//   • бандл не новее текущего не ставится, даже подписанный (откат на старую сборку);
//   • новый APK действительно идёт подписанным путём: у сборки с выключенным
//     автообновлением номер не ниже порога — иначе телефон не обновлялся бы НИКАК.
//
// ⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН: `verifyOtaSignature`, всегда отвечающий true, — краснеют три
// теста отказа; убрать сравнение версий — краснеет «откат»; убрать `checksum` из
// `download` — краснеет «скачивает ровно подписанный архив».
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { webcrypto } from 'node:crypto'
import { Buffer } from 'node:buffer'

import { checkSignedUpdate, compareOtaVersions, otaPayload, SIGNED_OTA_FROM_BUILD,
  verifyOtaSignature } from '../src/utils/otaVerify.js'

const subtle = webcrypto.subtle
const fx = JSON.parse(readFileSync(new URL('./fixtures/ota-sig-fixture.json', import.meta.url), 'utf8'))
const good = { version: fx.version, checksum: fx.checksum, sig: fx.sig,
  url: 'https://prod.test/app/bundles/b.zip' }

test('подпись, сделанная питоном, сходится в приложении (одна формула)', async () => {
  assert.equal(otaPayload('1.2.3', 'AB'), 'gradebook-ota:v1:1.2.3:ab')
  assert.equal(await verifyOtaSignature(good, [fx.spki], subtle), true)
})

test('подменённая версия, сумма или чужой ключ — отказ', async () => {
  assert.equal(await verifyOtaSignature({ ...good, version: '9.999999.9999' }, [fx.spki], subtle), false)
  assert.equal(await verifyOtaSignature({ ...good, checksum: 'cd'.repeat(32) }, [fx.spki], subtle), false)
  const keys = JSON.parse(readFileSync(new URL('../src/config/ota-public-keys.json', import.meta.url), 'utf8')).keys
  assert.equal(await verifyOtaSignature(good, keys, subtle), false, 'подпись чужим ключом принята')
  assert.equal(await verifyOtaSignature({ ...good, sig: '' }, [fx.spki], subtle), false)
})

function fakeUpdater() {
  const calls = []
  return {
    calls,
    download: async (o) => { calls.push(['download', o]); return { id: 'B1' } },
    next: async (o) => { calls.push(['next', o]) },
  }
}

const fetchOf = (body) => async () => ({ ok: true, status: 200, json: async () => body })

test('подписанный и более новый бандл скачивается ровно с подписанной суммой', async () => {
  const up = fakeUpdater()
  const res = await checkSignedUpdate({ fetchImpl: fetchOf(good), updateUrl: 'u', keys: [fx.spki],
    currentVersion: '1.260901.0000', updater: up, subtle })
  assert.equal(res.action, 'scheduled')
  assert.deepEqual(up.calls[0], ['download', { url: good.url, version: good.version, checksum: good.checksum }])
  assert.deepEqual(up.calls[1], ['next', { id: 'B1' }])
})

test('без подписи или с неверной — ничего не скачивается', async () => {
  for (const m of [{ ...good, sig: undefined }, { ...good, sig: fx.sig.replace(/^./, (c) => (c === 'A' ? 'B' : 'A')) }]) {
    const up = fakeUpdater()
    const res = await checkSignedUpdate({ fetchImpl: fetchOf(m), updateUrl: 'u', keys: [fx.spki],
      currentVersion: '1.0.0', updater: up, subtle })
    assert.equal(res.action, 'rejected', JSON.stringify(res))
    assert.equal(up.calls.length, 0, 'скачали бандл с неверной подписью')
  }
})

test('откат: подписанный, но не новее текущего — не ставится', async () => {
  const up = fakeUpdater()
  const res = await checkSignedUpdate({ fetchImpl: fetchOf(good), updateUrl: 'u', keys: [fx.spki],
    currentVersion: fx.version, updater: up, subtle })
  assert.equal(res.action, 'none')
  assert.equal(up.calls.length, 0)
  assert.equal(compareOtaVersions('1.260927.1200', '1.260927.0900'), 1)
  assert.equal(compareOtaVersions('1.260101.0000', '1.251231.2359'), 1)
  assert.equal(compareOtaVersions('builtin', '1.0.0'), -1)
})

test('новый APK с выключенным автообновлением идёт подписанным путём', () => {
  const cfg = JSON.parse(readFileSync(new URL('../capacitor.config.json', import.meta.url), 'utf8'))
  const gradle = readFileSync(new URL('../android/app/build.gradle', import.meta.url), 'utf8')
  const code = Number((gradle.match(/versionCode\s+(\d+)/) || [])[1])
  assert.equal(cfg.plugins.CapacitorUpdater.autoUpdate, false, 'плагин снова ставит бандлы сам, без подписи')
  assert.ok(code >= SIGNED_OTA_FROM_BUILD,
    `versionCode ${code} ниже порога ${SIGNED_OTA_FROM_BUILD}: автообновление выключено, а подписанный путь не включится — телефон не обновится никак`)
  const main = readFileSync(new URL('../src/main.js', import.meta.url), 'utf8')
  assert.match(main, /ota\.checkSignedUpdate\(/, 'подписанная проверка обновления не вызывается')
})

test('ключ приложения — настоящий открытый ключ P-256', async () => {
  const keys = JSON.parse(readFileSync(new URL('../src/config/ota-public-keys.json', import.meta.url), 'utf8')).keys
  assert.ok(keys.length >= 1)
  for (const k of keys) {
    const bin = Buffer.from(k, 'base64')
    await subtle.importKey('spki', bin, { name: 'ECDSA', namedCurve: 'P-256' }, false, ['verify'])
  }
})
