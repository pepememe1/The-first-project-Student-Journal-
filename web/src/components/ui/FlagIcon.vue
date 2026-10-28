<script setup>
// FlagIcon — флаг языка интерфейса, нарисованный SVG прямо в разметке (28.10.2026).
//
// Флаг-эмодзи тянул на экран входа шрифт Twemoji целиком — 466 КБ ради одной картинки:
// обе буквы флага попадают в unicode-range шрифта. Windows флагов-эмодзи не
// рисует вовсе, поэтому без шрифта там были бы буквы «RU». Встроенный SVG не качается
// отдельно, не требует картинок в бандле и одинаково чёткий на любом экране.
defineProps({
  code: { type: String, required: true },
})

// Пятиконечная звезда радиуса 1 с центром в нуле, вершиной вверх.
const STAR = '0,-1 .225,-.309 .951,-.309 .363,.118 .588,.809 0,.382 -.588,.809 -.363,.118 -.951,-.309 -.225,-.309'
const CN_SMALL = [[10, 2], [12, 4], [12, 7], [10, 9]]
</script>

<template>
  <svg class="h-3.5 w-5 shrink-0 overflow-hidden rounded-xs shadow-[0_0_0_1px_rgba(0,0,0,.12)]"
       viewBox="0 0 30 20" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
    <template v-if="code === 'ru'">
      <rect width="30" height="20" fill="#fff" />
      <rect y="6.67" width="30" height="6.67" fill="#0039a6" />
      <rect y="13.33" width="30" height="6.67" fill="#d52b1e" />
    </template>
    <template v-else-if="code === 'zh'">
      <rect width="30" height="20" fill="#ee1c25" />
      <polygon :points="STAR" fill="#ffde00" transform="translate(5 5) scale(3)" />
      <polygon v-for="([x, y], i) in CN_SMALL" :key="i" :points="STAR" fill="#ffde00"
               :transform="`translate(${x} ${y}) scale(1)`" />
    </template>
    <!-- Британский флаг — упрощённый: красные диагонали без смещения, на 20 пикселях
         разницы не видно. Поле 2:1 обрезается до 3:2 по краям, как у эмодзи. -->
    <g v-else-if="code === 'en'" transform="translate(-5 0) scale(.6667)">
      <rect width="60" height="30" fill="#012169" />
      <path d="M0,0 L60,30 M60,0 L0,30" stroke="#fff" stroke-width="6" />
      <path d="M0,0 L60,30 M60,0 L0,30" stroke="#c8102e" stroke-width="2" />
      <path d="M30,0 v30 M0,15 h60" stroke="#fff" stroke-width="10" />
      <path d="M30,0 v30 M0,15 h60" stroke="#c8102e" stroke-width="6" />
    </g>
  </svg>
</template>
