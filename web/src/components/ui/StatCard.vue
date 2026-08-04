<script setup>
// StatCard — карточка-метрика (порт stat_card из widgets.py): крупное число + подпись.
defineProps({
  label: { type: String, required: true },
  value: { type: [String, Number], default: '—' },
  hint: { type: String, default: '' },
  icon: { type: [Object, Function], default: null },
  accent: { type: Boolean, default: false },
})
</script>

<template>
  <!-- Отступы и кегль числа УМЕНЬШЕНЫ на телефоне: карточки стоят сеткой 2×2, и в
       «настольном» размере четвёрка метрик занимала пол-экрана — до собственно данных
       приходилось прокручивать (живой отзыв 3.6). На sm+ размеры прежние. -->
  <div class="rounded-lg border border-border bg-card p-3.5 shadow-card sm:p-5">
    <div class="flex items-start justify-between">
      <p class="text-[10px] font-medium uppercase tracking-wide text-text2">{{ label }}</p>
      <component :is="icon" v-if="icon" class="size-5" :class="accent ? 'text-accent' : 'text-text2'" />
    </div>
    <p class="mt-1.5 font-title text-2xl font-extrabold leading-none sm:mt-2 sm:text-[28px]"
       :class="accent ? 'text-accent' : 'text-text'">
      {{ value }}
    </p>
    <p v-if="hint" class="mt-1.5 text-xs text-text3">{{ hint }}</p>
  </div>
</template>
