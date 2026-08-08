<script setup>
// AvatarCropper — модалка загрузки/обрезки аватарки. Пользователь выбирает файл, двигает
// (перетаскивание) и масштабирует (ползунок/колесо) картинку в круглой рамке, чтобы
// «определить границы и нормально поставить», затем сохраняет. Экспорт — квадрат 256×256
// JPEG (data:URL) в prefs. Всё в браузере, без сети и сторонних библиотек.
import { ref, onBeforeUnmount } from 'vue'

defineProps({ current: { type: String, default: '' } })
const emit = defineEmits(['save', 'close'])

const VP = 256                       // размер вьюпорта/экспорта в пикселях (актуальный размер canvas)
const canvas = ref(null)
const img = ref(null)                // загруженный Image или null
const zoom = ref(1)                  // множитель поверх «cover»-масштаба (>=1)
const off = ref({ x: 0, y: 0 })      // смещение левого-верхнего угла картинки (в px вьюпорта)
let base = 1                         // «cover»-масштаб: минимальный, при котором картинка кроет вьюпорт
const drag = ref(null)               // {x,y} последней точки перетаскивания

function onFile(e) {
  const file = e.target.files?.[0]
  if (!file) return
  const reader = new FileReader()
  reader.onload = () => {
    const image = new Image()
    image.onload = () => { img.value = image; fit(); redraw() }
    image.src = reader.result
  }
  reader.readAsDataURL(file)
}

// Начальная посадка: масштаб «cover» + центрирование.
function fit() {
  const im = img.value
  if (!im) return
  base = Math.max(VP / im.width, VP / im.height)
  zoom.value = 1
  const w = im.width * base, h = im.height * base
  off.value = { x: (VP - w) / 2, y: (VP - h) / 2 }
}

// Не даём увести картинку так, чтобы в рамке появилась пустота.
function clamp() {
  const im = img.value
  if (!im) return
  const w = im.width * base * zoom.value, h = im.height * base * zoom.value
  off.value.x = Math.min(0, Math.max(VP - w, off.value.x))
  off.value.y = Math.min(0, Math.max(VP - h, off.value.y))
}

function redraw() {
  const c = canvas.value, im = img.value
  if (!c) return
  const ctx = c.getContext('2d')
  ctx.clearRect(0, 0, VP, VP)
  if (!im) return
  clamp()
  const s = base * zoom.value
  ctx.drawImage(im, off.value.x, off.value.y, im.width * s, im.height * s)
}

function onZoom() { redraw() }
function onWheel(e) {
  if (!img.value) return
  e.preventDefault()
  zoom.value = Math.min(5, Math.max(1, zoom.value + (e.deltaY < 0 ? 0.1 : -0.1)))
  redraw()
}
function onDown(e) {
  if (!img.value) return
  const p = e.touches ? e.touches[0] : e
  drag.value = { x: p.clientX, y: p.clientY }
}
function onMove(e) {
  if (!drag.value || !img.value) return
  const p = e.touches ? e.touches[0] : e
  const rect = canvas.value.getBoundingClientRect()
  const k = VP / rect.width          // экранные px → px вьюпорта (canvas может быть отмасштабирован CSS)
  off.value.x += (p.clientX - drag.value.x) * k
  off.value.y += (p.clientY - drag.value.y) * k
  drag.value = { x: p.clientX, y: p.clientY }
  redraw()
}
function onUp() { drag.value = null }
window.addEventListener('mousemove', onMove)
window.addEventListener('mouseup', onUp)
onBeforeUnmount(() => {
  window.removeEventListener('mousemove', onMove)
  window.removeEventListener('mouseup', onUp)
})

function save() {
  if (!img.value) { emit('close'); return }
  emit('save', canvas.value.toDataURL('image/jpeg', 0.85))
}
function remove() { emit('save', '') }        // удалить аватарку
</script>

<template>
  <div class="fixed inset-0 z-50 grid place-items-center p-4" style="background: var(--gb-overlay)"
       @click.self="emit('close')">
    <div class="w-full max-w-sm rounded-xl border border-border2 bg-card p-5 shadow-card">
      <h3 class="mb-4 font-title text-lg font-bold text-text">Аватарка</h3>

      <!-- Вьюпорт с круглой рамкой -->
      <div class="mx-auto mb-3" style="width: 256px; max-width: 100%;">
        <div class="relative mx-auto aspect-square w-full overflow-hidden rounded-full border border-border2 bg-card2">
          <canvas ref="canvas" :width="VP" :height="VP"
                  class="block h-full w-full cursor-move touch-none select-none"
                  @mousedown="onDown" @touchstart.prevent="onDown" @touchmove.prevent="onMove"
                  @touchend="onUp" @wheel="onWheel" />
          <p v-if="!img" class="pointer-events-none absolute inset-0 grid place-items-center px-4 text-center text-xs text-text3">
            Выберите изображение — перетаскивайте и масштабируйте, чтобы поместить в рамку.
          </p>
        </div>
      </div>

      <!-- Масштаб -->
      <div v-if="img" class="mb-4 flex items-center gap-2">
        <span class="text-xs text-text3">−</span>
        <input type="range" min="1" max="5" step="0.01" v-model.number="zoom" @input="onZoom"
               class="h-1.5 flex-1 accent-[var(--gb-accent)]" />
        <span class="text-xs text-text3">+</span>
      </div>

      <label class="mb-3 flex cursor-pointer items-center justify-center rounded-lg border border-dashed border-border2 px-4 py-2 text-sm text-text2 hover:bg-bg2">
        {{ img ? 'Выбрать другое изображение' : 'Выбрать изображение' }}
        <input type="file" accept="image/*" class="hidden" @change="onFile" />
      </label>

      <div class="flex flex-wrap gap-2">
        <button type="button" @click="save" :disabled="!img"
                class="flex-1 rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white hover:bg-accent2 disabled:opacity-50">
          Сохранить
        </button>
        <button v-if="current" type="button" @click="remove"
                class="rounded-lg border border-border2 px-4 py-2 text-sm text-red hover:bg-bg2">Удалить</button>
        <button type="button" @click="emit('close')"
                class="rounded-lg border border-border2 px-4 py-2 text-sm text-text2 hover:bg-bg2">Отмена</button>
      </div>
    </div>
  </div>
</template>
