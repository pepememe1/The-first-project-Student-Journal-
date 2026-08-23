<script setup>
// Skyrim: показывается ПОСЛЕ успешного входа, если до него было несколько неудачных
// попыток подряд. Пасхалка про момент «наконец зашёл», а не про сами ошибки.
//
// ⚠️ Реальное сообщение об ошибке она не подменяет и вход не задерживает — идёт
// отдельным слоем поверх уже открытого кабинета и уходит сама.
import { onMounted, onBeforeUnmount, ref } from 'vue'
const emit = defineEmits(['close'])
const on = ref(false)
const text = ref(false)
let timers = []

onMounted(() => {
  requestAnimationFrame(() => { on.value = true })
  timers.push(setTimeout(() => { text.value = true }, 900))
  timers.push(setTimeout(() => { on.value = false }, 6200))
  timers.push(setTimeout(() => emit('close'), 7000))
})
onBeforeUnmount(() => timers.forEach(clearTimeout))
</script>

<template>
  <!-- ⚠️ Слой ПЕРЕХВАТЫВАЕТ мышь (без pointer-events-none). Пока сцена идёт,
       кликнуть можно только по ней: промах по интерфейсу под ней уносил находку —
       страница уходила, а вместе с ней и пасхалка. Тот же приём, что у окна про
       cookie: выйти мимо кнопок нельзя. -->
  <div class="fixed inset-0 z-[92] bg-black transition-opacity duration-700"
       :style="{ opacity: on ? 1 : 0 }">
    <img src="/easter/img/skyrim-cart.webp" alt=""
         class="h-full w-full object-cover" />
    <!-- Текст поверх кадра, а не под ним: снизу у повозки самая тёмная часть,
         и подпись там читается без всякой подложки. -->
    <div class="absolute inset-x-0 bottom-[8%] text-center transition-opacity duration-700"
         :style="{ opacity: text ? 1 : 0 }">
      <p class="font-title text-lg" style="color:#e9e2d0;text-shadow:0 2px 14px #000">
        Эй, ты. Наконец-то ты очнулся.
      </p>
      <p class="mt-1.5 text-sm" style="color:#b9b09a;text-shadow:0 2px 10px #000">
        Ты спросонья перепутал пароль, так ведь?
      </p>
    </div>
  </div>
</template>
