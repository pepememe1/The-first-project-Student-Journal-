<script setup>
// ActivityWheel — выбор активности КОЛЕСОМ вместо сетки карточек (просьба Влада,
// 23.08.2026, с эскизом; предпросмотр картинкой — 27.08.2026, по присланному прототипу
// `activity-wheel.html`, геометрия у обоих одна и та же намеренно).
//
// ━━ ЗАЧЕМ КОЛЕСО ━━
// Активностей ровно шесть, и это число не растёт: сетка 3×2 показывала их как список
// настроек, из которого надо читать. У колеса все шесть равноудалены от центра и
// выбираются одним движением от середины — тот же приём, что у радиальных меню в играх.
// В середине — вход в журнал активностей: он относится ко всем шести сразу, и место в
// центре ровно это и означает.
//
// ━━ ЧТО ПРОИСХОДИТ ПРИ НАВЕДЕНИИ ━━
// Сектор растёт И ПО РАДИУСУ, И ПО УГЛУ, а соседи ужимаются, и внутрь него ложится
// КАРТИНКА ТОГО ЭКРАНА, который человек получит. Угол здесь не украшение: раскрытие с
// 60° до 96° даёт картинке примерно на 18 % большую сторону (посчитано, а не на глаз —
// см. `wheelGeometry.test.mjs`), и на узком клине снимок читался бы заметно хуже.
//
// 🔥 ЧЕТЫРЕ ТРЕБОВАНИЯ К КАРТИНКЕ, И КАЖДОЕ ЗАКРЫТО СВОИМ ПРИЁМОМ:
//  1. НЕ ВЫХОДИТ ЗА КРАЙ КУСКА ПИРОГА → `clipPath` по ТОМУ ЖЕ пути `d`, что и подложка
//     сектора. Не рамка поверх, а именно обрезка: рамка оставляла бы углы снаружи;
//  2. ТО ЖЕ ПОЛОЖЕНИЕ, ЧТО У ОРИГИНАЛА → у `<image>` НЕТ `transform` вообще. Крутится
//     и растёт только ФОРМА ОБРЕЗКИ, картинка живёт в обычных координатах. Ни поворота,
//     ни зеркала — что на файле, то и на экране;
//  3. ПУСТЫХ МЕСТ НЕТ → клин закрывает РАЗМЫТАЯ копия в режиме `slice` (заведомо больше
//     клина), поверх неё — чёткая копия целиком;
//  4. КАРТИНКУ ВИДНО ЦЕЛИКОМ, А ПОДПИСЬ НЕ ВЫЛЕЗАЕТ → снимок и плашка с названием
//     вписываются в клин ОДНИМ блоком (`fitBlockInSector` с запасом под подпись), а не
//     по очереди. Прототип клал подпись «на свободное место под снимком» и утверждал,
//     что оно есть всегда — на пропорции 4:3 её угол уходил за край клина.
//
// ⚠️ Почему нельзя «просто растянуть снимок на весь клин». Снимок широкий (порядка 4:3),
// клин узкий и высокий; чтобы закрыть его целиком, картинку надо увеличить в разы — и от
// экрана остаются две случайные плитки. Узнать по ним активность невозможно, а ради
// узнавания всё и затевалось. Отсюда пара «размытый фон + чёткий снимок».
//
// ⚠️ Картинки берутся из `web/public/activity/wheel/<id>.webp` (их собирает
// `tools/build_activity_shots.py` из `docs/activity-shots/`) и проверяются ЗАГРУЗКОЙ, а
// не наличием строки в списке: битый путь иначе дал бы пустой сектор, и выглядело бы это
// как поломка колеса, а не как отсутствующий файл. Файла нет — рисуем СХЕМУ того же
// экрана. Схема, а не поддельный «скриншот»: поддельный обещал бы человеку не то, что он
// увидит, и устаревал бы при каждой правке вёрстки.
//
// ⚠️ Наведение мыши на телефоне не существует. Там первое касание РАСКРЫВАЕТ сектор
// (показывает картинку), второе — выбирает. Иначе выбор шёл бы вслепую, а половина смысла
// колеса в том и состоит, чтобы сначала показать.
import { ref, computed, onMounted } from 'vue'
import { useLocaleStore } from '@/stores/locale'
//Геометрия — в отдельном модуле: только так её можно проверить числами
//(web/tests/wheelGeometry.test.mjs), не поднимая браузер. Копии формул здесь нет.
import { C, HALF as half, pt, sectorPath, sectorBBox, fitBlockInSector, shotAndCaption,
  CAPTION_GAP, CAPTION_H } from '@/utils/wheelGeometry'

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


