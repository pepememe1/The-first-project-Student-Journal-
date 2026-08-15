<script setup>
// BoardCanvas — общая доска (PLAN-ACTIVITIES §8.1).
//
// 🔑 Храним ШТРИХИ, а не картинку. Файлового хранилища в проекте нет вообще (картинки
// живут data:-строками в JSON), PNG доски — это сотни килобайт base64 в теле сообщения, а
// продолжить рисование поверх растра нельзя: рисуют заново.
//
// ⚠️ Штрихи уходят на сервер ПАЧКАМИ раз в ~150 мс, а не на каждое движение пальца: иначе
// один рисующий даёт сотни запросов в секунду.
import { ref, computed, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import { Eraser, Camera, PenLine, Shuffle } from '@lucide/vue'
import AppButton from '@/components/ui/AppButton.vue'
import { useLocaleStore } from '@/stores/locale'
import { useActivityStore } from '@/stores/activity'
import { useProfileStore } from '@/stores/profile'
import { activitiesApi } from '@/api/endpoints'

const locale = useLocaleStore()
const act = useActivityStore()
//Свой id клиент знает ТОЛЬКО отсюда: в «визитке» auth лежат логин, роль и ФИО, но не id
//(см. §третьего захода 3.7 — чтение `auth.user.id` даёт undefined и запрещено сторожем).
const profile = useProfileStore()

const canvas = ref(null)
const wrap = ref(null)
const strokes = ref([])          // [{c: цвет, w: толщина, p: [x0,y0,x1,y1,...]}] в долях 0..1
const color = ref('#e34b4b')
const width = ref(3)
const drawing = ref(false)
const penName = computed(() => act.state.pen_user_name || '')

const FLUSH_MS = 150
let pending = []
let flushTimer = null
let cur = null

//Рисует ведущий либо тот, кому он выдал перо. Сервер проверяет это же условие сам
//(`_may_draw`) — здесь только чтобы не давать человеку водить пальцем впустую.
const mayDraw = computed(() => act.isRunning
  && (act.isHost || (!!profile.userId && act.state.pen_user_id === profile.userId)))

function resize() {
  const el = canvas.value
  if (!el || !wrap.value) return
  el.width = wrap.value.clientWidth
  el.height = wrap.value.clientHeight
  redraw()
}

function sheetBackground(ctx, w, h) {
  ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue('--gb-card') || '#fff'
  ctx.fillRect(0, 0, w, h)
  const sheet = act.state.sheet || 'blank'
  if (sheet === 'blank') return
  ctx.strokeStyle = 'rgba(128,128,128,0.25)'
  ctx.lineWidth = 1
  const step = 28
  ctx.beginPath()
  for (let y = step; y < h; y += step) { ctx.moveTo(0, y); ctx.lineTo(w, y) }
  if (sheet === 'grid') for (let x = step; x < w; x += step) { ctx.moveTo(x, 0); ctx.lineTo(x, h) }
  ctx.stroke()
}

function redraw() {
  const el = canvas.value
  if (!el) return
  const ctx = el.getContext('2d')
  const { width: w, height: h } = el
  sheetBackground(ctx, w, h)
  ctx.lineCap = 'round'
  ctx.lineJoin = 'round'
  for (const s of strokes.value) {
    if (!s?.p || s.p.length < 4) continue
    ctx.strokeStyle = s.c || '#000'
    ctx.lineWidth = s.w || 3
    ctx.beginPath()
    ctx.moveTo(s.p[0] * w, s.p[1] * h)
    for (let i = 2; i < s.p.length; i += 2) ctx.lineTo(s.p[i] * w, s.p[i + 1] * h)
    ctx.stroke()
  }
}

function pos(e) {
  const r = canvas.value.getBoundingClientRect()
  const t = e.touches?.[0] || e
  return [(t.clientX - r.left) / r.width, (t.clientY - r.top) / r.height]
}

function down(e) {
  if (!mayDraw.value) return
  drawing.value = true
  cur = { c: color.value, w: width.value, p: pos(e) }
}
function move(e) {
  if (!drawing.value || !cur) return
  const [x, y] = pos(e)
  cur.p.push(x, y)
  strokes.value = [...strokes.value.filter((s) => s !== cur), cur]
  redraw()
}
function up() {
  if (!drawing.value || !cur) return
  drawing.value = false
  if (cur.p.length >= 4) { pending.push(cur); scheduleFlush() }
  cur = null
}

function scheduleFlush() {
  if (flushTimer) return
  flushTimer = setTimeout(async () => {
    flushTimer = null
    const batch = pending
    pending = []
    if (!batch.length) return
    try { await activitiesApi.strokes(act.activity.id, batch) } catch { pending.unshift(...batch) }
  }, FLUSH_MS)
}

async function clearAll() {
  strokes.value = []
  redraw()
  try { await activitiesApi.strokes(act.activity.id, [], true) } catch { /* noop */ }
}

async function snapshot() {
  try { await activitiesApi.snapshot(act.activity.id) } catch { /* noop */ }
}

async function givePen(random) {
  try {
    const { data } = await activitiesApi.pen(act.activity.id, random ? { random: true } : { user_id: '' })
    act.state = { ...act.state, pen_user_id: data.pen_user_id, pen_user_name: data.pen_user_name }
  } catch { /* noop */ }
}

// Кадр состояния приносит ТОЛЬКО добавленные штрихи (не всю доску): полная доска в
// каждом кадре — это мегабайты по сокету на длинной паре.
watch(() => act.state.strokes_added, (added) => {
  if (act.state.cleared) { strokes.value = []; redraw(); return }
  if (Array.isArray(added) && added.length) {
    strokes.value = [...strokes.value, ...added]
    redraw()
  }
})

onMounted(async () => {
  strokes.value = [...(act.state.strokes || [])]
  await nextTick()
  resize()
  window.addEventListener('resize', resize)
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  if (flushTimer) clearTimeout(flushTimer)
})
</script>

<template>
  <div class="flex min-h-0 flex-1 flex-col gap-2">
    <div v-if="act.isHost && act.isRunning" class="flex flex-wrap items-center gap-2">
      <input v-model="color" type="color" class="size-8 shrink-0 rounded border border-border2" />
      <input v-model.number="width" type="range" min="1" max="12" class="w-24 shrink-0" />
      <AppButton variant="ghost" size="sm" @click="clearAll">
        <Eraser class="size-4" /> {{ locale.t('board.clear', 'Стереть') }}
      </AppButton>
      <AppButton variant="ghost" size="sm" @click="snapshot">
        <Camera class="size-4" /> {{ locale.t('board.snapshot', 'Снимок в чат') }}
      </AppButton>
      <AppButton variant="ghost" size="sm" @click="givePen(true)">
        <Shuffle class="size-4" /> {{ locale.t('board.randomPen', 'Дать перо жребием') }}
      </AppButton>
      <AppButton v-if="penName" variant="ghost" size="sm" @click="givePen(false)">
        <PenLine class="size-4" /> {{ locale.t('board.takePen', 'Забрать перо') }}
      </AppButton>
    </div>
    <p v-if="penName" class="text-xs text-accent">
      {{ locale.t('board.penAt', { name: penName }) }}
    </p>

    <div ref="wrap" class="min-h-0 flex-1 overflow-hidden rounded-xl border border-border2">
      <canvas ref="canvas" class="size-full touch-none"
              :class="mayDraw ? 'cursor-crosshair' : 'cursor-default'"
              @pointerdown="down" @pointermove="move" @pointerup="up" @pointerleave="up" />
    </div>
  </div>
</template>
