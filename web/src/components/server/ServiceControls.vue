<script setup>
// ServiceControls — запуск, остановка и перезапуск служб боевой машины.
//
// Кнопок ровно столько, сколько нужно, и ни одной больше: `systemctl` умеет
// останавливать что угодно, включая ssh, — а это означало бы сервер, до которого больше
// нечем достучаться. Поэтому список служб и действий задан на сервере белым списком
// (SERVICES в ui/server_admin.py), а не собирается из того, что пришло со страницы.
//
// Остановка кладёт сайт для всего колледжа, поэтому она требует подтверждения — сервер
// отвечает 409 «confirm-required», пока человек не подтвердил осознанно.
import { ref } from 'vue'
import { Play, Square, RotateCw, TriangleAlert } from '@lucide/vue'
import { deskServerApi } from '@/api/endpoints'
import AppButton from '@/components/ui/AppButton.vue'
import Badge from '@/components/ui/Badge.vue'

const props = defineProps({
  serverId: { type: String, required: true },
  // { gradebook: 'active', caddy: 'active' } — состояние с последнего опроса
  services: { type: Object, default: () => ({}) },
})
const emit = defineEmits(['changed'])

const LABELS = {
  gradebook: 'Сервер журнала',
  caddy: 'Веб-сервер и сертификаты',
}

const busy = ref('')
const message = ref('')
const failed = ref(false)
const pending = ref(null)     // { name, action } — ждёт подтверждения остановки

async function act(name, action, confirm = false) {
  busy.value = `${name}:${action}`
  message.value = ''
  failed.value = false
  try {
    const { data } = await deskServerApi.service(props.serverId, name, action, confirm)
    failed.value = !data.ok
    message.value = data.hint || (data.ok ? `Готово: ${LABELS[name]} — ${data.state}` : '')
    pending.value = null
    emit('changed')
  } catch (e) {
    if (e?.response?.status === 409) {
      pending.value = { name, action }
    } else {
      failed.value = true
      message.value = e?.response?.data?.detail || 'Не удалось выполнить'
    }
  } finally {
    busy.value = ''
  }
}
</script>

<template>
  <div class="flex flex-col gap-3">
    <div v-for="(label, name) in LABELS" :key="name"
         class="flex flex-wrap items-center gap-3 rounded-lg border border-border bg-card2 px-3 py-2.5">
      <span class="min-w-0 flex-1">
        <span class="block text-sm font-semibold text-text">{{ label }}</span>
        <span class="block text-tiny text-text3">{{ name }}</span>
      </span>
      <Badge :variant="services[name] === 'active' ? 'green' : 'red'">
        {{ services[name] || 'неизвестно' }}
      </Badge>
      <span class="flex gap-1.5">
        <AppButton variant="ghost" :disabled="!!busy" @click="act(name, 'restart')">
          <RotateCw class="mr-1 inline size-4" />Перезапустить
        </AppButton>
        <AppButton v-if="services[name] === 'active'" variant="ghost" :disabled="!!busy"
                   @click="act(name, 'stop')">
          <Square class="mr-1 inline size-4" />Остановить
        </AppButton>
        <AppButton v-else variant="ghost" :disabled="!!busy" @click="act(name, 'start')">
          <Play class="mr-1 inline size-4" />Запустить
        </AppButton>
      </span>
    </div>

    <div v-if="pending"
         class="flex flex-col gap-2 rounded-lg border border-red/50 bg-card2 p-3">
      <p class="flex items-start gap-2 text-sm text-text2">
        <TriangleAlert class="mt-0.5 size-4 shrink-0 text-red" />
        <span>Остановка «{{ LABELS[pending.name] }}» сделает сайт и приложение
              недоступными для всего колледжа, пока службу не запустят обратно.</span>
      </p>
      <div class="flex gap-2">
        <AppButton variant="red" :disabled="!!busy"
                   @click="act(pending.name, pending.action, true)">Всё равно остановить</AppButton>
        <AppButton variant="ghost" @click="pending = null">Отмена</AppButton>
      </div>
    </div>

    <p v-if="message" class="text-sm" :class="failed ? 'text-red' : 'text-text3'">{{ message }}</p>
  </div>
</template>
