<script setup>
// Far Cry 3: седьмая неудачная попытка входа подряд.
//
// ⚠️ Седьмая, а НЕ восьмая. Исторически анти-брутфорс запирал пару (IP, логин) ровно
// на седьмой (`throttle.MAX_FAILS` был 7), и до восьмой проверки пароля дело не
// доходило — пасхалка на восьмой не сработала бы никогда. С 24.08.2026 порог поднят до
// 8, но условие оставлено семёркой намеренно: цитате про «повторять одно и то же» место
// ДО замка. Связь порогов больше не автоматическая — вернёшь `MAX_FAILS` в 7, и
// пасхалка снова окажется за запертой дверью.
//
// Субтитры раскладываются по РЕАЛЬНОЙ длительности файла: жёстких таймкодов нет, чтобы
// замена озвучки не рассыпала синхронизацию.
import { onMounted, onBeforeUnmount, ref } from 'vue'
import { easterSound } from '@/utils/easterAssetUrl'
import { whenAudioReady } from '@/utils/audioReady'
const emit = defineEmits(['close'])

const LINES = ['Я уже говорил тебе, что такое безумие?', 'Безумие —', 'это',
  'точное повторение', 'одного и того же действия', 'раз за разом',
  'в надежде на… изменения.', 'Ты ждёшь, что в этот раз пароль подойдёт?',
  'Но этого не происходит.', 'Это… есть… безумие.']

const line = ref('')
let audio = null, timers = [], cancelReady = null

onMounted(() => {
  audio = new Audio(easterSound('vaas.m4a'))
  audio.volume = 0.7
  audio.play().catch(() => {})       // автоплей мог быть закрыт — субтитры всё равно идут
  const start = () => {
    const total = (audio.duration && isFinite(audio.duration)) ? audio.duration : 30
    const w = LINES.map((s) => s.length)
    const sum = w.reduce((a, b) => a + b, 0)
    let acc = 0
    LINES.forEach((text, i) => {
      timers.push(setTimeout(() => { line.value = text }, acc * 1000))
      acc += total * w[i] / sum
    })
    timers.push(setTimeout(() => emit('close'), acc * 1000 + 800))
  }
  //⚠️ Через whenAudioReady, а НЕ голым 'loadedmetadata': не доехал звук —
  //событие не придёт никогда, и сцена не закроется вовсе. См. utils/audioReady.js.
  cancelReady = whenAudioReady(audio, start)
})
onBeforeUnmount(() => {
  timers.forEach(clearTimeout)
  if (cancelReady) cancelReady()
  if (audio) audio.pause()
})
</script>

<template>
  <div class="pointer-events-none fixed inset-x-0 bottom-0 z-[92] grid min-h-[72px] place-items-center
              px-5 py-4 text-center font-mono text-sm leading-relaxed"
       style="background:rgba(0,0,0,.86);color:#f2e9d8">
    {{ line }}
  </div>
</template>