// ── Картинки активностей ──────────────────────────────────────────────────────────
// id -> { src, aspect }. Пропорцию запоминаем СРАЗУ при загрузке: без неё «вписать
// снимок целиком» посчитать нечем, а брать её из вёрстки поздно — картинка уже нарисована.
const real = ref({})
const IMG_DIR = '/activity/wheel/'

onMounted(() => {
  for (const k of props.kinds) {
    const src = `${IMG_DIR}${k.id}.webp`
    const im = new Image()
    im.onload = () => {
      real.value = { ...real.value, [k.id]: { src, aspect: im.naturalWidth / im.naturalHeight } }
    }
    im.onerror = () => {}          // файла нет — остаётся схема, это не ошибка
    im.src = src
  }
})

// Оттенок схемы по категории. Только для схем-заглушек: настоящие цвета интерфейса
// живут в токенах `--gb-*`, а внутри data:URL до них не дотянуться — это отдельный
// документ, CSS-переменные страницы в него не проникают.
const HUE = { board: 172, quiz: 214, contest: 42, poll: 268, pulse: 8, timer: 130 }

/**
 * Схема экрана активности как data:URL. Повторяет СВОЙ экран продукта: доска с
 * конспектом, вопрос с плитками, карточка опроса, шкала среза, таймер. Пропорция 4:3 —
 * как у окна активности.
 */
function schema(id) {
  const hue = HUE[id] ?? 200
  const bg = '#171922'
  const line = 'rgba(255,255,255,.16)'
  const box = (x, y, w, h, f, r = 6) =>
    `<rect x='${x}' y='${y}' width='${w}' height='${h}' rx='${r}' fill='${f}'/>`
  let inner = ''

  if (id === 'board') {
    inner = box(24, 22, 200, 12, 'rgba(255,255,255,.85)', 6)
      + [0, 1, 2, 3, 4, 5].map((i) => box(24, 52 + i * 22, 150 - i * 8, 9, line)).join('')
      + "<g stroke='rgba(255,255,255,.75)' stroke-width='3' fill='none'>"
      + "<path d='M250 60 L300 60 L300 170 L250 170 Z'/><path d='M250 60 L262 48 L312 48 L300 60'/>"
      + "<path d='M312 48 L312 158 L300 170'/></g>"
      + box(258, 76, 34, 8, 'rgba(255,255,255,.6)', 3)
  } else if (id === 'quiz' || id === 'contest') {
    const tiles = [['#d31f3c', 16, 60], ['#1160c4', 172, 60], ['#d99000', 16, 118], ['#1d8a3c', 172, 118]]
    inner = box(16, 20, 90, 10, line) + box(16, 38, 210, 12, 'rgba(255,255,255,.8)')
      + tiles.map(([c, x, y]) => box(x, y, 140, 44, c, 8)).join('')
      + (id === 'quiz' ? box(16, 176, 140, 44, '#d31f3c', 8)
                       : box(280, 18, 36, 18, 'rgba(255,255,255,.14)', 9))
  } else if (id === 'poll') {
    inner = box(20, 24, 200, 12, 'rgba(255,255,255,.8)') + box(20, 44, 120, 9, line)
      + box(20, 70, 296, 34, 'rgba(53,201,192,.30)', 8) + box(20, 112, 296, 34, 'rgba(255,255,255,.08)', 8)
      + box(30, 82, 60, 10, 'rgba(255,255,255,.75)') + box(30, 124, 76, 10, line)
      + box(20, 162, 150, 9, line)
  } else if (id === 'pulse') {
    const seg = 10; const cx = 168; const cy = 176; const r0 = 66; const r1 = 116
    let arcs = ''
    for (let i = 0; i < seg; i++) {
      const a0 = 180 + (i * 180) / seg + 1.6
      const a1 = 180 + ((i + 1) * 180) / seg - 1.6
      const p = (r, a) => [cx + r * Math.cos((a * Math.PI) / 180), cy + r * Math.sin((a * Math.PI) / 180)]
      const [x0, y0] = p(r0, a0); const [x1, y1] = p(r1, a0)
      const [x2, y2] = p(r1, a1); const [x3, y3] = p(r0, a1)
      arcs += `<path d='M${x0} ${y0} L${x1} ${y1} A${r1} ${r1} 0 0 1 ${x2} ${y2} `
        + `L${x3} ${y3} A${r0} ${r0} 0 0 0 ${x0} ${y0} Z' fill='hsl(${i * 12} 72% 46%)'/>`
    }
    inner = box(96, 26, 148, 12, 'rgba(255,255,255,.8)') + arcs
      + `<circle cx='${cx}' cy='${cy}' r='11' fill='#fff'/>`
  } else {
    inner = box(110, 26, 116, 11, line)
      + "<circle cx='168' cy='140' r='70' fill='none' stroke='rgba(255,255,255,.14)' stroke-width='14'/>"
      + `<path d='M168 70 A70 70 0 1 1 98 140' fill='none' stroke='hsl(${hue} 65% 50%)' `
      + "stroke-width='14' stroke-linecap='round'/>"
      + box(126, 128, 84, 22, 'rgba(255,255,255,.85)', 5)
  }

  const s = "<svg xmlns='http://www.w3.org/2000/svg' width='336' height='252' viewBox='0 0 336 252'>"
    + `<rect width='336' height='252' fill='${bg}'/>`
    + `<rect x='.5' y='.5' width='335' height='251' fill='none' stroke='hsl(${hue} 50% 40%)' stroke-opacity='.5'/>`
    + inner + '</svg>'
  return `data:image/svg+xml;utf8,${encodeURIComponent(s)}`
}

