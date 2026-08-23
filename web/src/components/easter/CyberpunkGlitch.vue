<script setup>
// Cyberpunk после успешного входа.
//
// ⚠️ Глитч рисуется на CANVAS, а не десятками анимированных div-ов. Нужный вид — это
// сотни тонких горизонтальных полос, которые дрожат и накладываются друг на друга;
// в разметке это две-три сотни элементов с собственными анимациями, то есть заметная
// нагрузка ровно в тот момент, когда человек только вошёл и страница ещё грузится.
// На канвасе то же самое стоит один кадр отрисовки.
//
// ⚠️ Гитара стартует ПЕРВОЙ и на две секунды раньше фразы, поднимается с нуля и
// затухает по РЕАЛЬНОЙ длительности файла: раньше стоял фиксированный срок, и звук
// обрывался на полуслове — а замена файла ломала бы расчёт снова.
import { onMounted, onBeforeUnmount, ref } from 'vue'
import { useEasterStore } from '@/stores/easterEggs'
import { whenAudioReady } from '@/utils/audioReady'
const emit = defineEmits(['close'])
const easter = useEasterStore()

const canvas = ref(null)
const glitch = ref(true)
const text = ref('')
const fade = ref(false)
let sounds = [], raf = 0, timers = []

// Палитра с образца: холодная бирюза и малиновый на почти чёрном, редкие белые вспышки.
const COLD = ['#00e5ff', '#22b8d6', '#1f7fa8', '#0a4d63', '#9be9f7']
const WARM = ['#ff2d55', '#e01e5a', '#8c1030', '#ff7b9c']

function draw(ctx, W, H) {
  ctx.fillStyle = '#05070c'
  ctx.fillRect(0, 0, W, H)
  const rows = Math.floor(H / 6)
  for (let i = 0; i < rows; i++) {
    const y = i * 6 + Math.random() * 3
    // На одной строке несколько отрезков — от этого и получается наложение.
    const pieces = 1 + Math.floor(Math.random() * 4)
    for (let k = 0; k < pieces; k++) {
      const w = 20 + Math.random() * (W * 0.42)
      const x = Math.random() * (W - w * 0.4) - w * 0.2   // часть уезжает за край
      const warm = Math.random() < 0.28                    // красных заметно меньше
      const pal = warm ? WARM : COLD
      ctx.globalAlpha = 0.25 + Math.random() * 0.75
      ctx.fillStyle = pal[Math.floor(Math.random() * pal.length)]
      ctx.fillRect(x, y, w, 1 + Math.random() * 3)
    }
  }
  // Несколько ярких «прострелов» поверх — на образце они и держат кадр.
  ctx.globalAlpha = 1
  for (let i = 0; i < 3; i++) {
    const y = Math.random() * H
    const w = W * (0.3 + Math.random() * 0.5)
    ctx.fillStyle = Math.random() < 0.5 ? '#ffffff' : '#ff3b6b'
    ctx.shadowColor = ctx.fillStyle
    ctx.shadowBlur = 12
    ctx.fillRect(Math.random() * (W - w), y, w, 1 + Math.random() * 2)
    ctx.shadowBlur = 0
  }
}

function startCanvas() {
  const c = canvas.value
  if (!c) return
  const dpr = Math.min(window.devicePixelRatio || 1, 2)
  const W = c.width = Math.floor(c.clientWidth * dpr)
  const H = c.height = Math.floor(c.clientHeight * dpr)
  const ctx = c.getContext('2d')
  // Уважаем «меньше движения»: рисуем ОДИН кадр и оставляем его статикой.
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) { draw(ctx, W, H); return }
  let last = 0
  const loop = (t) => {
    if (t - last > 55) { draw(ctx, W, H); last = t }   // ~18 кадров: дрожь, а не рябь
    raf = requestAnimationFrame(loop)
  }
  raf = requestAnimationFrame(loop)
}

onMounted(async () => {
  const wait = (ms) => new Promise((r) => setTimeout(r, ms))
  startCanvas()

  const guitar = new Audio('/easter/snd/guitar.mp3')
  guitar.volume = 0
  guitar.play().catch(() => {})
  sounds.push(guitar)
  const t0 = performance.now()
  const up = setInterval(() => {
    const k = Math.min(1, (performance.now() - t0) / 3000)
    guitar.volume = 0.2 * k
    if (k >= 1) clearInterval(up)
  }, 50)
  timers.push(() => clearInterval(up))
  const tail = () => {
    const d = (guitar.duration && isFinite(guitar.duration)) ? guitar.duration : 12
    const id = setTimeout(() => {
      const v0 = guitar.volume, s0 = performance.now()
      const down = setInterval(() => {
        const k = Math.min(1, (performance.now() - s0) / 3500)
        guitar.volume = Math.max(0, v0 * (1 - k))
        if (k >= 1) { clearInterval(down); guitar.pause() }
      }, 50)
      timers.push(() => clearInterval(down))
    }, Math.max(0, (d - 3.5) * 1000))
    timers.push(() => clearTimeout(id))
  }
  //⚠️ Через whenAudioReady, а не голым 'loadedmetadata': без метаданных затухание
  //не заведётся вовсе и гитара оборвётся на полуслове. См. utils/audioReady.js.
  timers.push(whenAudioReady(guitar, tail))

  await wait(1100)
  glitch.value = false
  cancelAnimationFrame(raf)
  await wait(900)

  const johnny = new Audio('/easter/snd/johnny.mp3')
  johnny.volume = 0.7
  johnny.play().catch(() => {})
  sounds.push(johnny)

  const phrase = 'Проснись, самурай. Время учиться.'
  for (let i = 1; i <= phrase.length; i++) { text.value = phrase.slice(0, i); await wait(48) }
  await wait(1600)
  fade.value = true
  await wait(700)
  await easter.claim('cyberpunk_login')
  emit('close')
})

onBeforeUnmount(() => {
  cancelAnimationFrame(raf)
  sounds.forEach((a) => a.pause())
  timers.forEach((f) => f())
})
</script>

<template>
  <div class="pointer-events-none fixed inset-0 z-[93] overflow-hidden">
    <canvas v-if="glitch" ref="canvas" class="absolute inset-0 h-full w-full"></canvas>
    <p v-if="!glitch" class="absolute inset-x-0 top-[46%] text-center font-mono text-xl font-bold
                             transition-opacity duration-500"
       style="color:#fdf200;text-shadow:2px 0 #ff003c,-2px 0 #00e5ff"
       :style="{ opacity: fade ? 0 : 1 }">{{ text }}</p>
  </div>
</template>
