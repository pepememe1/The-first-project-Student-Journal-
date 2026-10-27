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
 *
 * ПОФАЙЛОВО (23.10.2026). С 4.1 скачивался весь архив: список файлов, по которому плагин
 * качает только изменённое, подписан не был, а в этом режиме плагин сверяет лишь хеш
 * каждого файла по списку — подменённый список провёл бы чужой файл. Теперь выпуск
 * подписывает и отпечаток списка (`files_sig`, `ota_files.py`): сошлась подпись — плагин
 * берёт неизменённое из своего кэша и встроенного бандла, качает только новое; нет — весь
 * архив под `sig`, как раньше. Отпечаток — `filesDigest`, общий образец с питоном —
 * `web/tests/fixtures/ota-files-fixture.json`.
 */

//Первая сборка APK, в которой автообновление выключено и обновление ведёт этот модуль.
export const SIGNED_OTA_FROM_BUILD = 14

/** Что подписано: версия и SHA-256 архива (см. шапку `tools/sign_ota.py`). */
export function otaPayload(version, checksum) {
  return `gradebook-ota:v1:${version}:${String(checksum || '').toLowerCase()}`
}

/** Что подписано для пофайловой закачки. ОДНА формула с `sign_ota.py::ota_files_payload`. */
export function otaFilesPayload(version, checksum, digest) {
  return `gradebook-ota:files:v1:${version}:${String(checksum || '').toLowerCase()}:${digest}`
}

//Порядок строк — по кодовым единицам, как `sorted()` в питоне для имён из ASCII; не
//`localeCompare`, у которого порядок зависит от языка телефона.
function byCodeUnits(a, b) { return a < b ? -1 : (a > b ? 1 : 0) }

/** Отпечаток списка файлов (SHA-256 hex) — та же формула, что `ota_files.files_digest`. */
export async function filesDigest(entries, subtle = globalThis.crypto?.subtle) {
  const lines = (entries || [])
    .map((e) => `${e.file_name}:${String(e.file_hash || '').toLowerCase()}`)
    .sort(byCodeUnits)
  const buf = await subtle.digest('SHA-256', new TextEncoder().encode(lines.join('\n')))
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, '0')).join('')
}

function b64ToBytes(s) {
  const bin = atob(String(s || ''))
  const out = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i)
  return out
}

async function verifyPayload(payload, sigB64, keys, subtle) {
  let sig
  try {
    sig = b64ToBytes(sigB64)
  } catch {
    return false
  }
  if (sig.length !== 64) return false
  const data = new TextEncoder().encode(payload)
  for (const k of keys || []) {
    try {
      const key = await subtle.importKey('spki', b64ToBytes(k),
        { name: 'ECDSA', namedCurve: 'P-256' }, false, ['verify'])
      if (await subtle.verify({ name: 'ECDSA', hash: 'SHA-256' }, key, sig, data)) return true
    } catch { /* битый ключ в списке — пробуем следующий */ }
  }
  return false
}

/** Сходится ли подпись манифеста хотя бы с одним из ключей. Ничего не бросает. */
export async function verifyOtaSignature(manifest, keys, subtle = globalThis.crypto?.subtle) {
  if (!subtle || !manifest || !manifest.sig || !manifest.version || !manifest.checksum) {
    return false
  }
  return verifyPayload(otaPayload(manifest.version, manifest.checksum), manifest.sig, keys, subtle)
}

/**
 * Подписан ли список файлов (`manifest.manifest`) — отпечаток считается здесь, из того
 * самого списка, который уйдёт плагину. Ничего не бросает.
 */
export async function verifyOtaFiles(manifest, keys, subtle = globalThis.crypto?.subtle) {
  const list = manifest?.manifest
  if (!subtle || !manifest?.files_sig || !Array.isArray(list) || !list.length) return false
  if (!list.every((e) => e && typeof e.file_name === 'string' && e.file_name
                     && typeof e.file_hash === 'string' && typeof e.download_url === 'string')) {
    return false
  }
  try {
    const digest = await filesDigest(list, subtle)
    return verifyPayload(otaFilesPayload(manifest.version, manifest.checksum, digest),
      manifest.files_sig, keys, subtle)
  } catch {
    return false
  }
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
 *   scheduled — бандл скачан с подписанной суммой и встанет при следующем запуске;
 *               `mode` — `files` (только изменённые файлы по подписанному списку) или
 *               `zip` (архив целиком).
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
  const opts = { url: m.url, version: m.version, checksum: m.checksum }
  const byFiles = await verifyOtaFiles(m, keys, subtle)
  if (byFiles) opts.manifest = m.manifest
  const bundle = await updater.download(opts)
  await updater.next({ id: bundle.id })
  return { action: 'scheduled', version: m.version, mode: byFiles ? 'files' : 'zip' }
}
