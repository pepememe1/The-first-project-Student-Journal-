<script setup>
// MicButton — голосовой ввод для Вектора: жмём → говорим → жмём → текст в поле.
//
// Кнопка ПОЯВЛЯЕТСЯ, только когда сервер подтвердил готовность распознавать. Иначе её
// нет вовсе: микрофон, который записывает и молча ничего не даёт, хуже отсутствующего.
// Внутри программы запрос уходит на локальный сервер (127.0.0.1) — запись не покидает
// компьютер; на сайте это сервер колледжа. Код один, разница только в адресе.
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { Mic, Square } from '@lucide/vue'
import { recordingSupported, browserRecognitionSupported, sttStatus, startVoice } from '@/utils/voiceInput'
import { useVoiceStore } from '@/stores/voice'
import { useLocaleStore } from '@/stores/locale'
import haptics from '@/utils/haptics'

const emit = defineEmits(['text', 'error'])

//Настройки устройства: тумблер и выбранный микрофон (см. `stores/voice.js`).
const voice = useVoiceStore()
const locale = useLocaleStore()

// Кнопку показываем, если браузер УМЕЕТ записывать. Готовность распознавателя влияет
// только на активность, а не на видимость: пока она решала «показывать ли», человек не
// мог отличить «функции нет» от «функция не настроена» — искал микрофон и не находил.
// Так и вышло на проверке: движок и распознаватель были готовы, а кнопки не было.
const supported = ref(false)
const ready = ref(false)
const reason = ref('')
const recording = ref(false)
const busy = ref(false)
let session = null

//Выключенный в настройках голосовой ввод убирает кнопку СОВСЕМ, а не гасит её. Здесь это
//не «функция не настроена» (тогда полезно объяснить), а прямое решение человека — вечная
//серая кнопка была бы напоминанием о том, что он только что отключил.
const visible = computed(() => supported.value && voice.enabled)

//Каким движком распознавать — говорит сервер (Whisper на хосте или сам браузер).
const engine = ref('')

onMounted(async () => {
  //Браузерному распознаванию MediaRecorder не нужен — оно само работает с микрофоном.
  //Поэтому «умеет записывать» = либо запись, либо встроенное распознавание.
  supported.value = recordingSupported() || browserRecognitionSupported()
  if (!supported.value) {
    reason.value = locale.t('micButton.notSupported', 'Этот браузер не умеет записывать звук.')
    return
  }
  const st = await sttStatus()
  engine.value = st.engine
  ready.value = st.available
  if (!ready.value) reason.value = st.reason || locale.t('micButton.notConfigured', 'Распознавание речи не настроено на сервере.')
})

// Микрофон нужно отпустить, даже если человек ушёл со страницы во время записи —
// иначе в системе остаётся гореть индикатор записи.
onUnmounted(() => { if (session) session.stop().catch(() => {}) })

async function toggle() {
  if (busy.value) return
  if (!ready.value) { emit('error', reason.value); return }
  if (!recording.value) {
    try {
      session = await startVoice(engine.value, voice.effectiveDeviceId)
      recording.value = true
      //Запись ПОШЛА. Случай «палец действует вслепую» в чистом виде: между нажатием и
      //реальным стартом записи есть задержка (разрешение, инициализация устройства), и
      //без отдачи человек говорит в ещё не начавшийся микрофон, а понимает это только по
      //пустому результату.
      haptics.tap()
    } catch {
      emit('error', locale.t('micButton.noMicAccess', 'Нет доступа к микрофону. Разрешите запись в настройках.'))
    }
    return
  }
  recording.value = false
  //Запись ОСТАНОВЛЕНА — можно опускать телефон и не договаривать в тишину.
  haptics.tap()
  busy.value = true
  try {
    const text = await session.stop()
    if (text) emit('text', text)
    else { haptics.error(); emit('error', locale.t('micButton.noSpeechRecognized', 'Не удалось разобрать речь — попробуйте ещё раз.')) }
  } catch (e) {
    haptics.error()
    emit('error', e.message || locale.t('micButton.recognitionFailed', 'Не удалось распознать речь.'))
  } finally {
    session = null
    busy.value = false
  }
}
</script>

<template>
  <button v-if="visible" type="button" @click="toggle" :disabled="busy"
          :aria-label="recording ? locale.t('micButton.stopRecording', 'Остановить запись') : locale.t('micButton.voiceInput', 'Голосовой ввод')"
          :title="!ready ? reason : (recording ? locale.t('micButton.stopAndRecognize', 'Остановить и распознать') : locale.t('micButton.speak', 'Сказать голосом'))"
          class="grid size-11 shrink-0 place-items-center rounded-sm border transition-colors disabled:opacity-50"
          :class="recording
            ? 'animate-pulse border-red bg-red/15 text-red'
            : (ready
              ? 'border-border2 bg-card2 text-text2 hover:border-accent hover:text-accent'
              : 'border-border2 bg-card2 text-text3 opacity-60')">
    <Square v-if="recording" class="size-4" />
    <Mic v-else class="size-5" />
  </button>
</template>
