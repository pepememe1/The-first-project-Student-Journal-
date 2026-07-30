<script setup>
// MyStatusPicker — §D7: мой статус ПОВЕРХ presence (online/оффлайн уже считает сервер сам).
// Компактная кнопка с цветной точкой в шапке списка чатов; клик открывает выбор:
// «Обычный» (сбросить), «Не беспокоить», «Готовлюсь/учусь», «Отошёл» — и, только у
// преподавателя, короткий текст статуса (виден другим в каталоге/карточке участника).
import { ref, computed, onMounted } from 'vue'
import { storeToRefs } from 'pinia'
import { ChevronDown } from '@lucide/vue'
import { useMessengerStore } from '@/stores/messenger'
import { useAuthStore } from '@/stores/auth'
import { STATUS_KINDS } from '@/config/status'

const m = useMessengerStore()
const auth = useAuthStore()
const { myStatus } = storeToRefs(m)
const isTeacher = computed(() => auth.role === 'teacher')

const open = ref(false)
const textDraft = ref('')

onMounted(async () => {
  await m.loadMyStatus()
  textDraft.value = myStatus.value.custom_text || ''
})

const current = computed(() => STATUS_KINDS.find(k => k.kind === myStatus.value.kind) || STATUS_KINDS[0])

async function pick(kind) {
  await m.setMyStatus(kind, isTeacher.value ? textDraft.value : '')
  if (kind !== 'dnd' && kind !== 'studying' && kind !== 'away') open.value = false
}
async function saveText() {
  await m.setMyStatus(myStatus.value.kind, textDraft.value)
  open.value = false
}
</script>

<template>
  <div class="relative">
    <button type="button" @click="open = !open"
            class="flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-text2 hover:bg-bg2">
      <span class="size-2.5 rounded-full" :style="{ background: current.color }" />
      {{ current.self }}
      <ChevronDown class="size-3.5" />
    </button>
    <div v-if="open" class="absolute left-0 top-full z-20 mt-1 w-56 rounded-lg border border-border2 bg-card p-1.5 shadow-card">
      <button v-for="k in STATUS_KINDS" :key="k.kind" type="button" @click="pick(k.kind)"
              class="flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-sm text-text hover:bg-bg2"
              :class="{ 'bg-accent-glow': myStatus.kind === k.kind }">
        <span class="size-2.5 shrink-0 rounded-full" :style="{ background: k.color }" />
        {{ k.self }}
      </button>
      <div v-if="isTeacher" class="mt-1 border-t border-border pt-1.5">
        <input v-model="textDraft" placeholder="Текст статуса (видят другие)" maxlength="80"
               @keydown.enter="saveText"
               class="w-full rounded-md border border-border2 bg-card2 px-2 py-1 text-xs text-text outline-none focus:border-accent" />
        <button type="button" @click="saveText"
                class="mt-1 w-full rounded-md bg-accent px-2 py-1 text-xs font-semibold text-white hover:bg-accent2">
          Сохранить текст
        </button>
      </div>
    </div>
    <div v-if="open" class="fixed inset-0 z-10" @click="open = false" />
  </div>
</template>
