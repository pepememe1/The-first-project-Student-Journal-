<script setup>
// VectorPage — чат с маскотом «Вектор» (порт vector/widget.py). Маскот РЕАГИРУЕТ:
// приветствие при открытии → «думает» во время запроса → эмоция по настроению ответа
// (радость/грусть/предупреждение) → возврат в покой. Все позы — из 30 спрайтов эмоций.
// Цифры считает СЕРВЕР (/web/vector/ask) из реальных данных — маскот не выдумывает.
import { ref, watch, onMounted, nextTick } from 'vue'
import { storeToRefs } from 'pinia'
import { Send, LayoutGrid } from '@lucide/vue'
import Mascot from '@/components/Mascot.vue'
import { useVectorStore } from '@/stores/vector'

// Чат живёт в общем store — ОДНА переписка с боковым доком (как в десктопе).
const vector = useVectorStore()
const { messages, input, state, sprite, label, cmds, tick } = storeToRefs(vector)
const scroller = ref(null)
const showQuick = ref(false)     // попап быстрых команд

async function scrollDown() {
  await nextTick()
  scroller.value?.scrollTo({ top: scroller.value.scrollHeight, behavior: 'smooth' })
}
watch(tick, scrollDown)                       // новое сообщение → прокрутка вниз
onMounted(() => { vector.greetSettle(); scrollDown() })

function send() { vector.send() }             // берёт текст из store.input (v-model)
function ask(q) { showQuick.value = false; vector.ask(q) }
</script>

<template>
  <!-- Вкладка «ИИ Помощник»: ОДИН крупный Вектор + чат. Мобайл — Вектор сверху, чат
       снизу; десктоп — Вектор слева, чат справа. Размеры маскота ФИКСИРОВАННЫЕ (rem) —
       так контейнер картинки не схлопывается в ноль. -->
  <div class="flex h-[calc(100dvh-8rem)] flex-col gap-3 sm:h-[calc(100dvh-9.5rem)] lg:h-[calc(100vh-11rem)] lg:flex-row lg:gap-6">
    <!-- Вектор -->
    <div class="flex shrink-0 flex-col items-center justify-center lg:w-[26rem]">
      <Mascot :sprite="sprite" class="h-72 w-64 sm:h-80 sm:w-72 lg:h-[32rem] lg:w-96" />
      <span class="mt-1 inline-flex items-center gap-2 rounded-full bg-accent-glow px-3 py-1 text-sm font-medium text-accent">
        <span class="size-1.5 rounded-full bg-accent" :class="state === 'thinking' ? 'animate-ping' : ''" />
        {{ label }}
      </span>
    </div>

    <!-- Чат -->
    <div class="flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg border border-border bg-card shadow-card">
      <div ref="scroller" class="flex-1 space-y-4 overflow-y-auto p-5">
        <div v-for="(m, i) in messages" :key="i" class="flex" :class="m.role === 'user' ? 'justify-end' : ''">
          <div class="max-w-[80%] rounded-lg px-4 py-2.5 text-sm"
               :class="m.role === 'user' ? 'bg-accent text-white' : 'bg-bg2 text-text'">
            {{ m.text }}
          </div>
        </div>
        <p v-if="state === 'thinking'" class="text-xs text-text2">Вектор думает…</p>
      </div>

      <!-- Ввод + кнопка «Быстрые команды» (попап, как в десктопе): нажал → список команд
           (те же иконки/подписи/вопросы) → тапнул → Вектор сразу отвечает. -->
      <div class="relative border-t border-border p-3">
        <transition name="pop">
          <div v-if="showQuick && cmds.length"
               class="absolute bottom-full left-3 right-3 mb-2 rounded-lg border border-border2 bg-card p-2 shadow-card">
            <p class="px-1 pb-1 text-xs font-semibold text-text3">Быстрые команды</p>
            <div class="flex flex-col gap-0.5">
              <button v-for="c in cmds" :key="c.label" type="button" @click="ask(c.q)"
                      class="flex items-center gap-2.5 rounded-md px-3 py-2 text-left text-sm text-text transition-colors hover:bg-accent-glow hover:text-accent">
                <component :is="c.icon" class="size-4 shrink-0 text-accent" />{{ c.label }}
              </button>
            </div>
          </div>
        </transition>

        <form class="flex items-center gap-2" @submit.prevent="send">
          <button type="button" @click="showQuick = !showQuick" aria-label="Быстрые команды"
                  class="grid size-11 shrink-0 place-items-center rounded-sm border transition-colors"
                  :class="showQuick ? 'border-accent bg-accent-glow text-accent' : 'border-border2 bg-card2 text-text2 hover:border-accent hover:text-accent'">
            <LayoutGrid class="size-5" />
          </button>
          <input v-model="input" placeholder="Спросите Вектора…" @focus="showQuick = false"
                 class="h-11 min-w-0 flex-1 rounded-sm border border-border2 bg-card2 px-3.5 text-text outline-none focus:border-accent focus:bg-card" />
          <button type="submit" aria-label="Отправить"
                  class="grid size-11 shrink-0 place-items-center rounded-sm bg-accent text-white transition-colors hover:bg-accent2 disabled:opacity-50"
                  :disabled="state === 'thinking' || !input.trim()">
            <Send class="size-5" />
          </button>
        </form>
      </div>
    </div>
  </div>
</template>

<style scoped>
.pop-enter-active, .pop-leave-active { transition: opacity 0.16s ease, transform 0.16s ease; }
.pop-enter-from, .pop-leave-to { opacity: 0; transform: translateY(6px); }
</style>
