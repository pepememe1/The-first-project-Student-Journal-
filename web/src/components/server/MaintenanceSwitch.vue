<script setup>
// Мягкий рубильник технических работ (server/app/maintenance.py). Включён — всех, кроме
// администратора, сайт переводит на страницу работ, а админу остаются «Сервер», приманки,
// журнал и сессии. Жёсткий рубильник (весь сайт, вместе с админкой) — на машине:
// deploy/maintenance/gb_maintenance.sh. Страница у обоих одна.
import { ref, onMounted } from 'vue'
import { api } from '@/api/client'
import Card from '@/components/ui/Card.vue'
import AppButton from '@/components/ui/AppButton.vue'
import { useLocaleStore } from '@/stores/locale'
import { useMaintenanceStore } from '@/stores/maintenance'
import { useConfirm } from '@/composables/useConfirm'
import { useToast } from '@/composables/useToast'
import { formatCollege } from '@/utils/collegeTime'

const locale = useLocaleStore()
const maint = useMaintenanceStore()
const { confirm } = useConfirm()
const toast = useToast()
const state = ref({ on: false })
const text = ref('')
const busy = ref(false)

async function load() {
  try { state.value = (await api.get('/admin/maintenance')).data || { on: false } } catch { /* */ }
}
onMounted(load)

async function toggle() {
  const next = !state.value.on
  if (next && !(await confirm({
    title: locale.t('maintenance.confirmOn', 'Включить технические работы? Сайт закроется для всех, кроме администраторов.'),
    okText: locale.t('maintenance.turnOn', 'Включить работы'), danger: true,
  }))) return
  busy.value = true
  try {
    state.value = await maint.setOn(next, text.value)
    toast.success(next ? locale.t('maintenance.isOn', 'Технические работы включены')
                       : locale.t('maintenance.isOff', 'Сайт снова открыт для всех'))
  } catch {
    toast.error(locale.t('maintenance.failed', 'Не получилось переключить — проверьте связь с сервером'))
  } finally { busy.value = false }
}
</script>

<template>
  <Card :title="locale.t('maintenance.title', 'Технические работы')"
        :subtitle="locale.t('maintenance.subtitle', 'Сайт показывает всем страницу с Вектором в каске, админка остаётся вам')" pad>
    <div class="flex flex-col gap-3 sm:flex-row sm:items-center">
      <div class="flex min-w-0 flex-1 items-center gap-3">
        <span class="size-3 shrink-0 rounded-full" :class="state.on ? 'bg-orange animate-pulse' : 'bg-green'" />
        <div class="min-w-0 text-sm">
          <div class="font-semibold text-text">
            {{ state.on ? locale.t('maintenance.stateOn', 'Идут работы — сайт закрыт для пользователей')
                        : locale.t('maintenance.stateOff', 'Сайт работает как обычно') }}
          </div>
          <div v-if="state.on && state.since" class="text-text3">
            {{ locale.t('maintenance.since', { when: formatCollege(new Date(state.since * 1000), locale.active, { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }), who: state.by || '—' }) }}
          </div>
        </div>
      </div>
      <AppButton :variant="state.on ? 'primary' : 'red'" :disabled="busy" @click="toggle">
        {{ state.on ? locale.t('maintenance.turnOff', 'Выключить работы') : locale.t('maintenance.turnOn', 'Включить работы') }}
      </AppButton>
    </div>
    <label v-if="!state.on" class="mt-3 block text-sm text-text3">
      {{ locale.t('maintenance.messageLabel', 'Что сказать людям (необязательно)') }}
      <input v-model="text" maxlength="300" type="text"
             :placeholder="locale.t('maintenance.messagePlaceholder', 'Например: обновляем журнал, вернёмся к 14:00')"
             class="mt-1 w-full rounded-lg border border-border bg-bg px-3 py-2 text-text outline-none focus:border-accent" />
    </label>
    <p class="mt-3 text-xs text-text3">
      {{ locale.t('maintenance.hint', 'Во время работ вам доступны «Сервер», «Приманки», «Журнал действий» и «Сессии». Если само приложение лежит — жёсткий рубильник на машине: gb_maintenance.sh on.') }}
    </p>
  </Card>
</template>
