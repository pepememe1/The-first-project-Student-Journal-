<script setup>
// ToggleRow — строка «подпись + пояснение + переключатель».
//
// Выделено в компонент, потому что таких строк в настройках стало много (категории
// уведомлений, голосовой ввод, озвучка), а разметка переключателя — это восемь
// классов Tailwind, которые при копировании разъезжаются: у одной строки отступ
// другой, у второй кружок не доезжает. Здесь она одна на всех.
//
// Кнопка, а не <input type="checkbox">: нажимать нужно по всей строке, а не по
// маленькому квадратику — на телефоне это разница между «попал» и «не попал».
defineProps({
  label: { type: String, required: true },
  hint: { type: String, default: '' },
  modelValue: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue'])
</script>

<template>
  <button type="button" :disabled="disabled"
          role="switch" :aria-checked="modelValue" :aria-label="label"
          class="flex w-full items-center gap-3 rounded-lg border border-border bg-card2 px-3 py-2.5 text-left transition-colors hover:border-accent disabled:cursor-not-allowed disabled:opacity-50"
          @click="emit('update:modelValue', !modelValue)">
    <span class="min-w-0 flex-1">
      <span class="block text-sm font-semibold text-text">{{ label }}</span>
      <span v-if="hint" class="block text-xs text-text3">{{ hint }}</span>
    </span>
    <span class="relative h-6 w-11 shrink-0 rounded-full transition-colors"
          :class="modelValue ? 'bg-accent' : 'bg-border2'">
      <span class="absolute top-0.5 size-5 rounded-full bg-white transition-all"
            :class="modelValue ? 'left-[22px]' : 'left-0.5'" />
    </span>
  </button>
</template>
