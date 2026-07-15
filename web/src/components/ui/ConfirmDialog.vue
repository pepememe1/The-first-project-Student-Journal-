<script setup>
// ConfirmDialog — единая модалка подтверждения/ввода (замена confirm()/prompt()).
// Управляется синглтоном useConfirm; монтируется один раз в App.vue.
import { ref, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'
import { dialogState, settleDialog } from '@/composables/useConfirm'
import AppButton from '@/components/ui/AppButton.vue'

const inputEl = ref(null)

function onOk() {
  settleDialog(dialogState.mode === 'prompt' ? dialogState.value : true)
}
function onCancel() {
  settleDialog(dialogState.mode === 'prompt' ? null : false)
}

// Фокус в поле ввода при открытии prompt; Esc — отмена.
watch(
  () => dialogState.open,
  async (open) => {
    if (open && dialogState.mode === 'prompt') {
      await nextTick()
      inputEl.value?.focus()
      inputEl.value?.select()
    }
  }
)
function onKey(e) {
  if (dialogState.open && e.key === 'Escape') onCancel()
}
onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <div
    v-if="dialogState.open"
    class="fixed inset-0 z-[100] flex items-center justify-center bg-black/40 p-4"
    @click.self="onCancel"
  >
    <div class="w-full max-w-sm rounded-lg border border-border bg-card p-5 shadow-card">
      <h3 v-if="dialogState.title" class="mb-2 font-title text-lg font-bold text-text">
        {{ dialogState.title }}
      </h3>
      <p v-if="dialogState.message" class="whitespace-pre-line text-sm text-text2">
        {{ dialogState.message }}
      </p>
      <input
        v-if="dialogState.mode === 'prompt'"
        ref="inputEl"
        v-model="dialogState.value"
        :placeholder="dialogState.placeholder"
        class="mt-3 h-10 w-full rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent"
        @keyup.enter="onOk"
      />
      <div class="mt-5 flex justify-end gap-2">
        <AppButton variant="ghost" size="sm" @click="onCancel">{{ dialogState.cancelText }}</AppButton>
        <AppButton :variant="dialogState.danger ? 'red' : 'green'" size="sm" @click="onOk">
          {{ dialogState.okText }}
        </AppButton>
      </div>
    </div>
  </div>
</template>
