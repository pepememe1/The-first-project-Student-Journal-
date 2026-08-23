<script setup>
// Dark Souls на выходе из аккаунта. Заменяет обычное прощание Вектора.
//
// ⚠️ АЧИВКУ ЗАКРЫВАЕТ НЕ ЭТА СЦЕНА, а `Settings.vue::onLogout` — ДО вызова `logout()`.
// Здесь стоял `easter.claim(...)`, и он не срабатывал никогда: к моменту показа токен
// уже стёрт, запрос уходил без авторизации и получал 401. Человек видел пасхалку, а
// ачивку не получал, причём молча.
// ⚠️ Не возвращать сюда вызов «для надёжности»: он снова будет уходить в пустоту и
// создавать видимость, что закрытие находки происходит здесь.
import { onMounted, ref } from 'vue'
const emit = defineEmits(['close'])
const veil = ref(false), band = ref(false), text = ref(false)

onMounted(async () => {
  const wait = (ms) => new Promise((r) => setTimeout(r, ms))
  veil.value = true
  await wait(400); band.value = true
  await wait(300); text.value = true
  await wait(2600); veil.value = band.value = text.value = false
  await wait(1700); emit('close')
})
</script>

<template>
  <!-- ⚠️ Слой ПЕРЕХВАТЫВАЕТ мышь (без pointer-events-none). Пока сцена идёт,
       кликнуть можно только по ней: промах по интерфейсу под ней уносил находку —
       страница уходила, а вместе с ней и пасхалка. Тот же приём, что у окна про
       cookie: выйти мимо кнопок нельзя. -->
  <div class="fixed inset-0 z-[94]">
    <div class="absolute inset-0 bg-black transition-opacity duration-1000"
         :style="{ opacity: veil ? 0.42 : 0 }"></div>
    <div class="absolute inset-x-0 top-1/2 grid h-[23%] -translate-y-1/2 place-items-center
                transition-opacity duration-1000"
         :style="{ background:'rgba(0,0,0,.55)', opacity: band ? 1 : 0 }">
      <p class="whitespace-nowrap transition-opacity duration-1000"
         :style="{ fontFamily:'\'Cormorant Garamond\', Georgia, serif',
                   fontSize:'clamp(20px,4.6vw,40px)', letterSpacing:'.24em',
                   color:'#d9c07a', textShadow:'0 0 22px rgba(217,192,122,.45)',
                   opacity: text ? 1 : 0 }">СЕССИЯ ЗАВЕРШЕНА</p>
      <!-- ⚠️ О НАГРАДЕ ГОВОРИМ ЗДЕСЬ, а не общим тостом. Тост живёт в сторе, а стор при
           выходе обнуляется — значит «достижение открыто» либо мелькнёт на долю секунды,
           либо всплывёт уже на экране входа у СЛЕДУЮЩЕГО человека. Именно это Влад и
           видел. Внутри сцены надпись живёт ровно столько, сколько сама сцена, и
           попадает в тот момент, к которому относится. -->
      <p class="mt-3 whitespace-nowrap transition-opacity duration-1000"
         :style="{ fontFamily: '\'Cormorant Garamond\', Georgia, serif',
                   fontSize: 'clamp(11px,1.7vw,15px)', letterSpacing: '.18em',
                   color: '#9a865a', opacity: text ? 0.85 : 0 }">ДОСТИЖЕНИЕ ОТКРЫТО</p>
    </div>
  </div>
</template>
