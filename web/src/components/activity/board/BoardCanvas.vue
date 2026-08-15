<script setup>
// BoardCanvas — общая доска (PLAN-ACTIVITIES §8.1).
//
// 🔑 Храним ОБЪЕКТЫ, а не картинку. Файлового хранилища в проекте нет вообще (картинки
// живут data:-строками в JSON), PNG доски — это сотни килобайт base64 в теле сообщения, а
// продолжить рисование поверх растра нельзя: рисуют заново.
//
// Формат объекта (доли 0..1, поэтому доска одинакова на любом экране):
//   {t:'p'|'r'|'e'|'a'|'x', c: цвет, w: толщина, p: [координаты], s: текст, g: id группы}
//   'p' — линия от руки, 'r' — прямоугольник, 'e' — овал, 'a' — стрелка, 'x' — надпись.
// ⚠️ ОТСУТСТВИЕ `t` = линия от руки. Так выглядят все доски, нарисованные до появления
// фигур: сохранённые артефакты обязаны открываться и после этой правки.
//
// ⚠️ Объекты добавляются и удаляются ЦЕЛИКОМ — не двигаются и не редактируются после
// создания. Это осознанная граница: перемещение объектов означает совместное
// редактирование одной сущности, а от слияния правок в этом проекте отказались.
import { ref, computed, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import { Pencil, Square, Circle, MoveUpRight, Type, Eraser, Trash2, Camera,
         Hand, Shuffle, PenLine, X } from '@lucide/vue'
import { useLocaleStore } from '@/stores/locale'
import { useConfirm } from '@/composables/useConfirm'
import { useActivityStore } from '@/stores/activity'
import { useMessengerStore } from '@/stores/messenger'
import { useProfileStore } from '@/stores/profile'
import { activitiesApi } from '@/api/endpoints'

const locale = useLocaleStore()
const { prompt } = useConfirm()
const act = useActivityStore()
const m = useMessengerStore()
//Свой id клиент знает ТОЛЬКО отсюда: в «визитке» auth лежат логин, роль и ФИО, но не id
//(см. §третьего захода 3.7 — чтение `auth.user.id` даёт undefined и запрещено сторожем).
const profile = useProfileStore()

const canvas = ref(null)
const wrap = ref(null)
const objects = ref([])
const color = ref('#e34b4b')
const width = ref(3)
const tool = ref('p')
const drawing = ref(false)
const callOpen = ref(false)
const penName = computed(() => act.state.pen_user_name || '')

// Цифры на кнопках — не украшение: это горячие клавиши, как в привычных редакторах.
// Подпись словом на круглой кнопке не помещается, а безымянная иконка требует наведения.
const TOOLS = [
  { id: 'p', key: '1', icon: Pencil, label: 'board.tool.pen' },
  { id: 'r', key: '2', icon: Square, label: 'board.tool.rect' },
  { id: 'e', key: '3', icon: Circle, label: 'board.tool.ellipse' },
  { id: 'a', key: '4', icon: MoveUpRight, label: 'board.tool.arrow' },
  { id: 'x', key: '5', icon: Type, label: 'board.tool.text' },
  { id: 'd', key: '6', icon: Eraser, label: 'board.tool.erase' },
]

const FLUSH_MS = 150
let pending = []
let flushTimer = null
let cur = null            // объект, который рисуется прямо сейчас
let liveTail = null       // «хвост» линии от руки, ещё не отправленный
let groupSeq = 0

//Рисует ведущий либо тот, кому он выдал перо. Сервер проверяет это же условие сам
//(`_may_draw`) — здесь только чтобы не давать человеку водить пальцем впустую.
const mayDraw = computed(() => act.isRunning
  && (act.isHost || (!!profile.userId && act.state.pen_user_id === profile.userId)))

const participants = computed(() =>
  (m.activeInfo?.participants || []).filter((p) => p.user_id !== act.activity?.host_id))

// ── Отрисовка ──────────────────────────────────────────────────────────────────────
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

function drawOne(ctx, o, w, h) {
  const p = o?.p
  if (!p || !p.length) return
  ctx.strokeStyle = o.c || '#000'
  ctx.fillStyle = o.c || '#000'
  ctx.lineWidth = o.w || 3
  const t = o.t || 'p'
  if (t === 'x') {
    const size = Math.max(12, (o.w || 3) * 6)
    ctx.font = `600 ${size}px system-ui, sans-serif`
    ctx.textBaseline = 'top'
    ctx.fillText(o.s || '', p[0] * w, p[1] * h)
    return
  }
  const [x0, y0, x1, y1] = [p[0] * w, p[1] * h, p[2] * w, p[3] * h]
  ctx.beginPath()
  if (t === 'r') ctx.rect(x0, y0, x1 - x0, y1 - y0)
  else if (t === 'e') ctx.ellipse((x0 + x1) / 2, (y0 + y1) / 2,
                                  Math.abs(x1 - x0) / 2, Math.abs(y1 - y0) / 2, 0, 0, Math.PI * 2)
  else if (t === 'a') {
    ctx.moveTo(x0, y0); ctx.lineTo(x1, y1)
    const ang = Math.atan2(y1 - y0, x1 - x0)
    const head = Math.max(8, (o.w || 3) * 3)
    ctx.moveTo(x1, y1)
    ctx.lineTo(x1 - head * Math.cos(ang - Math.PI / 6), y1 - head * Math.sin(ang - Math.PI / 6))
    ctx.moveTo(x1, y1)
    ctx.lineTo(x1 - head * Math.cos(ang + Math.PI / 6), y1 - head * Math.sin(ang + Math.PI / 6))
  } else {
    if (p.length < 4) return
    ctx.moveTo(p[0] * w, p[1] * h)
    for (let i = 2; i < p.length; i += 2) ctx.lineTo(p[i] * w, p[i + 1] * h)
  }
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
  for (const o of objects.value) drawOne(ctx, o, w, h)
  if (cur) drawOne(ctx, cur, w, h)
}

// ── Ввод ───────────────────────────────────────────────────────────────────────────
function pos(e) {
  const r = canvas.value.getBoundingClientRect()
  const t = e.touches?.[0] || e
  return [(t.clientX - r.left) / r.width, (t.clientY - r.top) / r.height]
}

function boxOf(o) {
  const p = o.p || []
  const t = o.t || 'p'
  if (t === 'x') return [p[0], p[1], p[0] + 0.25, p[1] + 0.06]
  if (t === 'p') {
    const xs = p.filter((_, i) => i % 2 === 0)
    const ys = p.filter((_, i) => i % 2 === 1)
    return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)]
  }
  return [Math.min(p[0], p[2]), Math.min(p[1], p[3]), Math.max(p[0], p[2]), Math.max(p[1], p[3])]
}

