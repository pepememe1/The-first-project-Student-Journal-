<script setup>
// BoardCard — сохранённая доска в ленте (PLAN-ACTIVITIES §8.1).
//
// Показываем ПРЕВЬЮ ИЗ ШТРИХОВ, а не картинку: растра у нас нет и не будет (см.
// BoardCanvas — файлового хранилища в проекте не существует). Рисуем те же штрихи в
// маленький canvas — это единицы килобайт и чётко на любом экране.
import { ref, onMounted, nextTick } from 'vue'
import { Presentation } from '@lucide/vue'
import { useLocaleStore } from '@/stores/locale'
import { activitiesApi } from '@/api/endpoints'

const props = defineProps({ board: { type: Object, required: true } })
const locale = useLocaleStore()
const canvas = ref(null)
const open = ref(false)

async function draw() {
  await nextTick()
  const el = canvas.value
  if (!el) return
  let strokes = []
  try {
    const { data } = await activitiesApi.board(props.board.id)
    strokes = data.strokes || []
  } catch { return }
  const ctx = el.getContext('2d')
  const { width: w, height: h } = el
  ctx.clearRect(0, 0, w, h)
  ctx.lineCap = 'round'
  ctx.lineJoin = 'round'
  for (const s of strokes) {
    if (!s?.p || s.p.length < 4) continue
    ctx.strokeStyle = s.c || '#000'
    //Толщина масштабируется вместе с превью, иначе на маленьком холсте линии сливаются
    //в пятно и «доска» читается как клякса.
    ctx.lineWidth = Math.max(1, (s.w || 3) * (w / 900))
    ctx.beginPath()
    ctx.moveTo(s.p[0] * w, s.p[1] * h)
    for (let i = 2; i < s.p.length; i += 2) ctx.lineTo(s.p[i] * w, s.p[i + 1] * h)
    ctx.stroke()
  }
}

onMounted(draw)
async function toggle() { open.value = !open.value; if (open.value) await draw() }
</script>

<template>
  <div class="my-1 flex justify-start">
    <div class="min-w-0 max-w-[75%] overflow-hidden rounded-2xl border border-border2 bg-card shadow-sm">
      <button type="button" @click="toggle"
              class="flex w-full min-w-0 items-center gap-2 px-4 py-2 text-left text-sm hover:bg-bg2">
        <Presentation class="size-4 shrink-0 text-accent" />
        <span class="min-w-0 flex-1 truncate font-semibold text-text">
          {{ board.title || locale.t('activity.kind.board', 'Доска') }}
        </span>
        <span class="shrink-0 text-[11px] text-text3">{{ board.strokes_count }}</span>
      </button>
      <div v-show="open" class="border-t border-border2 bg-bg2 p-2">
        <canvas ref="canvas" width="360" height="220" class="w-full rounded-lg bg-card" />
      </div>
    </div>
  </div>
</template>
