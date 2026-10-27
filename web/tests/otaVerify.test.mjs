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

import { checkSignedUpdate, compareOtaVersions, filesDigest, otaFilesPayload, otaPayload,
  SIGNED_OTA_FROM_BUILD, verifyOtaFiles,
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

// ── Пофайловое обновление (23.10.2026) ────────────────────────────────────────────
// Плагин в этом режиме сверяет только хеш каждого файла по списку, а сумму архива — нет:
// неподписанный или подменённый список обязан уводить в закачку архива целиком.
// ⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН: `verifyOtaFiles`, всегда отвечающий true, — краснеют «подмена
// списка» и «без подписи списка»; убрать `opts.manifest` — краснеет «только новое».
const ff = JSON.parse(readFileSync(new URL('./fixtures/ota-files-fixture.json', import.meta.url), 'utf8'))
const delta = { version: ff.version, checksum: ff.checksum, sig: ff.sig, files_sig: ff.files_sig,
  manifest: ff.manifest, url: 'https://prod.test/app/bundles/d.zip' }

test('отпечаток списка и его подпись из питона сходятся в приложении', async () => {
  assert.equal(await filesDigest(ff.manifest, subtle), ff.digest)
  assert.equal(await filesDigest([...ff.manifest].reverse(), subtle), ff.digest,
    'отпечаток зависит от порядка, в котором сервер отдал список')
  assert.equal(otaFilesPayload('1.2.3', 'AB', 'ff'), 'gradebook-ota:files:v1:1.2.3:ab:ff')
  assert.equal(await verifyOtaFiles(delta, [ff.spki], subtle), true)
})

test('подменённый список файлов не проходит', async () => {
  const swapped = ff.manifest.map((e, i) => (i ? e : { ...e, file_hash: 'ee'.repeat(32) }))
  const extra = [...ff.manifest, { file_name: 'evil.js', file_hash: 'aa'.repeat(32), download_url: 'x' }]
  for (const manifest of [swapped, extra, ff.manifest.slice(1)]) {
    assert.equal(await verifyOtaFiles({ ...delta, manifest }, [ff.spki], subtle), false)
  }
  assert.equal(await verifyOtaFiles({ ...delta, version: '9.999999.9999' }, [ff.spki], subtle), false)
  assert.equal(await verifyOtaFiles({ ...delta, files_sig: undefined }, [ff.spki], subtle), false)
})

test('подписанный список — качается только новое, по этому самому списку', async () => {
  const up = fakeUpdater()
  const res = await checkSignedUpdate({ fetchImpl: fetchOf(delta), updateUrl: 'u', keys: [ff.spki],
    currentVersion: '1.260901.0000', updater: up, subtle })
  assert.equal(res.mode, 'files')
  assert.deepEqual(up.calls[0], ['download', { url: delta.url, version: delta.version,
    checksum: delta.checksum, manifest: ff.manifest }])
})

test('без подписи списка или с подменённым — архив целиком, а не отказ', async () => {
  const swapped = ff.manifest.map((e, i) => (i ? e : { ...e, file_hash: 'ee'.repeat(32) }))
  for (const m of [{ ...delta, files_sig: undefined }, { ...delta, manifest: swapped }]) {
    const up = fakeUpdater()
    const res = await checkSignedUpdate({ fetchImpl: fetchOf(m), updateUrl: 'u', keys: [ff.spki],
      currentVersion: '1.260901.0000', updater: up, subtle })
    assert.equal(res.action, 'scheduled')
    assert.equal(res.mode, 'zip')
    assert.equal('manifest' in up.calls[0][1], false, 'плагину ушёл неподписанный список')
  }
})

test('ключ приложения — настоящий открытый ключ P-256', async () => {
  const keys = JSON.parse(readFileSync(new URL('../src/config/ota-public-keys.json', import.meta.url), 'utf8')).keys
  assert.ok(keys.length >= 1)
  for (const k of keys) {
    const bin = Buffer.from(k, 'base64')
    await subtle.importKey('spki', bin, { name: 'ECDSA', namedCurve: 'P-256' }, false, ['verify'])
  }
})
