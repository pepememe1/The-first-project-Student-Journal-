<script setup>
// Avatar — круглая аватарка: показывает картинку (prefs.avatar) либо инициалы по ФИО.
// Единый вид во всех местах (список чатов, карточка, каталог людей, модерация).
import { computed } from 'vue'

const props = defineProps({
  src: { type: String, default: '' },
  name: { type: String, default: '' },
  size: { type: Number, default: 40 },
  online: { type: Boolean, default: false },
})

const initials = computed(() => {
  const p = (props.name || '').trim().split(/\s+/)
  return ((p[0]?.[0] || '') + (p[1]?.[0] || '')).toUpperCase() || '?'
})
</script>

<template>
  <div class="relative shrink-0" :style="{ width: size + 'px', height: size + 'px' }">
    <div class="size-full overflow-hidden rounded-full bg-accent">
      <img v-if="src" :src="src" alt="" class="size-full object-cover" />
      <span v-else class="grid size-full place-items-center font-bold text-white"
            :style="{ fontSize: Math.round(size * 0.4) + 'px' }">{{ initials }}</span>
    </div>
    <span v-if="online" title="в сети"
          class="absolute bottom-0 right-0 size-3 rounded-full border-2 border-card" style="background:#2e9e5b"></span>
  </div>
</template>
