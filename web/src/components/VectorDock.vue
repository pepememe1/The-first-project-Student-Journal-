<script setup>
// VectorDock — постоянная боковая шторка Вектора (справа, десктоп). Порт десктопной
// компоновки vector/widget._AvatarChatOverlay: маскот лежит ФОНОМ во всю площадь, а
// переписка — полупрозрачным слоем ПОВЕРХ него (Вектор просвечивает между строк, но
// текст читаем). Переписка ОБЩАЯ со вкладкой «ИИ Помощник» (Pinia-store vector).
import { ref, watch, onMounted, nextTick } from 'vue'
import { storeToRefs } from 'pinia'
import { Send, LayoutGrid, PanelRightClose, Volume2, VolumeX } from '@lucide/vue'
import Mascot from '@/components/Mascot.vue'
import { useVectorStore } from '@/stores/vector'
import { useTtsStore } from '@/stores/tts'

const vector = useVectorStore()
const tts = useTtsStore()
const { messages, input, state, anim, label, cmds, tick, typingReveal } = storeToRefs(vector)
const { enabled: ttsEnabled, speaking } = storeToRefs(tts)
const scroller = ref(null)
const showQuick = ref(false)

// Печать ответа по символам — та же логика, что в VectorPage.vue (переписка и
// typingReveal общие через один store). Двойной клик по печатающемуся сообщению
// сразу показывает его целиком.
function displayText(i) {
  const tr = typingReveal.value
  return (tr.index === i && !tr.done) ? tr.text : messages.value[i].text
}
function isTyping(i) {
  return typingReveal.value.index === i && !typingReveal.value.done
}
function onMessageDblClick(i) {
  if (isTyping(i)) vector.skipTyping()
}

async function scrollDown() {
  await nextTick()
  scroller.value?.scrollTo({ top: scroller.value.scrollHeight, behavior: 'smooth' })
}
watch(tick, scrollDown)
onMounted(() => { vector.greetSettle(); scrollDown(); tts.refreshStatus() })

function send() { vector.send() }
function ask(q) { showQuick.value = false; vector.ask(q) }
</script>

<template>
  <aside class="relative flex h-full w-96 shrink-0 flex-col border-l border-border bg-card">
    <!-- Шапка: заголовок + индикатор состояния + скрыть панель -->
    <div class="flex h-11 shrink-0 items-center justify-between gap-2 border-b border-border px-3">
      <div class="flex min-w-0 items-center gap-2">
        <span class="size-2 shrink-0 rounded-full bg-accent" :class="state === 'thinking' ? 'animate-ping' : ''" />
        <span class="font-title text-sm font-bold text-text">Вектор</span>
        <span v-if="label" class="truncate text-[11px] text-text3">· {{ label }}</span>
      </div>
      <div class="flex shrink-0 items-center gap-0.5">
        <!-- Озвучка: вкл/выкл. Когда играет — иконка подсвечена. Клик по выключенной
             также гасит текущую речь (внутри setEnabled). -->
        <button type="button" @click="tts.setEnabled(!ttsEnabled)"
                :aria-label="ttsEnabled ? 'Выключить озвучку' : 'Включить озвучку'"
                :title="ttsEnabled ? 'Озвучка включена' : 'Озвучка выключена'"
                class="grid size-7 place-items-center rounded-md transition-colors hover:bg-bg2"
                :class="ttsEnabled ? (speaking ? 'text-accent' : 'text-text2 hover:text-text') : 'text-text3'">
          <component :is="ttsEnabled ? Volume2 : VolumeX" class="size-4" />
        </button>
        <button type="button" @click="vector.setCollapsed(true)" aria-label="Скрыть панель Вектора"
                title="Скрыть панель"
                class="grid size-7 place-items-center rounded-md text-text3 transition-colors hover:bg-bg2 hover:text-text">
          <PanelRightClose class="size-4" />
        </button>
      </div>
    </div>

    <!-- Маскот ФОНОМ (во всю площадь) + чат полупрозрачным слоем поверх -->
    <div class="relative min-h-0 flex-1 overflow-hidden">
      <div class="pointer-events-none absolute inset-0">
        <Mascot :anim="anim" class="h-full w-full" />
      </div>
      <!-- Чат: верхний край ~42% высоты (уровень туловища) → голова и плечи открыты;
           подложка полупрозрачная + лёгкое размытие фона, чтобы текст читался. -->
      <div ref="scroller"
           class="absolute inset-x-2 bottom-2 top-[42%] space-y-2 overflow-y-auto rounded-xl border border-border/60 bg-card/70 p-3 backdrop-blur-sm">
        <template v-for="(m, i) in messages" :key="i">
          <div v-if="m.role === 'user'" class="flex justify-end">
            <div class="max-w-[85%] rounded-lg bg-accent px-3 py-1.5 text-sm text-white">{{ m.text }}</div>
          </div>
          <p v-else class="text-sm leading-snug text-text" @dblclick="onMessageDblClick(i)"
             :title="isTyping(i) ? 'Двойной клик — показать целиком' : ''">
            <span class="font-semibold text-accent">Вектор:</span> {{ displayText(i) }}<span
              v-if="isTyping(i)" class="animate-pulse text-accent">▍</span>
          </p>
        </template>
        <p v-if="state === 'thinking'" class="text-xs text-text2">Вектор думает…</p>
      </div>
    </div>

    <!-- Ввод + быстрые команды -->
    <div class="relative shrink-0 border-t border-border p-2.5">
      <transition name="pop">
        <div v-if="showQuick && cmds.length"
             class="absolute bottom-full left-2.5 right-2.5 mb-2 rounded-lg border border-border2 bg-card p-2 shadow-card">
          <p class="px-1 pb-1 text-xs font-semibold text-text3">Быстрые команды</p>
          <div class="flex flex-col gap-0.5">
            <button v-for="c in cmds" :key="c.label" type="button" @click="ask(c.q)"
                    class="flex items-center gap-2.5 rounded-md px-3 py-2 text-left text-sm text-text transition-colors hover:bg-accent-glow hover:text-accent">
              <component :is="c.icon" class="size-4 shrink-0 text-accent" />{{ c.label }}
            </button>
          </div>
        </div>
      </transition>

      <form class="flex items-center gap-1.5" @submit.prevent="send">
        <button type="button" @click="showQuick = !showQuick" aria-label="Быстрые команды"
                class="grid size-10 shrink-0 place-items-center rounded-sm border transition-colors"
                :class="showQuick ? 'border-accent bg-accent-glow text-accent' : 'border-border2 bg-card2 text-text2 hover:border-accent hover:text-accent'">
          <LayoutGrid class="size-4" />
        </button>
        <input v-model="input" placeholder="Спросите Вектора…" @focus="showQuick = false"
               class="h-10 min-w-0 flex-1 rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent focus:bg-card" />
        <button type="submit" aria-label="Отправить"
                class="grid size-10 shrink-0 place-items-center rounded-sm bg-accent text-white transition-colors hover:bg-accent2 disabled:opacity-50"
                :disabled="state === 'thinking' || !input.trim()">
          <Send class="size-4" />
        </button>
      </form>
    </div>
  </aside>
</template>

<style scoped>
.pop-enter-active, .pop-leave-active { transition: opacity 0.16s ease, transform 0.16s ease; }
.pop-enter-from, .pop-leave-to { opacity: 0; transform: translateY(6px); }
</style>
