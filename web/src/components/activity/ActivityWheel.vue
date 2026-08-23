<script setup>
// ActivityWheel — выбор активности КОЛЕСОМ вместо сетки карточек (просьба Влада,
// 23.08.2026, с эскизом).
//
// ━━ ЗАЧЕМ КОЛЕСО ━━
// Активностей ровно шесть, и это число не растёт: сетка 3×2 показывала их как список
// настроек, из которого надо читать. У колеса все шесть равноудалены от центра и
// выбираются одним движением от середины — тот же приём, что у радиальных меню в играх.
// В середине — вход в журнал активностей: он относится ко всем шести сразу, и место в
// центре ровно это и означает.
//
// ━━ ЧТО ПРОИСХОДИТ ПРИ НАВЕДЕНИИ ━━
// Сектор растёт И ПО РАДИУСУ, И ПО УГЛУ, а соседи ужимаются. Угол здесь не украшение:
// внутри узкого сектора (60°) физически некуда положить картинку с подписью — у клина
// ширина у основания стремится к нулю. На 96° в наружной трети помещается и то и другое.
//
// ⚠️ Картинки — СХЕМАТИЧЕСКИЕ, нарисованы здесь же в SVG, а не снимки экрана. Это
// честно: настоящих снимков у нас нет, а поддельный «скриншот» обещал бы человеку не то,
// что он увидит. Схема показывает суть («доска с рукописью», «вопрос и варианты»,
// «пьедестал») и не устаревает при каждой правке вёрстки. Появятся настоящие снимки —
// менять только блок предпросмотра в разметке ниже (<svg viewBox="0 0 120 64">).
//
// ⚠️ Наведение мыши на телефоне не существует. Там первое касание РАСКРЫВАЕТ сектор
// (показывает картинку и описание), второе — выбирает. Иначе выбор шёл бы вслепую, а
// половина смысла колеса в том и состоит, чтобы сначала показать.
import { ref, computed } from 'vue'
import { useLocaleStore } from '@/stores/locale'

const props = defineProps({
  kinds: { type: Array, required: true },        // [{ id, emoji }]
  canSeeJournal: { type: Boolean, default: false },
})
const emit = defineEmits(['choose', 'journal'])
const locale = useLocaleStore()

const R_IN = 0.30                 // радиус втулки, доля от половины стороны
const R_OUT = 0.94                // обычный внешний радиус
const R_OUT_HOVER = 1.0           // раскрытый
const SPREAD = 96                 // угол раскрытого сектора
const GAP = 1.1                   // просвет между секторами, градусы

const hovered = ref('')           // id раскрытого сектора ('' — колесо в покое)
const revealed = ref('')          // то же для касания: первое касание раскрывает

const C = 200                     // центр в координатах viewBox 0 0 400 400
const half = 200

const rad = (deg) => ((deg - 90) * Math.PI) / 180
const pt = (r, deg) => [C + r * Math.cos(rad(deg)), C + r * Math.sin(rad(deg))]

/**
 * Углы всех секторов с учётом раскрытого.
 * Раскрытый остаётся НА СВОЁМ МЕСТЕ (центрирован на своей исходной середине), остальные
 * делят остаток по кругу в прежнем порядке — иначе колесо провернулось бы под курсором
 * и человек навёлся бы на соседа.
 */
const layout = computed(() => {
  const n = props.kinds.length
  const step = 360 / n
  const openIdx = props.kinds.findIndex((k) => k.id === (hovered.value || revealed.value))
  const out = []
  if (openIdx < 0) {
    for (let i = 0; i < n; i++) out.push({ from: i * step, to: (i + 1) * step })
  } else {
    const mid = openIdx * step + step / 2
    const rest = (360 - SPREAD) / (n - 1)
    out[openIdx] = { from: mid - SPREAD / 2, to: mid + SPREAD / 2 }
    let cursor = mid + SPREAD / 2
    for (let j = 1; j < n; j++) {
      const i = (openIdx + j) % n
      out[i] = { from: cursor, to: cursor + rest }
      cursor += rest
    }
  }
  return props.kinds.map((k, i) => {
    const open = i === openIdx
    const a0 = out[i].from + GAP / 2
    const a1 = out[i].to - GAP / 2
    const rOut = (open ? R_OUT_HOVER : R_OUT) * half
    const rIn = R_IN * half
    const [x0, y0] = pt(rIn, a0)
    const [x1, y1] = pt(rOut, a0)
    const [x2, y2] = pt(rOut, a1)
    const [x3, y3] = pt(rIn, a1)
    const big = a1 - a0 > 180 ? 1 : 0
    return {
      ...k, open,
      mid: (a0 + a1) / 2,
      d: `M ${x0} ${y0} L ${x1} ${y1} A ${rOut} ${rOut} 0 ${big} 1 ${x2} ${y2} `
        + `L ${x3} ${y3} A ${rIn} ${rIn} 0 ${big} 0 ${x0} ${y0} Z`,
      // Ярлык (эмодзи + название) — на середине кольца; у раскрытого он уезжает к
      // основанию, освобождая наружную треть под картинку с описанием.
      label: pt(open ? rIn + 22 : (rIn + rOut) / 2, (a0 + a1) / 2),
    }
  })
})

