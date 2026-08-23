<script setup>
// Дерево Делтарун — выпадает на переключении между вкладками, 1/666.
//
// ⚠️ ОВЕРЛЕЙ БЕЗ РОУТИНГА, и это принципиально: адрес не меняется, значит и подсмотреть
// нечего, и напрямую зайти невозможно — это не URL, а временный элемент, который
// существует, только пока показан. Перезагрузка страницы его убирает.
//
// Реплики листаются КЛИКОМ по окну, сами не пролистываются. Взял яйцо — дальше при
// любом заходе остаётся только «Это дерево».
import { onMounted, onBeforeUnmount, ref } from 'vue'
import { useEasterStore } from '@/stores/easterEggs'
import { mumble } from '@/utils/mumble'
const emit = defineEmits(['close'])
const easter = useEasterStore()

const FULL = ['* (Он за деревом.)', '* (Он предлагает тебе что-то.)', '* (Вы получили "Яйцо")',
              '* (Ну, здесь теперь никого нет.)', '* (Это дерево.)']
const SHORT = ['* (Это дерево.)']

// Яйцо уже брали? Помним на устройстве: сервер знает про ачивку, но спрашивать его
// ради одной строки диалога — лишний запрос ровно в тот момент, когда важна плавность.
const taken = ref(localStorage.getItem('gb.egg.tree') === '1')
const lines = ref([])
const dlg = ref('')
const started = ref(false)
const shown = ref(false)
let busy = false, music = null

onMounted(() => {
  requestAnimationFrame(() => { shown.value = true })
  music = new Audio('/easter/snd/tree.ogg')
  music.loop = true
  music.volume = 0
  music.play().catch(() => {})
  const t0 = performance.now()
  const id = setInterval(() => {
    const k = Math.min(1, (performance.now() - t0) / 1400)
    music.volume = 0.3 * k
    if (k >= 1) clearInterval(id)
  }, 50)
})
onBeforeUnmount(() => { if (music) music.pause() })

async function type(text) {
  busy = true
  dlg.value = ''
  for (let i = 1; i <= text.length; i++) {
    dlg.value = text.slice(0, i)
    if (i % 2 === 0 && text[i - 1] !== ' ') mumble()
    await new Promise((r) => setTimeout(r, 30))
  }
  busy = false
}

let step = 0
async function talk() {
  if (started.value) return
  started.value = true
  lines.value = taken.value ? SHORT : FULL
  await type(lines.value[0])
}

async function advance() {
  if (!started.value || busy) return
  step += 1
  if (step < lines.value.length) { await type(lines.value[step]); return }
  const first = lines.value.length > 1
  started.value = false; step = 0; dlg.value = ''
  if (first && !taken.value) {
    taken.value = true
    localStorage.setItem('gb.egg.tree', '1')
    await easter.claim('deltarune_tree')
  }
}
</script>

<template>
  <div class="fixed inset-0 z-[95] grid place-items-center bg-black transition-opacity duration-500 soul"
       :style="{ opacity: shown ? 1 : 0 }">
    <button type="button" class="soul absolute inset-0 cursor-[inherit]" aria-label="Закрыть"
            @click="emit('close')"></button>

    <img src="/easter/img/tree.gif" alt="" class="relative w-[31%] max-w-[280px]"
         style="image-rendering:pixelated;filter:drop-shadow(0 0 26px rgba(200,30,90,.3))" />

    <button type="button" @click.stop="talk" aria-label="Осмотреть дерево"
            class="soul absolute bottom-[18%] left-1/2 h-[20%] w-[12%] -translate-x-1/2"></button>

    <div v-if="started" class="utbox soul absolute inset-x-[7%] bottom-[6%]" @click.stop="advance">
      <span>{{ dlg }}</span>
      <span class="absolute bottom-1 right-2.5 text-[9px] text-[#8a8a8a]">▼ клик</span>
    </div>
  </div>
</template>

<style scoped>
/* Курсор-душа: смысловая часть сцены, а не украшение. */
.soul { cursor: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='18' height='18' viewBox='0 0 8 8'%3E%3Cpath fill='%23f00' d='M1 1h2v1h2V1h2v1h1v3H7v1H6v1H5v1H3V7H2V6H1V5H0V2h1z'/%3E%3C/svg%3E") 9 9, auto; }
.utbox { background:#000; border:4px solid #fff; color:#fff; padding:14px 16px; min-height:58px;
         font-family:'Press Start 2P', monospace; font-size:11px; line-height:1.95; }
</style>
