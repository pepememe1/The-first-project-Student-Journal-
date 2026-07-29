<script setup>
// MicButton — голосовой ввод для Вектора: жмём → говорим → жмём → текст в поле.
//
// Кнопка ПОЯВЛЯЕТСЯ, только когда сервер подтвердил готовность распознавать. Иначе её
// нет вовсе: микрофон, который записывает и молча ничего не даёт, хуже отсутствующего.
// Внутри программы запрос уходит на локальный сервер (127.0.0.1) — запись не покидает
// компьютер; на сайте это сервер колледжа. Код один, разница только в адресе.
import { ref, onMounted, onUnmounted } from 'vue'
import { Mic, Square } from '@lucide/vue'
import { recordingSupported, sttAvailable, startRecording } from '@/utils/voiceInput'

const emit = defineEmits(['text', 'error'])

const available = ref(false)
const recording = ref(false)
const busy = ref(false)
let session = null

onMounted(async () => {
  if (!recordingSupported()) return
  available.value = await sttAvailable()
})

// Микрофон нужно отпустить, даже если человек ушёл со страницы во время записи —
// иначе в системе остаётся гореть индикатор записи.
onUnmounted(() => { if (session) session.stop().catch(() => {}) })

async function toggle() {
  if (busy.value) return
  if (!recording.value) {
    try {
      session = await startRecording()
      recording.value = true
    } catch {
      emit('error', 'Нет доступа к микрофону. Разрешите запись в настройках.')
    }
    return
  }
  recording.value = false
  busy.value = true
  try {
    const text = await session.stop()
    if (text) emit('text', text)
    else emit('error', 'Не удалось разобрать речь — попробуйте ещё раз.')
  } catch (e) {
    emit('error', e.message || 'Не удалось распознать речь.')
  } finally {
    session = null
    busy.value = false
  }
}
</script>

<template>
  <button v-if="available" type="button" @click="toggle" :disabled="busy"
          :aria-label="recording ? 'Остановить запись' : 'Голосовой ввод'"
          :title="recording ? 'Остановить и распознать' : 'Сказать голосом'"
          class="grid size-11 shrink-0 place-items-center rounded-sm border transition-colors disabled:opacity-50"
          :class="recording
            ? 'animate-pulse border-red bg-red/15 text-red'
            : 'border-border2 bg-card2 text-text2 hover:border-accent hover:text-accent'">
    <Square v-if="recording" class="size-4" />
    <Mic v-else class="size-5" />
  </button>
</template>