//Ширина плашки подписи по длине названия. Метрик текста в SVG до отрисовки не
//получить, поэтому оцениваем по числу символов — с запасом, чтобы название не упиралось
//в края плашки.
function labelWidth(id) {
  return locale.t(`activity.kind.${id}`, id).length * 7.9 + 20
}

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
    const seg = {
      ...k,
      open,
      a0,
      a1,
      rIn,
      rOut,
      mid: (a0 + a1) / 2,
      d: sectorPath(a0, a1, rIn, rOut),
      label: pt((rIn + rOut) / 2, (a0 + a1) / 2),
    }
    if (!open) return seg
    // Тяжёлый расчёт — ТОЛЬКО для раскрытого: он один, и считается на смену наведения.
    const got = real.value[k.id]
    const src = got ? got.src : schema(k.id)
    const aspect = got ? got.aspect : 336 / 252
    const box = sectorBBox(a0, a1, rIn, rOut)
    //Снимок и подпись вписываются в клин ОДНИМ блоком, а не по очереди: почему именно
    //так — в докстринге `fitBlockInSector`, держит `wheelGeometry.test.mjs`.
    const block = fitBlockInSector(aspect, CAPTION_GAP + CAPTION_H, a0, a1, rIn, rOut)
    const lw = labelWidth(k.id)
    const { shot, caption } = shotAndCaption(block, lw)
    //Плашка не шире снимка, поэтому длинное название в неё может не поместиться. Сжимаем
    //САМ ТЕКСТ (`textLength`), а не отпускаем его наружу: обрезать многоточием на трёх-
    //четырёх буквах бессмысленно («Срез пон…»), а вылезший за плашку текст ляжет на
    //картинку и будет срезан обрезкой клина.
    const squeeze = lw > caption.w ? Math.max(caption.w - 12, 8) : 0
    return { ...seg, src, box, fit: shot, caption, squeeze }
  })
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
// Tab, выбирал бы вслепую — картинку он бы не увидел ни разу.
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
        <defs>
          <!-- Размытие в единицах viewBox, а не пикселей — одинаково на любом размере. -->
          <filter id="gb-wheel-soft" x="-20%" y="-20%" width="140%" height="140%">
            <feGaussianBlur stdDeviation="7" />
          </filter>
          <!-- Обрезка по ТОМУ ЖЕ пути, что и подложка сектора: картинка физически не
               может выйти за край своего куска пирога. -->
          <clipPath v-for="s in layout" :key="`clip-${s.id}`" :id="`gb-wheel-clip-${s.id}`">
            <path :d="s.d" />
          </clipPath>
        </defs>

        <g v-for="s in layout" :key="s.id">
          <path :d="s.d" class="gb-seg" :class="s.open ? 'gb-seg-open' : ''"
                role="button" tabindex="0" :aria-label="locale.t(`activity.kind.${s.id}`, s.id)"
                @pointerenter="onEnter($event, s.id)" @focus="onFocus(s.id)"
                @click="onActivate(s.id)"
                @keydown.enter.prevent="emit('choose', s.id)"
                @keydown.space.prevent="emit('choose', s.id)" />

          <!-- Раскрытый сектор: размытая копия закрывает клин целиком, чёткая показывает
               экран в родных пропорциях. Обе — под обрезкой и БЕЗ transform. -->
          <template v-if="s.open">
            <image :href="s.src" :x="s.box.x" :y="s.box.y" :width="s.box.w" :height="s.box.h"
                   preserveAspectRatio="xMidYMid slice" filter="url(#gb-wheel-soft)"
                   opacity="0.55" :clip-path="`url(#gb-wheel-clip-${s.id})`"
                   class="pointer-events-none" />
            <path :d="s.d" class="gb-seg-veil pointer-events-none"
                  :clip-path="`url(#gb-wheel-clip-${s.id})`" />
            <image :href="s.src" :x="s.fit.x" :y="s.fit.y" :width="s.fit.w" :height="s.fit.h"
                   preserveAspectRatio="xMidYMid meet"
                   :clip-path="`url(#gb-wheel-clip-${s.id})`" class="pointer-events-none" />
            <!-- Рамка снимка: без неё тёмный экран сливается с размытым фоном себя же. -->
            <rect :x="s.fit.x" :y="s.fit.y" :width="s.fit.w" :height="s.fit.h" rx="4"
                  class="gb-shot-frame pointer-events-none"
                  :clip-path="`url(#gb-wheel-clip-${s.id})`" />
            <rect :x="s.caption.x" :y="s.caption.y" :width="s.caption.w" :height="s.caption.h"
                  rx="12" class="gb-cap-plate pointer-events-none" />
            <text :x="s.caption.x + s.caption.w / 2" :y="s.caption.y + s.caption.h / 2 + 4"
                  text-anchor="middle" class="gb-cap pointer-events-none"
                  :textLength="s.squeeze || null" lengthAdjust="spacingAndGlyphs">
              {{ locale.t(`activity.kind.${s.id}`, s.id) }}
            </text>
          </template>

          <!-- Сектор в покое: эмодзи и название. Ярлык не перехватывает мышь — иначе
               курсор, наехав на текст, «выходил» бы из сектора и раскрытие моргало. -->
          <template v-else>
            <text :x="s.label[0]" :y="s.label[1] - 6" text-anchor="middle"
                  class="gb-emoji pointer-events-none">{{ s.emoji }}</text>
            <text :x="s.label[0]" :y="s.label[1] + 12" text-anchor="middle"
                  class="gb-name pointer-events-none">
              {{ locale.t(`activity.kind.${s.id}`, s.id) }}
            </text>
          </template>
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
.gb-seg-open { fill: var(--gb-accent-glow); stroke: var(--gb-accent); stroke-width: 1.8 }

