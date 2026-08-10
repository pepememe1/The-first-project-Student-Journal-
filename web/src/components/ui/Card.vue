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
    <!-- ⚠️ Шапка ПЕРЕНОСИТСЯ и УМЕЕТ СЖИМАТЬСЯ — это не косметика, а починка реального
         бага «в журнале на телефоне ничего не влазит». Раньше здесь стояло
         `flex items-center justify-between` БЕЗ `min-w-0` у блока заголовка: у flex-детей
         минимальный размер равен размеру содержимого, поэтому длинное название предмета
         («Иностранный язык в профессиональной коммуникации») не сжималось, а РАСПИРАЛО
         строку — вместе с бейджами часов и среднего балла шапка требовала ~490 px при
         360 px экрана, и вбок уезжала вся страница. `min-w-0` разрешает блоку сжаться,
         `flex-wrap` — перенести бейджи под заголовок, когда рядом они уже не помещаются.
         Заголовок при этом ПЕРЕНОСИТСЯ ПО СЛОВАМ, а не обрезается: обрезанное название
         предмета не отличить от другого с тем же началом. -->
    <header v-if="title || $slots.header"
            class="flex flex-wrap items-center justify-between gap-x-3 gap-y-2 border-b border-border px-4 py-3 sm:px-5 sm:py-4">
      <div class="min-w-0">
        <h3 class="font-title text-base font-bold text-text sm:text-lg">{{ title }}</h3>
        <p v-if="subtitle" class="mt-0.5 text-xs text-text3">{{ subtitle }}</p>
      </div>
      <!-- Обёртка нужна, чтобы бейджи переносились ГРУППОЙ, а не поодиночке -->
      <div v-if="$slots.header" class="flex flex-wrap items-center gap-2">
        <slot name="header" />
      </div>
    </header>
    <!-- Отступы на телефоне уже: 40 px из 360 съедала одна только рамка карточки -->
    <div :class="pad ? 'p-4 sm:p-5' : ''">
      <slot />
    </div>
  </section>
</template>
