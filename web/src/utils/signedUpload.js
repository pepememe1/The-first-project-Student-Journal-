// signedUpload.js — положить файл по подписанной ссылке, которую выдал сервер.
//
// ⚠️ ДВА СПОСОБА, ОДИН КОД. Куда класть файл, решает сервер: в объектное хранилище —
// сырым PUT (иначе подпись не сойдётся), к нам на диск — обычной формой (чтобы
// обработчик остался синхронным и не встал поперёк цикла событий). Клиент про это знать
// не должен: он делает то, что сказано в ответе на подпись. Благодаря этому переезд на
// большую машину не требует правок в браузере.
//
// Одна дверь для мессенджера и для файлов курса (аудит F-26): вторая копия разошлась бы
// с первой на первой же правке способа хранения — и сломалась бы ровно у курсов, где
// файлы грузят реже и заметят позже.

/**
 * @param {{url: string, method?: string, headers?: object, form_field?: string}} sign
 *   ответ сервера на подпись загрузки
 * @param {File|Blob} file
 */
export async function putSigned(sign, file, fetchImpl = globalThis.fetch) {
  let body = file
  if (sign.form_field) {
    body = new FormData()
    body.append(sign.form_field, file, file.name)
  }
  const res = await fetchImpl(sign.url, {
    method: sign.method || 'PUT',
    //У формы заголовок ставит браузер сам (там граница multipart) — свой сломал бы.
    headers: sign.form_field ? undefined : (sign.headers || {}),
    body,
  })
  if (!res.ok) throw new Error(`хранилище отказало: ${res.status}`)
  return res
}