function hit(o, x, y) {
  const [a, b, c, d] = boxOf(o)
  const pad = 0.015
  return x >= a - pad && x <= c + pad && y >= b - pad && y <= d + pad
}

async function eraseAt(x, y) {
  // Ищем СВЕРХУ вниз: стираем то, что человек видит последним нарисованным.
  const target = [...objects.value].reverse().find((o) => hit(o, x, y))
  if (!target) return
  //Линия от руки уезжает на сервер кусками (ради реального времени), поэтому у всех
  //кусков один `g` — стираем всю линию целиком, а не тот огрызок, куда попал курсор.
  const gid = target.g
  objects.value = objects.value.filter((o) => (gid ? o.g !== gid : o !== target))
  redraw()
  await replaceAll()
}

async function down(e) {
  if (!mayDraw.value) return
  const [x, y] = pos(e)
  if (tool.value === 'd') { await eraseAt(x, y); return }
  if (tool.value === 'x') {
    const text = await prompt({ title: locale.t('board.tool.text', 'Надпись'),
                                message: locale.t('board.textPrompt', 'Что написать?') })
    if (!text) return
    const o = { t: 'x', c: color.value, w: width.value, p: [x, y], s: String(text).slice(0, 120) }
    objects.value = [...objects.value, o]
    pending.push(o); scheduleFlush(); redraw()
    return
  }
  drawing.value = true
  groupSeq += 1
  const g = `g${Date.now()}_${groupSeq}`
  cur = tool.value === 'p'
    ? { t: 'p', c: color.value, w: width.value, p: [x, y], g }
    : { t: tool.value, c: color.value, w: width.value, p: [x, y, x, y] }
  liveTail = tool.value === 'p' ? { ...cur, p: [x, y] } : null
}