// Точка, вокруг которой рисуется карточка предпросмотра, в ПРОЦЕНТАХ контейнера —
// проценты, а не пиксели, чтобы колесо целиком масштабировалось на узком экране.
const previewAt = computed(() => {
  const seg = layout.value.find((s) => s.open)
  if (!seg) return null
  const [x, y] = pt(0.72 * half, seg.mid)
  return { left: `${(x / 400) * 100}%`, top: `${(y / 400) * 100}%`, id: seg.id }
})

/**
 * Наведение — ТОЛЬКО мышью и пером.
 *
 * ⚠️ Проверка `pointerType` здесь обязательна, а не перестраховка: в Chromium
 * `pointerenter` прилетает и от ПАЛЬЦА, вместе с касанием. Без неё первое же касание
 * и раскрывало бы сектор, и тут же его выбирало — то есть на телефоне предпросмотра
 * не существовало бы вовсе, хотя ради него колесо и затевалось.
 */
function onEnter(e, id) {
  if (e.pointerType === 'touch') return
  hovered.value = id
}
function onLeave() { hovered.value = '' }

// Клавиатура: фокус раскрывает сектор так же, как наведение. Иначе человек, идущий по
// Tab, выбирал бы вслепую — картинку и описание он бы не увидел ни разу.
function onFocus(id) { hovered.value = id }

/** Касание: первое раскрывает, второе выбирает. Мышью сюда приходим уже раскрытыми. */
function onActivate(id) {
  if (revealed.value === id || hovered.value === id) { emit('choose', id); return }
  revealed.value = id
}
</script>

