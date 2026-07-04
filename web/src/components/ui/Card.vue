<script setup>
// Card — базовая карточка (порт QFrame#card из styles.py): белая поверхность,
// тихая граница, мягкая тень, крупное скругление.
defineProps({
  title: { type: String, default: '' },
  subtitle: { type: String, default: '' },
  pad: { type: Boolean, default: true },
})
</script>

<template>
  <section class="rounded-lg border border-border bg-card shadow-card">
    <header v-if="title || $slots.header" class="flex items-center justify-between gap-3 border-b border-border px-5 py-4">
      <div>
        <h3 class="font-title text-lg font-bold text-text">{{ title }}</h3>
        <p v-if="subtitle" class="mt-0.5 text-xs text-text3">{{ subtitle }}</p>
      </div>
      <slot name="header" />
    </header>
    <div :class="pad ? 'p-5' : ''">
      <slot />
    </div>
  </section>
</template>
