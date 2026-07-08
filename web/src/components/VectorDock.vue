<script setup>
// VectorDock — постоянная боковая панель Вектора (справа, десктоп), как док в десктопном
// приложении. Аватар + чат + ввод. Переписка ОБЩАЯ со вкладкой «ИИ Помощник» (Pinia-store
// vector). Показывается на всех страницах, кроме самой вкладки ИИ (см. AppShell).
import { ref, watch, onMounted, nextTick } from 'vue'
import { storeToRefs } from 'pinia'
import { Send, LayoutGrid, PanelRightClose } from '@lucide/vue'
import Mascot from '@/components/Mascot.vue'
import { useVectorStore } from '@/stores/vector'

const vector = useVectorStore()
const { messages, input, state, sprite, label, cmds, tick } = storeToRefs(vector)
const scroller = ref(null)
const showQuick = ref(false)

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
  <aside class="relative flex h-full w-96 shrink-0 flex-col border-l border-border bg-card">
    <!-- Кнопка «скрыть панель» (в углу) -->
    <button type="button" @click="vector.setCollapsed(true)" aria-label="Скрыть панель Вектора"
            title="Скрыть панель"
            class="absolute right-2 top-2 z-10 grid size-7 place-items-center rounded-md text-text3 transition-colors hover:bg-bg2 hover:text-text">
      <PanelRightClose class="size-4" />
    </button>

    <!-- Аватар Вектора сверху — крупный, чтобы был заметен -->
    <div class="flex shrink-0 flex-col items-center border-b border-border pb-2 pt-3">
      <Mascot :sprite="sprite" class="h-80 w-72" />
      <span class="inline-flex items-center gap-2 rounded-full bg-accent-glow px-3 py-1 text-xs font-medium text-accent">
        <span class="size-1.5 rounded-full bg-accent" :class="state === 'thinking' ? 'animate-ping' : ''" />
        {{ label }}
      </span>
    </div>

    <!-- Чат -->
    <div ref="scroller" class="flex-1 space-y-3 overflow-y-auto p-3">
      <div v-for="(m, i) in messages" :key="i" class="flex" :class="m.role === 'user' ? 'justify-end' : ''">
        <div class="max-w-[85%] rounded-lg px-3 py-2 text-sm"
             :class="m.role === 'user' ? 'bg-accent text-white' : 'bg-bg2 text-text'">
          {{ m.text }}
        </div>
      </div>
      <p v-if="state === 'thinking'" class="text-xs text-text2">Вектор думает…</p>
    </div>

    <!-- Ввод + быстрые команды -->
    <div class="relative border-t border-border p-2.5">
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