<template>
  <div class="mx-auto w-full max-w-[420px]">
    <div class="relative aspect-square w-full select-none" @pointerleave="onLeave">
      <svg viewBox="0 0 400 400" class="h-full w-full overflow-visible">
        <g v-for="s in layout" :key="s.id">
          <path :d="s.d" class="gb-seg" :class="s.open ? 'gb-seg-open' : ''"
                role="button" tabindex="0" :aria-label="locale.t(`activity.kind.${s.id}`, s.id)"
                @pointerenter="onEnter($event, s.id)" @focus="onFocus(s.id)"
                @click="onActivate(s.id)"
                @keydown.enter.prevent="emit('choose', s.id)"
                @keydown.space.prevent="emit('choose', s.id)" />
          <!-- Ярлык не перехватывает мышь: иначе курсор, наехав на текст, «выходил» бы
               из сектора и раскрытие моргало бы. -->
          <text :x="s.label[0]" :y="s.label[1] - 6" text-anchor="middle"
                class="gb-emoji pointer-events-none">{{ s.emoji }}</text>
          <text :x="s.label[0]" :y="s.label[1] + 12" text-anchor="middle"
                class="gb-name pointer-events-none" :class="s.open ? 'gb-name-open' : ''">
            {{ locale.t(`activity.kind.${s.id}`, s.id) }}
          </text>
        </g>

        <!-- Втулка: журнал активностей — он про все шесть сразу, потому и в центре -->
        <circle :cx="C" :cy="C" :r="R_IN * half - 4" class="gb-hub"
                :class="canSeeJournal ? 'gb-hub-live' : ''"
                @click="canSeeJournal && emit('journal')" />
        <text :x="C" :y="C - 6" text-anchor="middle" class="gb-emoji pointer-events-none">📓</text>
        <text :x="C" :y="C + 14" text-anchor="middle" class="gb-hub-text pointer-events-none">
          {{ locale.t('activity.journal.short', 'Журнал') }}
        </text>
      </svg>

      <!-- Предпросмотр внутри раскрытого сектора: схема сверху, подпись снизу -->
      <div v-if="previewAt" class="pointer-events-none absolute w-[38%] -translate-x-1/2 -translate-y-1/2
                                   text-center"
           :style="{ left: previewAt.left, top: previewAt.top }">
        <svg viewBox="0 0 120 64" class="mx-auto w-full rounded-md" role="img"
             :aria-label="locale.t(`activity.hint.${previewAt.id}`, '')">
          <rect x="1" y="1" width="118" height="62" rx="5" class="gb-pv-bg" />
          <g class="gb-pv-ink">
            <!-- Доска: рукописный след и переданное перо -->
            <template v-if="previewAt.id === 'board'">
              <path d="M12 44 C28 20, 40 52, 56 30 S82 18, 100 38" fill="none" stroke-width="3" />
              <circle cx="100" cy="38" r="4" class="gb-pv-accent" stroke="none" />
            </template>
            <!-- Викторина: вопрос и варианты, один отмечен -->
            <template v-else-if="previewAt.id === 'quiz'">
              <rect x="12" y="10" width="72" height="7" rx="3" />
              <rect x="12" y="26" width="96" height="9" rx="4" class="gb-pv-accent" stroke="none" />
              <rect x="12" y="40" width="80" height="9" rx="4" opacity=".45" />
            </template>
            <!-- Соревнование: пьедестал -->
            <template v-else-if="previewAt.id === 'contest'">
              <rect x="46" y="16" width="28" height="40" rx="2" class="gb-pv-accent" stroke="none" />
              <rect x="16" y="30" width="26" height="26" rx="2" opacity=".6" />
              <rect x="78" y="38" width="26" height="18" rx="2" opacity=".45" />
            </template>
            <!-- Опрос: столбики -->
            <template v-else-if="previewAt.id === 'poll'">
              <rect x="14" y="16" width="58" height="8" rx="4" class="gb-pv-accent" stroke="none" />
              <rect x="14" y="30" width="88" height="8" rx="4" opacity=".55" />
              <rect x="14" y="44" width="34" height="8" rx="4" opacity=".4" />
            </template>
            <!-- Срез понимания: шкала со стрелкой -->
            <template v-else-if="previewAt.id === 'pulse'">
              <path d="M18 48 A42 42 0 0 1 102 48" fill="none" stroke-width="5" opacity=".45" />
              <path d="M18 48 A42 42 0 0 1 46 15" fill="none" stroke-width="5" class="gb-pv-accent-s" />
              <line x1="60" y1="48" x2="76" y2="26" stroke-width="3" />
            </template>
            <!-- Тайм-бокс: циферблат -->
            <template v-else>
              <circle cx="60" cy="32" r="21" fill="none" stroke-width="3" opacity=".5" />
              <path d="M60 32 L60 17" stroke-width="3" />
              <path d="M60 32 L72 38" stroke-width="3" class="gb-pv-accent-s" />
            </template>
          </g>
        </svg>
        <p class="gb-pv-hint mt-1">{{ locale.t(`activity.hint.${previewAt.id}`, '') }}</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.gb-seg {
  fill: var(--gb-bg2);
  stroke: var(--gb-border2);
  stroke-width: 1.5;
  cursor: pointer;
  transition: d .22s cubic-bezier(.2, .9, .3, 1), fill .18s, stroke .18s;
}
.gb-seg:hover, .gb-seg:focus-visible { stroke: var(--gb-accent) }
.gb-seg-open { fill: var(--gb-accent-glow); stroke: var(--gb-accent) }

/* Плавное «раскрытие» сектора. `transition: d` работает не во всех движках, поэтому
   форма пересчитывается покадрово и без анимации выглядит просто мгновенной — это
   допустимая деградация, а не поломка. */
@media (prefers-reduced-motion: reduce) { .gb-seg { transition: none } }

.gb-emoji { font-size: 17px; dominant-baseline: middle }
.gb-name {
  font-size: 11px; font-weight: 600; fill: var(--gb-text);
  dominant-baseline: middle;
}
.gb-name-open { fill: var(--gb-accent) }

.gb-hub {
  fill: var(--gb-card);
  stroke: var(--gb-border2);
  stroke-width: 1.5;
}
.gb-hub-live { cursor: pointer }
.gb-hub-live:hover { stroke: var(--gb-accent) }
.gb-hub-text { font-size: 10px; font-weight: 700; fill: var(--gb-text2); dominant-baseline: middle }

.gb-pv-bg { fill: var(--gb-card); stroke: var(--gb-border2); stroke-width: 1 }
.gb-pv-ink { stroke: var(--gb-text3); fill: var(--gb-text3); stroke-linecap: round }
.gb-pv-accent { fill: var(--gb-accent) }
.gb-pv-accent-s { stroke: var(--gb-accent) }
.gb-pv-hint {
  font-size: 10px; line-height: 1.25; color: var(--gb-text2);
  text-wrap: balance;
}
</style>
