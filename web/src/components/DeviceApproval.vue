<script setup>
// DeviceApproval — веб-версия барьера подтверждения устройства для персонала.
// Поток совпадает с десктопом и опирается на существующие эндпоинты /connect/*:
//   request → админ выдаёт 6-значный код → verify. Студентам барьер не применяется.
import { ref, onUnmounted } from 'vue'
import { connectApi } from '@/api/endpoints'
import { getDeviceId } from '@/api/tokens'
import AppButton from '@/components/ui/AppButton.vue'

const emit = defineEmits(['approved'])

const phase = ref('idle') // idle | requested | verifying | error
const code = ref('')
const message = ref('')
const busy = ref(false)
let poll = null

async function requestAccess() {
  busy.value = true
  message.value = ''
  try {
    const { data } = await connectApi.request(getDeviceId(), navigator.userAgent.slice(0, 60))
    if (data.status === 'approved') return emit('approved')
    phase.value = 'requested'
    message.value = 'Запрос отправлен. Попросите администратора одобрить это устройство и продиктовать код.'
    startPolling()
  } catch (e) {
    phase.value = 'error'
    message.value = e.response?.data?.detail || 'Не удалось отправить запрос'
  } finally {
    busy.value = false
  }
}

// Пока ждём код — тихо опрашиваем статус: как только админ одобрит, поле кода активно.
function startPolling() {
  stopPolling()
  poll = setInterval(async () => {
    try {
      const { data } = await connectApi.status(getDeviceId())
      if (data.status === 'approved') { stopPolling(); emit('approved') }
    } catch { /* нет сети — попробуем в следующий раз */ }
  }, 4000)
}
function stopPolling() { if (poll) { clearInterval(poll); poll = null } }
onUnmounted(stopPolling)

async function verify() {
  if (!/^\d{6}$/.test(code.value)) { message.value = 'Код — 6 цифр'; return }
  busy.value = true
  message.value = ''
  try {
    await connectApi.verify(getDeviceId(), code.value)
    stopPolling()
    emit('approved')
  } catch (e) {
    message.value = e.response?.data?.detail || 'Неверный код'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="mt-4 rounded-md border border-border2 bg-card2 p-4 text-sm">
    <p class="font-semibold text-text">Подтверждение устройства</p>
    <p class="mt-1 text-text3">
      Для входа преподавателя/администратора это устройство должен одобрить администратор.
    </p>

    <AppButton v-if="phase === 'idle' || phase === 'error'" class="mt-3" size="sm" :disabled="busy" @click="requestAccess">
      Запросить подтверждение
    </AppButton>

    <div v-if="phase === 'requested'" class="mt-3 space-y-2">
      <input
        v-model="code"
        inputmode="numeric"
        maxlength="6"
        placeholder="Код из 6 цифр"
        class="h-11 w-full rounded-sm border border-border2 bg-card px-3 tracking-[0.4em] text-text outline-none focus:border-accent"
        @keyup.enter="verify"
      />
      <AppButton size="sm" :disabled="busy" @click="verify">Подтвердить код</AppButton>
    </div>

    <p v-if="message" class="mt-2 text-xs text-text3">{{ message }}</p>
  </div>
</template>
