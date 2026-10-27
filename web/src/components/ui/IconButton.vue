<script setup>
// IconButton — кнопка-значок без текста, одна на всё приложение: «изменить», «удалить»,
// «часы», «пригласить» в строках таблиц и окнах. До 27.10.2026 такие кнопки были
// разного размера (11×20 px в «Предметах», 32×32 в «Студентах»), и опасное действие
// не отличалось цветом от безобидного. Размер: 36 px с мышью, 44 px под палец
// (pointer-coarse); подпись `label` — и подсказка при наведении, и текст для диктора.
import GbIcon from '@/components/ui/GbIcon.vue'

defineProps({
  icon: { type: String, required: true },
  label: { type: String, required: true },
  // neutral — просто действие; danger — необратимое (наведение красит красным)
  tone: { type: String, default: 'neutral' },
  disabled: { type: Boolean, default: false },
})
</script>

<template>
  <button type="button" :title="label" :aria-label="label" :disabled="disabled"
          class="inline-grid size-9 shrink-0 place-items-center rounded-md text-text3 transition
                 active:scale-[0.94] disabled:pointer-events-none disabled:opacity-40 pointer-coarse:size-11"
          :class="tone === 'danger' ? 'hover:bg-red/10 hover:text-red focus-visible:text-red'
                                    : 'hover:bg-accent-glow hover:text-accent'">
    <GbIcon :name="icon" class="size-4" />
  </button>
</template>
