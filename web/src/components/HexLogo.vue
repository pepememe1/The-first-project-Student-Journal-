<script setup>
// HexLogo — логотип-шестиугольник «GB» (порт ui_components.HexLogoWidget).
defineProps({ size: { type: Number, default: 60 } })
</script>

<template>
  <svg :width="size" :height="size" viewBox="0 0 60 60" xmlns="http://www.w3.org/2000/svg">
    <!-- внешний шестиугольник -->
    <polygon points="30,2.4 53.9,16.2 53.9,43.8 30,57.6 6.1,43.8 6.1,16.2"
             fill="rgba(20,124,139,0.04)" stroke="var(--gb-accent)" stroke-width="1.5" />
    <!-- внутренний шестиугольник -->
    <polygon points="30,12.3 47.3,22.1 47.3,41.9 30,51.7 12.7,41.9 12.7,22.1"
             fill="rgba(20,124,139,0.07)" stroke="rgba(20,124,139,0.24)" stroke-width="1" />
    <text x="30" y="30" text-anchor="middle" dominant-baseline="central"
          font-family="'Syne','Segoe UI',sans-serif" font-weight="800"
          :font-size="size * 0.24" fill="var(--gb-accent)">GB</text>
  </svg>
</template>
