<script setup>
// VectorPage — вкладка «ИИ Помощник» (порт vector/widget.py). Компоновка как в
// десктопе (_AvatarChatOverlay): ОДИН крупный Вектор во всю площадь + переписка
// полупрозрачным слоем ПОВЕРХ него. Маскот РЕАГИРУЕТ: приветствие → «думает» →
// эмоция по настроению ответа → покой. Цифры считает СЕРВЕР (/web/vector/ask).
// Чат живёт в общем store — ОДНА переписка с боковым доком (как в десктопе).
import { ref, watch, onMounted, nextTick } from 'vue'
import { storeToRefs } from 'pinia'
import { Send, LayoutGrid } from '@lucide/vue'
import Mascot from '@/components/Mascot.vue'
import { useVectorStore } from '@/stores/vector'

const vector = useVectorStore()
const { messages, input, state, anim, label, cmds, tick } = storeToRefs(vector)
const scroller = ref(null)
const showQuick = ref(false)
// На телефоне при вводе (клавиатура открыта) прячем крупный маскот-фон и разворачиваем
// чат на всю высоту — так клавиатура закрывает пустое место, а не «красивый интерфейс».
const focused = ref(false)

async function scrollDown() {
  await nextTick()
  scroller.value?.scrollTo({ top: scroller.value.scrollHeight, behavior: 'smooth' })
}
watch(tick, scrollDown)
onMounted(() => { vector.greetSettle(); scrollDown() })

function send() { vector.send() }
function ask(q) { showQuick.value = false; vector.ask(q) }
</script>

<template>
  <!-- Одна карточка на всю высоту: шапка · (маскот ФОНОМ + чат поверх) · ввод -->
  <div class="relative flex h-[calc(100dvh-8rem)] flex-col overflow-hidden rounded-lg border border-border bg-card shadow-card sm:h-[calc(100dvh-9.5rem)] lg:h-[calc(100vh-11rem)]">
    <!-- Шапка -->
    <div class="flex h-12 shrink-0 items-center gap-2 border-b border-border px-4">
      <span class="size-2 shrink-0 rounded-full bg-accent" :class="state === 'thinking' ? 'animate-ping' : ''" />
      <span class="font-title text-base font-bold text-text">Вектор</span>
      <span v-if="label" class="truncate text-xs text-text3">· {{ label }}</span>
    </div>

    <!-- Маскот ФОНОМ (крупный, по центру) + чат полупрозрачным слоем поверх -->
    <div class="relative min-h-0 flex-1 overflow-hidden">
      <div class="pointer-events-none absolute inset-0 transition-opacity duration-300"
           :class="{ 'opacity-15 sm:opacity-100': focused }">
        <Mascot :anim="anim" class="h-full w-full" />
      </div>
      <!-- Чат: верхний край ~40% высоты (уровень туловища), по центру, ограничен по
           ширине; подложка полупрозрачная + размытие — текст читаем, Вектор просвечивает.
           На телефоне при вводе разворачивается почти на всю высоту (top-3). -->
      <div ref="scroller"
           class="absolute inset-x-4 bottom-4 mx-auto max-w-3xl space-y-3 overflow-y-auto rounded-xl border border-border/60 bg-card/70 p-4 backdrop-blur-sm transition-[top] duration-300 sm:inset-x-8"
           :class="focused ? 'top-3 sm:top-[40%]' : 'top-[40%]'">
        <template v-for="(m, i) in messages" :key="i">
          <div v-if="m.role === 'user'" class="flex justify-end">
            <div class="max-w-[80%] rounded-lg bg-accent px-4 py-2 text-sm text-white">{{ m.text }}</div>
          </div>
          <p v-else class="text-[15px] leading-relaxed text-text">
            <span class="font-semibold text-accent">Вектор:</span> {{ m.text }}
          </p>
        </template>
        <p v-if="state === 'thinking'" class="text-xs text-text2">Вектор думает…</p>
      </div>
    </div>

    <!-- Ввод + кнопка «Быстрые команды» (попап, как в десктопе) -->
    <div class="relative shrink-0 border-t border-border p-3">
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

      <form class="mx-auto flex max-w-3xl items-center gap-2" @submit.prevent="send">
        <button type="button" @click="showQuick = !showQuick" aria-label="Быстрые команды"
                class="grid size-11 shrink-0 place-items-center rounded-sm border transition-colors"
                :class="showQuick ? 'border-accent bg-accent-glow text-accent' : 'border-border2 bg-card2 text-text2 hover:border-accent hover:text-accent'">
          <LayoutGrid class="size-5" />
        </button>
        <input v-model="input" placeholder="Спросите Вектора…"
               @focus="showQuick = false; focused = true" @blur="focused = false"
               class="h-11 min-w-0 flex-1 rounded-sm border border-border2 bg-card2 px-3.5 text-text outline-none focus:border-accent focus:bg-card" />
        <button type="submit" aria-label="Отправить"
                class="grid size-11 shrink-0 place-items-center rounded-sm bg-accent text-white transition-colors hover:bg-accent2 disabled:opacity-50"
                :disabled="state === 'thinking' || !input.trim()">
          <Send class="size-5" />
        </button>
      </form>
    </div>
  </div>
</template>

<style scoped>
.pop-enter-active, .pop-leave-active { transition: opacity 0.16s ease, transform 0.16s ease; }
.pop-enter-from, .pop-leave-to { opacity: 0; transform: translateY(6px); }
</style>
