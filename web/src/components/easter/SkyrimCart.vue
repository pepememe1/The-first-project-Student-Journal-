<script setup>
// Skyrim: показывается ПОСЛЕ успешного входа, когда до него было несколько неудачных.
// Реальное сообщение об ошибке не подменяет и вход не задерживает — идёт поверх.
//
// ⚠️ Кадр повозки — заглушка вёрсткой, пока Арина не отдаст рисунок. Показывать чужой
// кадр из игры в продукте нельзя (docs/PLAN-EASTER-EGGS.md §В7).
import { onMounted, ref } from 'vue'
const emit = defineEmits(['close'])
const on = ref(false)
onMounted(() => { on.value = true; setTimeout(() => emit('close'), 5200) })
</script>

<template>
  <div class="fixed inset-0 z-[92] grid place-items-center bg-black transition-opacity duration-700"
       :class="on ? 'opacity-100' : 'opacity-0'">
    <div class="w-[min(78vw,560px)] text-center">
      <div class="grid h-40 place-items-center rounded-md font-mono text-[11px]"
           style="background:linear-gradient(#1b2430,#0c1116);color:#3c4a58">
        [ заглушка: кадр повозки ]
      </div>
      <p class="mt-4 font-title text-lg" style="color:#e9e2d0">Эй, ты. Наконец-то ты очнулся.</p>
      <p class="mt-1.5 text-sm" style="color:#9a9382">Ты спросонья перепутал пароль, так ведь?</p>
    </div>
  </div>
</template>
