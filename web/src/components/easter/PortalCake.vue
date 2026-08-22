<script setup>
// Portal: день рождения. Не по шансу — по совпадению дня и месяца (год админ не вводит).
//
// Рисунки Арины: Вектор с тортом (чёрный фон вырезан по яркости — жёсткое сравнение
// «строго чёрный» оставляло бы тёмную кайму по мягкому краю) и вторая сцена «ТОРТ ЭТО
// ЛОЖЬ», которая показывается после того, как свечу задули.
//
// ⚠️ Область клика по свече поставлена ПО СВЕЧЕ, с запасом: автоопределение огонька по
// яркости упорно цепляло белые горошины на колпаке, а промахиваться по пиксельному
// огоньку человеку не должно быть обидно.
import { ref } from 'vue'
import { useEasterStore } from '@/stores/easterEggs'
const emit = defineEmits(['close'])
const easter = useEasterStore()

const done = ref(false)

async function blow() {
  if (done.value) return
  done.value = true
  setTimeout(() => { easter.claim('portal_cake') }, 1200)
}
</script>

<template>
  <div class="fixed inset-0 z-[93] grid place-items-center p-4" style="background:var(--gb-overlay)"
       @click.self="emit('close')">

    <!-- До: поздравление. Свечу можно задуть — и тогда всё меняется. -->
    <div v-if="!done" class="flex flex-col items-center gap-3">
      <div class="relative">
        <img src="/easter/img/cake-vector.webp" alt=""
             class="max-h-[62vh] w-auto drop-shadow-2xl" />
        <button type="button" @click="blow" aria-label="Задуть свечу"
                class="absolute left-[36%] top-[26%] h-[14%] w-[18%] cursor-pointer rounded-full
                       border-0 bg-transparent outline-offset-4"></button>
      </div>
      <p class="font-title text-lg text-text">С днём рождения!</p>
      <button type="button" @click="emit('close')"
              class="rounded-lg bg-accent px-6 py-2 text-sm font-semibold text-white hover:brightness-110">
        ОК
      </button>
    </div>

    <!-- После: торт остался, Вектора нет. -->
    <div v-else class="flex flex-col items-center gap-3">
      <img src="/easter/img/cake-lie.webp" alt="Торт — это ложь"
           class="max-h-[74vh] w-auto rounded-lg shadow-2xl" />
      <button type="button" @click="emit('close')" class="text-xs text-text3 hover:text-text">
        закрыть
      </button>
    </div>
  </div>
</template>
