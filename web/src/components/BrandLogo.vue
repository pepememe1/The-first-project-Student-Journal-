<script setup>
// BrandLogo — утверждённый фирменный знак (вариант №8): двухцветный вращающийся гексагон
// с «GB», средней обводкой и мягкой тенью, вращающимся внешним кольцом со свечением и
// СТАТИЧНЫМ внутренним кольцом. Цвет ЯДРА всегда из темы (--gb-accent / --gb-accent2),
// поэтому знак подстраивается под цветовую гамму. Векторный — чёткий на любом экране.
//
// props:
//   size    — сторона в px;
//   oncard  — вариант для КАРТОЧКИ (экран входа, светлый/тёмный фон): кольца и обводка
//             акцентным цветом темы (видны на белом), ядро двухцветное, «GB» белые.
//             По умолчанию (шапка на акцентном фоне): кольца/обводка белые, свечение белое.
import { computed } from 'vue'

const props = defineProps({
  size: { type: Number, default: 40 },
  oncard: { type: Boolean, default: false },
  // animated=false — СТАТИЧНЫЙ знак (без вращения колец/ядра). Нужен там, где анимация
  // неуместна или невозможна: печать, растровые иконки, экономия отрисовки в списках.
  animated: { type: Boolean, default: true },
})

// Уникальный суффикс id фильтров/градиента — чтобы несколько знаков не конфликтовали.
const uid = 'bl' + Math.random().toString(36).slice(2, 8)

// Пути гексагонов (viewBox 200): внешнее кольцо, внутреннее кольцо, ядро.
const OUTER = 'M100,7 L180.5,53.5 L180.5,146.5 L100,193 L19.5,146.5 L19.5,53.5 Z'
const INNER = 'M100,18 L171,59 L171,141 L100,182 L29,141 L29,59 Z'
const CORE  = 'M100,30 L160.6,65 L160.6,135 L100,170 L39.4,135 L39.4,65 Z'

// Цвет колец/обводки/свечения: на карточке — акцент темы (виден на белом), в шапке — белый.
const lineColor = computed(() => (props.oncard ? 'var(--gb-accent)' : '#ffffff'))
</script>

<template>
  <svg :width="size" :height="size" viewBox="0 0 200 200" xmlns="http://www.w3.org/2000/svg"
       role="img" aria-label="GradeBookAI" style="display:block; overflow:visible;">
    <defs>
      <linearGradient :id="uid + '-tt'" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stop-color="var(--gb-accent)" />
        <stop offset="0.5" stop-color="var(--gb-accent)" />
        <stop offset="0.5" stop-color="var(--gb-accent2)" />
        <stop offset="1" stop-color="var(--gb-accent2)" />
      </linearGradient>
      <filter :id="uid + '-soft'" x="-40%" y="-40%" width="180%" height="180%">
        <feDropShadow dx="0" dy="4" stdDeviation="6" flood-color="#0f1b22" flood-opacity="0.28" />
      </filter>
      <filter :id="uid + '-glow'" x="-60%" y="-60%" width="220%" height="220%">
        <feDropShadow dx="0" dy="0" stdDeviation="4.5" :flood-color="lineColor" flood-opacity="0.9" />
      </filter>
    </defs>

    <!-- Внешнее кольцо: со свечением. Вращается только когда animated. -->
    <g fill="none" :stroke="lineColor" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"
       stroke-dasharray="20 16" :filter="`url(#${uid}-glow)`">
      <animateTransform v-if="animated" attributeName="transform" type="rotate" from="0 100 100" to="360 100 100" dur="22s" repeatCount="indefinite" />
      <path :d="OUTER" />
    </g>

    <!-- Внутреннее кольцо: СТАТИЧНОЕ (не крутится). -->
    <path :d="INNER" fill="none" :stroke="lineColor" stroke-width="3" stroke-linejoin="round" opacity="0.85" />

    <!-- Ядро: двухцветное (цвет темы), крутится. В шапке — белая обводка (видна на
         акцентном фоне); на карточке обводка не нужна (цветное ядро само видно на белом). -->
    <g :filter="`url(#${uid}-soft)`">
      <g>
        <animateTransform v-if="animated" attributeName="transform" type="rotate" from="0 100 100" to="360 100 100" dur="19s" repeatCount="indefinite" />
        <path :d="CORE" :fill="`url(#${uid}-tt)`"
              :stroke="oncard ? 'none' : '#ffffff'" stroke-width="12"
              stroke-linejoin="round" paint-order="stroke" />
      </g>
    </g>

    <!-- GB: белые на цветном ядре, уменьшены, стоят ровно. -->
    <text x="100" y="103" text-anchor="middle" dominant-baseline="central" fill="#ffffff"
          font-family="'Syne','Segoe UI',sans-serif" font-weight="800"
          font-size="56" letter-spacing="-3">GB</text>
  </svg>
</template>
