<script setup>
// FarewellOverlay — Вектор машет на прощание при выходе из аккаунта.
//
// Зачем: сессия начиналась приветствием, а обрывалась резко — щелчок «Выйти» и сразу
// форма входа. По правилу пика и конца запоминаются начало и ФИНАЛ, и пустой финал
// сводил на нет всё впечатление от начала. Здесь закрывается та же рамка, что открывает
// вход.
//
// Нового арта не потребовалось: переиспользуем анимацию `greeting` (Вектор машет) —
// жест прощания и приветствия у него один и тот же, как у человека.
import Mascot from '@/components/Mascot.vue'

defineProps({ name: { type: String, default: '' } })
</script>

<template>
  <!-- Поверх всего, клики не ловим: оверлей живёт секунду и сам исчезает. -->
  <div class="pointer-events-none fixed inset-0 z-[100] grid place-items-center"
       style="background: var(--gb-overlay)">
    <div class="flex flex-col items-center gap-2">
      <Mascot anim="greeting" class="h-64 w-48" />
      <p class="font-title text-lg font-bold text-text">
        {{ name ? `До встречи, ${name}!` : 'До встречи!' }}
      </p>
      <p class="text-xs text-text3">Вектор будет ждать</p>
    </div>
  </div>
</template>
