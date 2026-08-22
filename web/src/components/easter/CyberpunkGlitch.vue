<script setup>
// Cyberpunk после успешного входа.
//
// ⚠️ Гитара стартует ПЕРВОЙ и на две секунды раньше фразы, поднимается с нуля и
// затухает по РЕАЛЬНОЙ длительности файла. Раньше стоял фиксированный срок — звук
// обрывался на полуслове; замена файла ломала бы расчёт снова.
import { onMounted, onBeforeUnmount, ref } from 'vue'
import { useEasterStore } from '@/stores/easterEggs'
const emit = defineEmits(['close'])
const easter = useEasterStore()

const glitch = ref(true), text = ref(''), fade = ref(false)
let sounds = [], timers = []

function fadeIn(a, target, ms) {
  const t0 = performance.now()
  const id = setInterval(() => {
    const k = Math.min(1, (performance.now() - t0) / ms)
    a.volume = target * k
    if (k >= 1) clearInterval(id)
  }, 50)
  timers.push(() => clearInterval(id))
}

onMounted(async () => {
  const wait = (ms) => new Promise((r) => setTimeout(r, ms))
  const guitar = new Audio('/easter/snd/guitar.mp3')
  guitar.volume = 0
  guitar.play().catch(() => {})
  sounds.push(guitar)
  fadeIn(guitar, 0.2, 3000)
  const tail = () => {
    const d = (guitar.duration && isFinite(guitar.duration)) ? guitar.duration : 12
    setTimeout(() => {
      const v0 = guitar.volume, t0 = performance.now()
      const id = setInterval(() => {
        const k = Math.min(1, (performance.now() - t0) / 3500)
        guitar.volume = Math.max(0, v0 * (1 - k))
        if (k >= 1) { clearInterval(id); guitar.pause() }
      }, 50)
    }, Math.max(0, (d - 3.5) * 1000))
  }
  guitar.readyState > 0 ? tail() : guitar.addEventListener('loadedmetadata', tail, { once: true })

  await wait(1000); glitch.value = false
  await wait(1000)
  const johnny = new Audio('/easter/snd/johnny.mp3')
  johnny.volume = 0.7
  johnny.play().catch(() => {})
  sounds.push(johnny)

  const phrase = 'Проснись, самурай. Время учиться.'
  for (let i = 1; i <= phrase.length; i++) { text.value = phrase.slice(0, i); await wait(48) }
  await wait(1600); fade.value = true
  await wait(700)
  await easter.claim('cyberpunk_login')
  emit('close')
})
onBeforeUnmount(() => { sounds.forEach((a) => a.pause()); timers.forEach((f) => f()) })
</script>

<template>
  <div class="pointer-events-none fixed inset-0 z-[93] overflow-hidden">
    <div v-if="glitch" class="absolute inset-0">
      <div v-for="i in 7" :key="i" class="absolute inset-x-0 gl"
           :style="{ top: (i - 1) * 14 + '%', height: (4 + i) + '%', animationDuration: (0.2 + i * 0.05) + 's' }"></div>
    </div>
    <p class="absolute inset-x-0 top-[46%] text-center font-mono text-xl font-bold transition-opacity duration-500"
       style="color:#fdf200;text-shadow:2px 0 #ff003c,-2px 0 #00e5ff"
       :style="{ opacity: fade ? 0 : 1 }">{{ text }}</p>
  </div>
</template>

<style scoped>
.gl { background: linear-gradient(90deg, #0ff5, #f0f5); mix-blend-mode: screen;
      animation: cps steps(3) infinite; }
@keyframes cps { 0% { opacity:.8 } 50% { opacity:.15 } 100% { opacity:.6 } }
@media (prefers-reduced-motion: reduce) { .gl { animation: none; opacity: .3 } }
</style>
