<script setup>
// PageReveal — страница или блок, который ждёт данные, появляется одним кадром (28.10.2026).
//
// Раньше страницы рисовали ответы по мере прихода: карточки вставали одна над другой и
// толкали уже показанное (замер на стенде: журнал родителя сдвигался на 0.22, главная
// студента — на 0.03). Здесь три состояния:
//   • ждём меньше 150 мс — пусто: быстрый ответ показывает контент сразу, без мелькания;
//   • ждём дольше — слот #skeleton (заглушка той же формы, components/ui/Skeleton.vue);
//   • готово — контент целиком, мягким проявлением .gb-reveal (style.css).
// Данные страница грузит сама и одним пакетом (Promise.allSettled), сюда отдаёт только
// флаг ожидания.
import { toRef } from 'vue'
import { useDelayedFlag } from '@/composables/useDelayedFlag'

const props = defineProps({
  loading: { type: Boolean, required: true },
})
const showSkeleton = useDelayedFlag(toRef(props, 'loading'))
</script>

<template>
  <div v-if="loading" aria-busy="true">
    <slot v-if="showSkeleton" name="skeleton" />
  </div>
  <div v-else class="gb-reveal">
    <slot />
  </div>
</template>