function move(e) {
  if (!drawing.value || !cur) return
  const [x, y] = pos(e)
  if ((cur.t || 'p') === 'p') {
    cur.p.push(x, y)
    liveTail.p.push(x, y)
    //🔴 РЕАЛЬНОЕ ВРЕМЯ. Раньше штрих уходил только когда рисующий ОТРЫВАЛ перо, и на
    //длинной линии остальные секундами смотрели в пустую доску. Теперь хвост уезжает
    //каждые FLUSH_MS отдельным куском, а следующий начинается с последней точки —
    //визуально шов незаметен (круглые концы), зато линия появляется у всех сразу.
    if (liveTail.p.length >= 8) {
      pending.push(liveTail)
      liveTail = { ...cur, p: [x, y] }
      scheduleFlush()
    }
  } else {
    cur.p[2] = x; cur.p[3] = y
  }
  redraw()
}

function up() {
  if (!drawing.value || !cur) return
  drawing.value = false
  const o = cur
  cur = null
  if ((o.t || 'p') === 'p') {
    if (liveTail && liveTail.p.length >= 4) pending.push(liveTail)
    liveTail = null
    //Локально держим линию ОДНИМ объектом: куски нужны только для передачи.
    if (o.p.length >= 4) objects.value = [...objects.value, o]
  } else {
    objects.value = [...objects.value, o]
    pending.push(o)
  }
  redraw()
  scheduleFlush()
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

/** Полная замена доски (стирание объекта). Сервер умеет только «добавить» и «очистить»,
 *  поэтому шлём очистку вместе с остатком. Пачка ограничена сервером (500), длинную
 *  доску досылаем следом — иначе часть объектов молча пропала бы. */
async function replaceAll() {
  const all = objects.value
  try {
    await activitiesApi.strokes(act.activity.id, all.slice(0, 400), true)
    for (let i = 400; i < all.length; i += 400) {
      await activitiesApi.strokes(act.activity.id, all.slice(i, i + 400))
    }
  } catch { /* следующее действие дошлёт */ }
}

async function clearAll() {
  objects.value = []
  redraw()
  try { await activitiesApi.strokes(act.activity.id, [], true) } catch { /* noop */ }
}

async function snapshot() {
  try { await activitiesApi.snapshot(act.activity.id) } catch { /* noop */ }
}

async function givePen(payload) {
  try {
    const { data } = await activitiesApi.pen(act.activity.id, payload)
    act.state = { ...act.state, pen_user_id: data.pen_user_id, pen_user_name: data.pen_user_name }
  } catch { /* noop */ }
  callOpen.value = false
}

function onKey(e) {
  if (!mayDraw.value || e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return
  const t = TOOLS.find((x) => x.key === e.key)
  if (t) tool.value = t.id
}

// Кадр состояния приносит ТОЛЬКО добавленное (не всю доску): полная доска в каждом
// кадре — это мегабайты по сокету на длинной паре.
watch(() => act.state.strokes_added, (added) => {
  if (act.state.cleared) { objects.value = [] }
  if (Array.isArray(added) && added.length) objects.value = [...objects.value, ...added]
  redraw()
})

onMounted(async () => {
  objects.value = [...(act.state.strokes || [])]
  await nextTick()
  resize()
  window.addEventListener('resize', resize)
  window.addEventListener('keydown', onKey)
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  window.removeEventListener('keydown', onKey)
  if (flushTimer) clearTimeout(flushTimer)
})
</script>

<template>
  <div class="relative flex min-h-0 flex-1 flex-col">
    <p v-if="penName" class="shrink-0 pb-1 text-xs text-accent">
      {{ locale.t('board.penAt', { name: penName }) }}
    </p>

    <div ref="wrap" class="min-h-0 flex-1 overflow-hidden rounded-xl border border-border2">
      <canvas ref="canvas" class="size-full touch-none"
              :class="mayDraw ? 'cursor-crosshair' : 'cursor-default'"
              @pointerdown="down" @pointermove="move" @pointerup="up" @pointerleave="up" />
    </div>

    <!-- Панель ВНИЗУ и поверх холста: сверху она отъедала высоту доски, а рука при
         рисовании закрывает низ экрана меньше, чем верх. Прокручивается по горизонтали —
         на телефоне инструменты в строку не помещаются. -->
    <div v-if="mayDraw"
         class="pointer-events-none absolute inset-x-0 bottom-3 z-10 flex justify-center px-2">
      <div class="pointer-events-auto flex max-w-full items-center gap-1 overflow-x-auto rounded-full border border-border2 bg-card/95 px-2 py-1.5 shadow-lg backdrop-blur">
        <button v-for="t in TOOLS" :key="t.id" type="button" @click="tool = t.id"
                :title="`${locale.t(t.label, t.id)} (${t.key})`"
                class="relative grid size-9 shrink-0 place-items-center rounded-full transition-colors"
                :class="tool === t.id ? 'bg-accent text-white' : 'text-text2 hover:bg-bg2'">
          <component :is="t.icon" class="size-[18px]" />
          <span class="absolute bottom-0 right-0.5 text-[9px] font-bold leading-none opacity-60">{{ t.key }}</span>
        </button>

        <span class="mx-1 h-6 w-px shrink-0 bg-border2" />

        <input v-model="color" type="color" :title="locale.t('board.color', 'Цвет')"
               class="size-8 shrink-0 cursor-pointer rounded-full border border-border2 bg-transparent p-0.5" />
        <input v-model.number="width" type="range" min="1" max="12"
               :title="locale.t('board.width', 'Толщина')" class="w-20 shrink-0" />

        <span class="mx-1 h-6 w-px shrink-0 bg-border2" />

        <button v-if="act.isHost" type="button" @click="clearAll"
                :title="locale.t('board.clear', 'Стереть всё')"
                class="grid size-9 shrink-0 place-items-center rounded-full text-text2 hover:bg-bg2 hover:text-red">
          <Trash2 class="size-[18px]" />
        </button>
        <button v-if="act.isHost" type="button" @click="snapshot"
                :title="locale.t('board.snapshot', 'Снимок в чат')"
                class="grid size-9 shrink-0 place-items-center rounded-full text-text2 hover:bg-bg2 hover:text-accent">
          <Camera class="size-[18px]" />
        </button>
        <!-- Передача пера: сначала ВЫБОР ЧЕЛОВЕКА, жребий — рядом. Раньше была только
             кнопка жребия, то есть вызвать конкретного студента было нечем. -->
        <button v-if="act.isHost" type="button" @click="callOpen = !callOpen"
                :title="locale.t('board.callToBoard', 'Вызвать к доске')"
                class="grid size-9 shrink-0 place-items-center rounded-full transition-colors"
                :class="callOpen ? 'bg-accent text-white' : 'text-text2 hover:bg-bg2 hover:text-accent'">
          <Hand class="size-[18px]" />
        </button>
      </div>
    </div>

    <!-- Список участников для вызова к доске -->
    <div v-if="callOpen" class="absolute inset-x-0 bottom-16 z-20 flex justify-center px-2">
      <div class="max-h-64 w-64 max-w-full overflow-y-auto rounded-xl border border-border2 bg-card p-2 shadow-xl">
        <div class="flex items-center justify-between px-1 pb-1">
          <span class="text-xs font-semibold text-text">{{ locale.t('board.callToBoard', 'Вызвать к доске') }}</span>
          <button type="button" @click="callOpen = false" class="text-text3 hover:text-text"><X class="size-4" /></button>
        </div>
        <button type="button" @click="givePen({ random: true })"
                class="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm text-text2 hover:bg-bg2">
          <Shuffle class="size-4 shrink-0" /> {{ locale.t('board.randomPen', 'Жребием') }}
        </button>
        <button v-if="penName" type="button" @click="givePen({ user_id: '' })"
                class="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm text-text2 hover:bg-bg2">
          <PenLine class="size-4 shrink-0" /> {{ locale.t('board.takePen', 'Забрать перо') }}
        </button>
        <div class="my-1 h-px bg-border2" />
        <button v-for="p in participants" :key="p.user_id" type="button"
                @click="givePen({ user_id: p.user_id })"
                class="block w-full truncate rounded-lg px-2 py-1.5 text-left text-sm text-text2 hover:bg-bg2">
          {{ p.full_name || p.login }}
        </button>
        <p v-if="!participants.length" class="px-2 py-1.5 text-xs text-text3">
          {{ locale.t('board.noParticipants', 'В беседе больше никого нет') }}
        </p>
      </div>
    </div>
  </div>
</template>
