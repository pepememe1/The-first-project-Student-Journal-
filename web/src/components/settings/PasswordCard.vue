<script setup>
/**
 * PasswordCard.vue — смена СВОЕГО пароля (4.0).
 *
 * ⚠️ Зачем появилась. Колледж раздаёт стартовые пароли на бумаге («Выкатить данные
 * групп»), а самообслуживание на форме входа выключено. Без этой карточки студент не мог
 * сменить выданный пароль вообще — и выданный колледжем оставался бы видимым
 * администратору вечно.
 *
 * После смены приходит уведомление «пароль изменён» (вкладка «Уведомления», пуш и письмо
 * на подтверждённую почту). Остальные сессии НЕ закрываются: если пароль сменил не
 * владелец, владельцу нужна живая сессия, чтобы нажать «Выйти из всех сессий».
 */
import { ref, computed } from 'vue'
import { accountApi } from '@/api/endpoints'
import AppButton from '@/components/ui/AppButton.vue'
import { useToast } from '@/composables/useToast'
import { useLocaleStore } from '@/stores/locale'

const loc = useLocaleStore()
const toast = useToast()
const current = ref('')
const next = ref('')
const repeat = ref('')
const code = ref('')
const needCode = ref(false)       //сервер потребовал второй фактор (401 + X-Gb-Reason)
const busy = ref(false)
const error = ref('')
const show = ref(false)

const MIN = 8
const canSave = computed(() => current.value && next.value.length >= MIN
  && next.value === repeat.value && !busy.value)
const mismatch = computed(() => repeat.value && next.value !== repeat.value)

async function save() {
  if (!canSave.value) return
  busy.value = true
  error.value = ''
  try {
    await accountApi.changePassword(current.value, next.value, code.value)
    current.value = next.value = repeat.value = code.value = ''
    needCode.value = false
    toast.success(loc.t('account.passwordChanged', 'Пароль изменён'))
  } catch (e) {
    if (e?.response?.headers?.['x-gb-reason'] === 'mfa_required') needCode.value = true
    error.value = e?.response?.data?.detail || loc.t('account.passwordFailed', 'Не удалось сменить пароль')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="space-y-3">
    <label class="block">
      <span class="mb-1 block text-tiny uppercase text-text3">{{ loc.t('account.currentPassword', 'Текущий пароль') }}</span>
      <input v-model="current" :type="show ? 'text' : 'password'" autocomplete="current-password"
             class="h-10 w-full rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent" />
    </label>
    <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
      <label class="block">
        <span class="mb-1 block text-tiny uppercase text-text3">{{ loc.t('account.newPassword', 'Новый пароль') }}</span>
        <input v-model="next" :type="show ? 'text' : 'password'" autocomplete="new-password"
               class="h-10 w-full rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent" />
      </label>
      <label class="block">
        <span class="mb-1 block text-tiny uppercase text-text3">{{ loc.t('account.repeatPassword', 'Повторите новый пароль') }}</span>
        <input v-model="repeat" :type="show ? 'text' : 'password'" autocomplete="new-password"
               class="h-10 w-full rounded-sm border bg-card2 px-3 text-sm text-text outline-none focus:border-accent"
               :class="mismatch ? 'border-red' : 'border-border2'" />
      </label>
    </div>
    <label v-if="needCode" class="block">
      <span class="mb-1 block text-tiny uppercase text-text3">{{ loc.t('account.mfaCode', 'Код из приложения-аутентификатора') }}</span>
      <input v-model="code" inputmode="numeric" autocomplete="one-time-code" maxlength="11"
             class="h-10 w-full rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent" />
    </label>
    <label class="flex items-center gap-2 text-xs text-text3">
      <input v-model="show" type="checkbox" class="size-3.5" />{{ loc.t('login.show', 'Показать') }}
    </label>
    <p class="text-tiny text-text3">{{ loc.t('account.passwordHint', { n: MIN }) }}</p>
    <p v-if="mismatch" class="text-sm text-red">{{ loc.t('account.passwordMismatch', 'Пароли не совпадают') }}</p>
    <p v-if="error" class="text-sm text-red">{{ error }}</p>
    <AppButton variant="green" size="sm" :disabled="!canSave" @click="save">
      {{ busy ? loc.t('account.saving', 'Сохраняем…') : loc.t('account.changePassword', 'Сменить пароль') }}
    </AppButton>
  </div>
</template>
