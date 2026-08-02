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
import { useLocaleStore } from '@/stores/locale'

/** Поддерживает ли браузер запись вообще (в старых и в http-контексте — нет). */
export function recordingSupported() {
  return !!(navigator.mediaDevices?.getUserMedia && window.MediaRecorder)
}

/** Умеет ли САМ браузер распознавать речь (Web Speech API, Chrome/Edge). */
export function browserRecognitionSupported() {
  return !!(window.SpeechRecognition || window.webkitSpeechRecognition)
}

/**
 * Чем распознавать: спрашиваем СЕРВЕР, а не решаем на клиенте.
 * Возвращает { available, engine, reason }: engine — 'whisper' | 'browser' | ''.
 *
 * Почему решает сервер. Во-первых, у администратора есть переключатель «распознавать на
 * сервере для всех» — клиент не может его знать. Во-вторых, десктоп и сайт обязаны вести
 * себя одинаково, а «есть ли на хосте Whisper» видно только хосту.
 */
export async function sttStatus() {
  try {
    const { data } = await api.get('/web/vector/stt/status')
    const engine = data?.engine || ''
    //Сервер отдал 'browser', но браузер этого не умеет (Firefox/Safari) — честно
    //сообщаем, а не оставляем кнопку, которая ничего не сделает.
    if (engine === 'browser' && !browserRecognitionSupported()) {
      return { available: false, engine: '',
               reason: useLocaleStore().t('voiceInput.browserUnsupported', 'Этот браузер не умеет распознавать речь. Откройте в Chrome или Edge.') }
    }
    return { available: !!data?.available && !!engine, engine, reason: data?.reason || '' }
  } catch {
    return { available: false, engine: '', reason: useLocaleStore().t('voiceInput.statusUnknown', 'Не удалось узнать, доступен ли голосовой ввод.') }
  }
}

/** Совместимость с прежним вызовом: просто «доступен ли голосовой ввод». */
export async function sttAvailable() {
  return (await sttStatus()).available
}

/**
 * Список микрофонов для выбора в настройках: [{ deviceId, label }].
 *
 * ⚠️ Браузер скрывает НАЗВАНИЯ устройств, пока не выдано разрешение на микрофон — до
 * этого приходит список пустых «label». Поэтому `ask=true` (только из жеста человека)
 * коротко открывает поток и сразу закрывает: это штатный способ узнать названия, другого
 * нет. Без разрешения возвращаем то, что есть, с честными подписями «Микрофон 1/2/…» —
 * пустой список выглядел бы как «микрофонов нет», хотя они есть.
 */
export async function listMicrophones(ask = false) {
  if (!navigator.mediaDevices?.enumerateDevices) return []
  if (ask) {
    //Поток нужен на мгновение — ровно чтобы браузер раскрыл названия. Дорожки закрываем
    //в том же вызове, иначе у человека останется горящий индикатор записи.
    const probe = await navigator.mediaDevices.getUserMedia({ audio: true })
    probe.getTracks().forEach((t) => t.stop())
  }
  const all = await navigator.mediaDevices.enumerateDevices()
  return all
    .filter((d) => d.kind === 'audioinput')
    .map((d, i) => ({ deviceId: d.deviceId, label: d.label || useLocaleStore().t('voiceInput.microphoneN', { n: i + 1 }) }))
}

/**
 * Начать распознавание ТЕМ движком, который назначил сервер. Единая точка входа для
 * интерфейса: кнопка микрофона не должна знать, кто именно распознаёт.
 */
export async function startVoice(engine, deviceId = '') {
  return engine === 'browser'
    ? startBrowserRecognition()
    : startRecording(deviceId)
}

/**
 * Распознавание СИЛАМИ БРАУЗЕРА (Web Speech API).
 *
 * ⚠️ Важное отличие от Whisper: браузер (Chrome/Edge) отправляет звук на серверы Google,
 * то есть третьей стороне. Для журнала с ПДн это допустимо ТОЛЬКО потому, что здесь
 * распознаётся вопрос помощнику, а не данные студентов, — и потому что это осознанный
 * выбор администратора (режим `browser`). Основной путь — Whisper на своём хосте.
 *
 * Интерфейс намеренно ТОТ ЖЕ, что у записи на сервер ({ stop }): кнопка микрофона не
 * должна знать, кто распознаёт.
 */
export function startBrowserRecognition() {
  const locale = useLocaleStore()
  const Ctor = window.SpeechRecognition || window.webkitSpeechRecognition
  if (!Ctor) throw new Error(locale.t('voiceInput.browserUnsupportedShort', 'Этот браузер не умеет распознавать речь.'))
  const rec = new Ctor()
  // Распознаём НА ЯЗЫКЕ ИНТЕРФЕЙСА: иностранный студент, выбравший английский, не станет
  // диктовать команды по-русски.
  rec.lang = { ru: 'ru-RU', en: 'en-US', zh: 'zh-CN' }[locale.active] || 'ru-RU'
  rec.continuous = true          //не обрывать на первой паузе: команда бывает длинной
  rec.interimResults = false     //нужен итог, черновые варианты только мигали бы
  let text = ''
  let failure = ''
  rec.onresult = (e) => {
    for (let i = e.resultIndex; i < e.results.length; i += 1) {
      if (e.results[i].isFinal) text += `${e.results[i][0].transcript} `
    }
  }
  rec.onerror = (e) => {
    //Запоминаем причину, но НЕ бросаем здесь: обработчик события — не наш стек вызова,
    //исключение из него до кнопки не дойдёт и человек увидит «просто ничего».
    failure = e?.error === 'not-allowed'
      ? locale.t('voiceInput.micDenied', 'Нет доступа к микрофону. Разрешите запись в настройках.')
      : locale.t('voiceInput.recognitionFailed', 'Не удалось распознать речь.')
  }
  rec.start()

  return {
    async stop() {
      const done = new Promise((resolve) => { rec.onend = resolve })
      rec.stop()
      await done
      if (failure && !text.trim()) throw new Error(failure)
      return text.trim()
    },
  }
}

/**
 * Пишет с микрофона, пока не позовут stop(); распознаёт на СЕРВЕРЕ (Whisper).
 * Возвращает { stop } — stop() отдаёт текст (или бросает ошибку с человеческой причиной).
 *
 * `deviceId` — выбранный в настройках микрофон; пусто = системный по умолчанию.
 */
export async function startRecording(deviceId = '') {
  const locale = useLocaleStore()
  //`exact` НЕ используем осознанно: с ним исчезнувшее устройство (отключили гарнитуру)
  //даёт OverconstrainedError и голосовой ввод просто перестаёт работать. Без `exact`
  //браузер сам берёт системный микрофон — лучше записать не тем, чем ничем.
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: deviceId ? { deviceId } : true,
  })
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
      if (!blob.size) throw new Error(locale.t('voiceInput.nothingRecorded', 'Ничего не записалось — проверьте микрофон.'))
      const form = new FormData()
      form.append('file', blob, 'audio.webm')
      try {
        const { data } = await api.post('/web/vector/stt', form)
        return (data?.text || '').trim()
      } catch (e) {
        const status = e.response?.status
        if (status === 503) throw new Error(locale.t('voiceInput.notConfigured', 'Голосовой ввод не настроен на сервере.'))
        if (status === 413) throw new Error(locale.t('voiceInput.tooLong', 'Запись слишком длинная — скажите короче.'))
        throw new Error(e.response?.data?.detail || locale.t('voiceInput.recognitionFailed', 'Не удалось распознать речь.'))
      }
    },
  }
}
