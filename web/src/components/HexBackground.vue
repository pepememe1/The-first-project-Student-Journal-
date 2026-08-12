<script setup>
// HexBackground — фон экрана входа. ТОЧНЫЙ ПОРТ ui_components.AnimatedBackground
// (animated): та же сцена, что в десктопе — вертикальный градиент bg→bg2, два мягких
// световых пятна (пульсируют), 5 КРУПНЫХ дрейфующих шестиугольников-«сот» (отсыл к
// лого GB) и ~30 мерцающих частиц акцентного цвета. Раньше был статичный тайл-паттерн
// плотных сот — он не совпадал с десктопом. Лёгкий: ~30 fps, ~37 объектов, стоп при
// уходе со страницы и при prefers-reduced-motion.
import { ref, onMounted, onBeforeUnmount } from 'vue'

const canvas = ref(null)
let ctx, raf = 0, t = 0, W = 0, H = 0, dpr = 1, last = 0
let particles = [], hexes = [], blobs = []
let accent = '20,124,139'          // RGB акцента (--gb-accent), fallback teal
let bg = '#0e151d', bg2 = '#0a0f16'
const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

const rand = (a, b) => a + Math.random() * (b - a)

function hexToRgb(h) {
  const m = (h || '').replace('#', '').trim()
  if (m.length < 6) return null
  const n = parseInt(m.slice(0, 6), 16)
  return `${(n >> 16) & 255},${(n >> 8) & 255},${n & 255}`
}
function readColors() {
  const s = getComputedStyle(document.documentElement)
  accent = hexToRgb(s.getPropertyValue('--gb-accent')) || accent
  bg = (s.getPropertyValue('--gb-bg') || bg).trim()
  bg2 = (s.getPropertyValue('--gb-bg2') || bg2).trim()
}

function seed() {
  particles = []
  for (let i = 0; i < 30; i++) particles.push({
    x: rand(0, W), y: rand(0, H), r: rand(2, 5),
    vx: rand(-0.25, 0.25), vy: rand(-0.55, -0.15),
    a: rand(0.3, 0.7), ph: rand(0, Math.PI * 2),
  })
  // ⚠️ Размер фигур задан в ПИКСЕЛЯХ и подбирался на мониторе. На телефоне ширина втрое
  // меньше, а гексагоны те же — шестиугольник радиусом 210 px при экране 360 px закрывает
  // его целиком, и фон из декорации превращается в пятно поперёк страницы (живой отзыв со
  // скриншота). Привязываем масштаб к ширине окна: на узком экране фигуры мельче, на
  // широком — ровно как были, ни пикселя разницы.
  const k = Math.min(1, Math.max(0.42, W / 900))
  hexes = []
  for (let i = 0; i < 6; i++) hexes.push({
    x: rand(0, W), y: rand(0, H), R: rand(85, 210) * k,
    vx: rand(-0.16, 0.16), vy: rand(-0.16, 0.16),
    ang: rand(0, Math.PI), spin: rand(-0.0035, 0.0035),
  })
  // Световые пятна считаются от БОЛЬШЕЙ стороны, а у телефона это высота — на вытянутом
  // экране пятно выходило шире самого экрана. Берём меньшую: она и определяет, что
  // человек реально видит поперёк.
  const base = Math.min(W, H)
  blobs = [
    { x: W * 0.3, y: H * 0.35, R: base * 0.5 },
    { x: W * 0.72, y: H * 0.62, R: base * 0.4 },
  ]
}

function resize() {
  const el = canvas.value
  if (!el) return
  dpr = Math.min(window.devicePixelRatio || 1, 2)
  W = el.clientWidth || window.innerWidth
  H = el.clientHeight || window.innerHeight
  el.width = W * dpr; el.height = H * dpr
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  seed()
}

function hexPath(cx, cy, r, ang) {
  ctx.beginPath()
  for (let a = 0; a < 360; a += 60) {
    const rad = ang + (a * Math.PI) / 180
    const x = cx + r * Math.cos(rad), y = cy + r * Math.sin(rad)
    a === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)
  }
  ctx.closePath()
}

function draw() {
  const g = ctx.createLinearGradient(0, 0, 0, H)
  g.addColorStop(0, bg); g.addColorStop(1, bg2)
  ctx.fillStyle = g; ctx.fillRect(0, 0, W, H)

  // 1) световые пятна (глубина за карточкой)
  blobs.forEach((b, i) => {
    const pulse = 0.5 + 0.5 * Math.sin(t * 0.01 + i)
    const rg = ctx.createRadialGradient(b.x, b.y, 0, b.x, b.y, b.R)
    rg.addColorStop(0, `rgba(${accent},${(26 + 14 * pulse) / 255})`)
    rg.addColorStop(1, `rgba(${accent},0)`)
    ctx.fillStyle = rg
    ctx.beginPath(); ctx.arc(b.x, b.y, b.R, 0, Math.PI * 2); ctx.fill()
  })

  // 2) шестиугольники-«соты» (контур + лёгкая заливка)
  hexes.forEach((hx) => {
    hexPath(hx.x, hx.y, hx.R, hx.ang)
    ctx.fillStyle = `rgba(${accent},0.08)`; ctx.fill()
    ctx.strokeStyle = `rgba(${accent},0.27)`; ctx.lineWidth = 2; ctx.stroke()
  })

  // 2.5) «живая» сеть-созвездие: тонкие линии между близкими частицами — оживляет фон.
  ctx.lineWidth = 1
  for (let i = 0; i < particles.length; i++) {
    for (let j = i + 1; j < particles.length; j++) {
      const a = particles[i], b = particles[j]
      const d = Math.hypot(a.x - b.x, a.y - b.y)
      if (d < 155) {
        ctx.strokeStyle = `rgba(${accent},${0.15 * (1 - d / 155)})`
        ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke()
      }
    }
  }

  // 3) частицы (мерцают по фазе)
  particles.forEach((pt) => {
    const tw = 0.65 + 0.35 * Math.sin(t * 0.05 + pt.ph)
    ctx.fillStyle = `rgba(${accent},${Math.max(0, Math.min(1, pt.a * tw))})`
    ctx.beginPath(); ctx.arc(pt.x, pt.y, pt.r, 0, Math.PI * 2); ctx.fill()
  })
}

function advance() {
  particles.forEach((pt) => {
    pt.x += pt.vx; pt.y += pt.vy
    if (pt.y < -5) { pt.y = H + 5; pt.x = rand(0, W) }
    if (pt.x < -5) pt.x = W + 5
    else if (pt.x > W + 5) pt.x = -5
  })
  hexes.forEach((hx) => {
    hx.x += hx.vx; hx.y += hx.vy; hx.ang += hx.spin
    if (hx.x < -hx.R) hx.x = W + hx.R
    else if (hx.x > W + hx.R) hx.x = -hx.R
    if (hx.y < -hx.R) hx.y = H + hx.R
    else if (hx.y > H + hx.R) hx.y = -hx.R
  })
}

function loop(ts) {
  raf = requestAnimationFrame(loop)
  if (ts - last < 33) return   // ~30 fps, бережём CPU
  last = ts
  t++; advance(); draw()
}

onMounted(() => {
  ctx = canvas.value.getContext('2d')
  readColors(); resize(); draw()
  if (!reduce) raf = requestAnimationFrame(loop)
  window.addEventListener('resize', resize)
})
onBeforeUnmount(() => {
  cancelAnimationFrame(raf)
  window.removeEventListener('resize', resize)
})
</script>

<template>
  <canvas ref="canvas" class="absolute inset-0 h-full w-full" aria-hidden="true" />
</template>
