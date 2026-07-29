/**
 * voiceInput.js — запись голоса в браузере и распознавание на сервере.
 *
 * ГДЕ ПРОИСХОДИТ РАСПОЗНАВАНИЕ. Не в браузере: звук уходит на `/web/vector/stt` того
 * сервера, с которого открыт интерфейс. Внутри программы это ЛОКАЛЬНЫЙ сервер на
 * 127.0.0.1 — значит запись не покидает компьютер (152-ФЗ), хотя код ровно тот же, что
 * на сайте. Разница между «на этом ПК» и «на сервере колледжа» — это разница адреса, а
 * не отдельная реализация.
 *
 * ⚠️ Кнопку показываем ТОЛЬКО когда сервер подтвердил готовность (`/vector/stt/status`):
 * без распознавателя микрофон записал бы и молча ничего не дал, а неработающая кнопка
 * хуже отсутствующей.
 */
import { api } from '@/api/client'

/** Поддерживает ли браузер запись вообще (в старых и в http-контексте — нет). */
export function recordingSupported() {
  return !!(navigator.mediaDevices?.getUserMedia && window.MediaRecorder)
}

/** Готов ли сервер распознавать (false — кнопку не показываем). */
export async function sttAvailable() {
  try {
    const { data } = await api.get('/web/vector/stt/status')
    return !!data?.available
  } catch {
    return false
  }
}

/**
 * Пишет с микрофона, пока не позовут stop(). Возвращает { stop } — stop() отдаёт
 * распознанный текст (или бросает ошибку с человеческой причиной).
 */
export async function startRecording() {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
  // webm/opus — то, что умеют все актуальные браузеры и понимает ffmpeg на стороне
  // распознавателя. Явный тип, а не «по умолчанию»: умолчание у браузеров разное.
  const mime = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
    ? 'audio/webm;codecs=opus' : ''
  const rec = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined)
  const chunks = []
  rec.ondataavailable = (e) => { if (e.data?.size) chunks.push(e.data) }
  rec.start()

  return {
    async stop() {
      const done = new Promise((resolve) => { rec.onstop = resolve })
      rec.stop()
      await done
      // Микрофон отпускаем ВСЕГДА, даже если распознавание упадёт: иначе в системе
      // остаётся гореть индикатор записи, и человек справедливо решит, что его слушают.
      stream.getTracks().forEach((t) => t.stop())
      const blob = new Blob(chunks, { type: mime || 'audio/webm' })
      if (!blob.size) throw new Error('Ничего не записалось — проверьте микрофон.')
      const form = new FormData()
      form.append('file', blob, 'audio.webm')
      try {
        const { data } = await api.post('/web/vector/stt', form)
        return (data?.text || '').trim()
      } catch (e) {
        const status = e.response?.status
        if (status === 503) throw new Error('Голосовой ввод не настроен на сервере.')
        if (status === 413) throw new Error('Запись слишком длинная — скажите короче.')
        throw new Error(e.response?.data?.detail || 'Не удалось распознать речь.')
      }
    },
  }
}
