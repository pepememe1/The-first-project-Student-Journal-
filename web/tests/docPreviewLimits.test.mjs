// docPreviewLimits.test.mjs — предпросмотр DOCX не разворачивает «бомбу» (аудит 17.10.2026).
//
// Сжатие у ZIP — до тысячи раз: документ в несколько килобайт разворачивался в
// миллионы знаков, и одно открытие предпросмотра могло съесть память вкладки или окна
// программы у получателя. Теперь распаковка идёт порциями и обрывается на пределе.
//
// ⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН: прежний `docxText` (распаковка целиком, без пределов) —
// краснеют четыре из пяти; «обычный документ» зелёный и стережёт от починки, которая
// обрезала бы честный файл.
import test from 'node:test'
import assert from 'node:assert/strict'
import { Buffer } from 'node:buffer'
import { deflateRawSync } from 'node:zlib'
import { docxText, inflateRaw, DOCX_PREVIEW_LIMITS, DOCX_CUT_MARK } from '../src/utils/docPreview.js'

const crc32 = (() => {
  const table = new Uint32Array(256)
  for (let n = 0; n < 256; n++) {
    let c = n
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1
    table[n] = c >>> 0
  }
  return (buf) => {
    let c = 0xffffffff
    for (const b of buf) c = table[(c ^ b) & 0xff] ^ (c >>> 8)
    return (c ^ 0xffffffff) >>> 0
  }
})()

/** Минимальный ZIP с одним файлом `word/document.xml` — как его пишет Word. */
function docx(xml, { store = false } = {}) {
  const name = Buffer.from('word/document.xml')
  const plain = Buffer.from(xml, 'utf8')
  const data = store ? plain : deflateRawSync(plain, { level: 9 })
  const method = store ? 0 : 8
  const local = Buffer.alloc(30)
  local.writeUInt32LE(0x04034b50, 0); local.writeUInt16LE(20, 4); local.writeUInt16LE(method, 8)
  local.writeUInt32LE(crc32(plain), 14); local.writeUInt32LE(data.length, 18)
  local.writeUInt32LE(plain.length, 22); local.writeUInt16LE(name.length, 26)
  const central = Buffer.alloc(46)
  central.writeUInt32LE(0x02014b50, 0); central.writeUInt16LE(20, 4); central.writeUInt16LE(20, 6)
  central.writeUInt16LE(method, 10); central.writeUInt32LE(crc32(plain), 16)
  central.writeUInt32LE(data.length, 20); central.writeUInt32LE(plain.length, 24)
  central.writeUInt16LE(name.length, 28); central.writeUInt32LE(0, 42)
  const cdOffset = local.length + name.length + data.length
  const eocd = Buffer.alloc(22)
  eocd.writeUInt32LE(0x06054b50, 0); eocd.writeUInt16LE(1, 8); eocd.writeUInt16LE(1, 10)
  eocd.writeUInt32LE(central.length + name.length, 12); eocd.writeUInt32LE(cdOffset, 16)
  const zip = Buffer.concat([local, name, data, central, name, eocd])
  return zip.buffer.slice(zip.byteOffset, zip.byteOffset + zip.length)
}

const para = (t) => `<w:p><w:r><w:t>${t}</w:t></w:r></w:p>`
const body = (inner) => `<?xml version="1.0"?><w:document><w:body>${inner}</w:body></w:document>`

test('обычный документ показывается целиком и без метки обрезки', async () => {
  const out = await docxText(docx(body(para('Лекция 1') + para('Тема: деревья'))))
  assert.deepEqual(out, ['Лекция 1', 'Тема: деревья'])
})

test('«бомба»: килобайты архива не разворачиваются в миллионы знаков', async () => {
  const huge = body(para('а'.repeat(20 * 1024 * 1024)))           // 20 МБ разметки
  const zip = docx(huge)
  assert.ok(zip.byteLength < 200 * 1024, `архив должен быть маленьким: ${zip.byteLength}`)
  const out = await docxText(zip)
  const chars = out.filter((p) => p !== DOCX_CUT_MARK).join('').length
  assert.ok(chars <= DOCX_PREVIEW_LIMITS.chars, `показано ${chars} знаков`)
  assert.equal(out.at(-1), DOCX_CUT_MARK, 'обрезанный предпросмотр обязан это сказать')
})

test('распаковка останавливается на пределе, а не после', async () => {
  const raw = deflateRawSync(Buffer.alloc(10 * 1024 * 1024, 0x61))
  const { bytes, truncated } = await inflateRaw(raw, 64 * 1024)
  assert.equal(truncated, true)
  assert.equal(bytes.length, 64 * 1024)
  const small = await inflateRaw(deflateRawSync(Buffer.from('ровно')), 64 * 1024)
  assert.equal(small.truncated, false)
  assert.equal(Buffer.from(small.bytes).toString(), 'ровно')
})

test('сотни тысяч абзацев режутся по числу абзацев', async () => {
  const out = await docxText(docx(body(para('x').repeat(300_000))))
  assert.ok(out.length <= DOCX_PREVIEW_LIMITS.paragraphs + 1, `абзацев: ${out.length}`)
  assert.equal(out.at(-1), DOCX_CUT_MARK)
})

test('файл без сжатия ограничен тем же пределом', async () => {
  const out = await docxText(docx(body(para('б'.repeat(6 * 1024 * 1024))), { store: true }))
  const chars = out.filter((p) => p !== DOCX_CUT_MARK).join('').length
  assert.ok(chars <= DOCX_PREVIEW_LIMITS.chars, `показано ${chars} знаков`)
  assert.equal(out.at(-1), DOCX_CUT_MARK)
})
