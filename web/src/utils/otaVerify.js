/**
 * otaVerify.js — подписанное обновление «по воздуху» (аудит 22.09.2026, находка F-24).
 *
 * 🔥 ЗАЧЕМ. До 4.1 плагин Capgo сам скачивал и ставил любой бандл, который отдавал
 * `/app/updates`, сверяя только SHA-256 — а сумма едет в том же манифесте, что и ссылка на
 * архив. Получивший доступ к хранилищу бандлов или к учётке выкладки подменил бы и то и
 * другое, и телефоны сами поставили бы чужой JavaScript — внутрь приложения с токеном и
 * данными людей.
 *
 * Теперь (APK с `autoUpdate: false`, сборка ≥ `SIGNED_OTA_FROM_BUILD`) обновление ведёт
 * интерфейс сам: берёт манифест, проверяет подпись ECDSA P-256 над парой «версия + сумма»
 * ключом, вшитым в приложение, отвергает не-новее текущего (откат на старый подписанный
 * бандл) и только потом просит плагин скачать архив С ЭТОЙ суммой — сверяет её плагин.
 *
 * ⚠️ Проверка — встроенным WebCrypto, без библиотек: самописная криптография в приложении
 * хуже отсутствующей, а P-256 WebCrypto умеет в любом WebView (Ed25519 — не везде).
 * ⚠️ Старые APK (сборка < 14) по-прежнему обновляются сами, как раньше: их нативный
 * конфиг не поменять ничем, кроме перезалива. Этот код для них ничего не делает — иначе
 * бандл качался бы дважды.
 * ⚠️ Формула подписи — ОДНА с `tools/sign_ota.py::ota_payload`; их согласие держит общий
 * образец `web/tests/fixtures/ota-sig-fixture.json`, подписанный питоном.
 */

//Первая сборка APK, в которой автообновление выключено и обновление ведёт этот модуль.
export const SIGNED_OTA_FROM_BUILD = 14

/** Что подписано: версия и SHA-256 архива (см. шапку `tools/sign_ota.py`). */
export function otaPayload(version, checksum) {
  return `gradebook-ota:v1:${version}:${String(checksum || '').toLowerCase()}`
}

function b64ToBytes(s) {
  const bin = atob(String(s || ''))
  const out = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i)
  return out
}

/** Сходится ли подпись манифеста хотя бы с одним из ключей. Ничего не бросает. */
export async function verifyOtaSignature(manifest, keys, subtle = globalThis.crypto?.subtle) {
  if (!subtle || !manifest || !manifest.sig || !manifest.version || !manifest.checksum) {
    return false
  }
  let sig
  try {
    sig = b64ToBytes(manifest.sig)
  } catch {
    return false
  }
  if (sig.length !== 64) return false
  const data = new TextEncoder().encode(otaPayload(manifest.version, manifest.checksum))
  for (const k of keys || []) {
    try {
      const key = await subtle.importKey('spki', b64ToBytes(k),
        { name: 'ECDSA', namedCurve: 'P-256' }, false, ['verify'])
      if (await subtle.verify({ name: 'ECDSA', hash: 'SHA-256' }, key, sig, data)) return true
    } catch { /* битый ключ в списке — пробуем следующий */ }
  }
  return false
}

/**
 * Сравнение версий бандла вида «1.ГГММДД.ЧЧММ» по частям числами (1 — a новее, −1 — b,
 * 0 — равны). Нечисловая часть считается нулём: «builtin» и пустая версия — самые старые.
 */
export function compareOtaVersions(a, b) {
  const pa = String(a || '').split('.').map((x) => parseInt(x, 10) || 0)
  const pb = String(b || '').split('.').map((x) => parseInt(x, 10) || 0)
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const d = (pa[i] || 0) - (pb[i] || 0)
    if (d) return d > 0 ? 1 : -1
  }
  return 0
}

/**
 * Один проход проверки обновления. Возвращает {action, reason?, version?}:
 *   none      — обновления нет или оно не новее текущего;
 *   rejected  — манифест без подписи или подпись не сходится (НИЧЕГО не скачано);
 *   scheduled — бандл скачан с подписанной суммой и встанет при следующем запуске.
 * Сеть, плагин и WebCrypto подаются снаружи — проверяется правило, а не телефон.
 */
export async function checkSignedUpdate({ fetchImpl, updateUrl, keys, currentVersion,
  updater, subtle }) {
  const r = await fetchImpl(updateUrl, { headers: { Accept: 'application/json' } })
  if (!r || !r.ok) return { action: 'none', reason: `http ${r ? r.status : 0}` }
  const m = await r.json()
  if (!m || !m.version || !m.url) return { action: 'none', reason: 'no update' }
  if (compareOtaVersions(m.version, currentVersion) <= 0) {
    return { action: 'none', reason: 'not newer', version: m.version }
  }
  if (!m.sig || !m.checksum) return { action: 'rejected', reason: 'unsigned', version: m.version }
  if (!(await verifyOtaSignature(m, keys, subtle))) {
    return { action: 'rejected', reason: 'bad-signature', version: m.version }
  }
  const bundle = await updater.download({ url: m.url, version: m.version, checksum: m.checksum })
  await updater.next({ id: bundle.id })
  return { action: 'scheduled', version: m.version }
}