/* Плавное «раскрытие» сектора. `transition: d` работает не во всех движках, поэтому
   форма пересчитывается покадрово и без анимации выглядит просто мгновенной — это
   допустимая деградация, а не поломка. */
@media (prefers-reduced-motion: reduce) { .gb-seg { transition: none } }

/* Затемнение поверх размытого фона: без него чёткий снимок теряется на копии себя же. */
.gb-seg-veil { fill: #05070c; opacity: .40 }
.gb-shot-frame { fill: none; stroke: rgba(255, 255, 255, .28); stroke-width: 1 }

.gb-emoji { font-size: 17px; dominant-baseline: middle }
.gb-name {
  font-size: 11px; font-weight: 600; fill: var(--gb-text);
  dominant-baseline: middle;
}
.gb-cap-plate { fill: #0b0d13; opacity: .86 }
.gb-cap { font-size: 12px; font-weight: 700; fill: #fff; dominant-baseline: middle }

.gb-hub {
  fill: var(--gb-card);
  stroke: var(--gb-border2);
  stroke-width: 1.5;
}
.gb-hub-live { cursor: pointer }
.gb-hub-live:hover { stroke: var(--gb-accent) }
.gb-hub-text { font-size: 10px; font-weight: 700; fill: var(--gb-text2); dominant-baseline: middle }
</style>
