<script setup>
// GbShape — фигура плитки ответа в викторине (треугольник, ромб, круг, квадрат, звезда,
// пятиугольник). Раньше это были текстовые символы: «⬟» в шрифтах Windows нет вовсе, и
// одна плитка из шести выходила квадратиком-заглушкой. Красится currentColor.
import { computed } from 'vue'

const props = defineProps({ index: { type: Number, required: true } })

const SHAPES = [
  'M12 3 22 20H2Z',
  'M12 2 22 12 12 22 2 12Z',
  'M12 2.5a9.5 9.5 0 1 0 0 19 9.5 9.5 0 0 0 0-19Z',
  'M3.5 3.5h17v17h-17Z',
  'M12 2l2.9 6.2 6.6.7-5 4.5 1.5 6.6L12 16.6 6 20l1.5-6.6-5-4.5 6.6-.7Z',
  'M12 2.5 21.5 9.4 17.9 20.5H6.1L2.5 9.4Z',
]
const d = computed(() => SHAPES[props.index % SHAPES.length])
</script>

<template>
  <svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true" focusable="false">
    <path :d="d" fill="currentColor" />
  </svg>
</template>
