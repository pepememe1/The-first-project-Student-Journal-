<script setup>
// GbIcon — значок по смыслу действия из общего словаря (config/icons.js). Размер и цвет
// задаёт класс вызывающего, как у значков lucide: <GbIcon name="delete" class="size-4" />.
// Значок декоративный: подпись для диктора несёт кнопка (aria-label или текст).
import { computed } from 'vue'
import { ICONS } from '@/config/icons.js'

const props = defineProps({ name: { type: String, required: true } })
const icon = computed(() => ICONS[props.name] || ICONS.help)
</script>

<template>
  <component :is="icon" aria-hidden="true" focusable="false" />
</template>
