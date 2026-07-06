<script setup>
// RegisterDialog — самостоятельная регистрация СТУДЕНТА (заявка админу). Поля: ФИО,
// группа (К.../число, сервер проверит и сопоставит со «сдвоенными»), телефон +7 (красивый
// ввод с маской, все символы отсекаются), e-mail (только @yandex.ru/@mail.ru/@esstu.ru).
// После отправки — заявка ждёт одобрения администратора; пароль придёт на почту.
import { ref, computed } from 'vue'
import { authApi } from '@/api/endpoints'
import AppButton from '@/components/ui/AppButton.vue'

const emit = defineEmits(['close'])

const fullName = ref('')
const group = ref('')
const email = ref('')
const phoneDigits = ref('')          // до 10 цифр после +7
const saving = ref(false)
const error = ref('')
const done = ref(false)

const ALLOWED = ['yandex.ru', 'mail.ru', 'esstu.ru']

// Телефон: показываем красиво +7 (XXX) XXX-XX-XX, храним только цифры.
function onPhone(e) {
  let d = e.target.value.replace(/\D/g, '')
  if (d.length === 11 && (d[0] === '7' || d[0] === '8')) d = d.slice(1)
  phoneDigits.value = d.slice(0, 10)
}
// В поле ВНЕ «+7» (он фиксированным префиксом слева) — только 10 цифр как (XXX) XXX-XX-XX.
const phoneDisplay = computed(() => {
  const d = phoneDigits.value
  if (!d) return ''
  let s = '(' + d.slice(0, 3)
  if (d.length >= 3) s += ')'
  if (d.length > 3) s += ' ' + d.slice(3, 6)
  if (d.length >= 6) s += '-' + d.slice(6, 8)
  if (d.length >= 8) s += '-' + d.slice(8, 10)
  return s
})
const emailDomainOk = computed(() => {
  const m = email.value.trim().toLowerCase().match(/@([a-z0-9.-]+)$/)
  return !!m && ALLOWED.includes(m[1])
})
const canSubmit = computed(() =>
  fullName.value.trim().split(/\s+/).length >= 2 &&
  group.value.trim() && phoneDigits.value.length === 10 &&
  /\S+@\S+\.\S+/.test(email.value) && emailDomainOk.value)

async function submit() {
  if (!canSubmit.value) { error.value = 'Заполните все поля правильно'; return }
  saving.value = true
  error.value = ''
  try {
    await authApi.register({
      full_name: fullName.value.trim(),
      group: group.value.trim(),
      phone: '+7' + phoneDigits.value,
      email: email.value.trim().toLowerCase(),
    })
    done.value = true
  } catch (e) {
    error.value = e?.response?.data?.detail || 'Не удалось отправить заявку'
  } finally { saving.value = false }
}
</script>

<template>
  <div class="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto bg-black/45 p-4" @click.self="emit('close')">
    <div class="my-auto max-h-[92vh] w-full max-w-md overflow-y-auto rounded-2xl border border-border bg-card p-6 shadow-card">
      <h3 class="mb-1 font-title text-xl font-extrabold text-text">Регистрация студента</h3>

      <template v-if="!done">
        <p class="mb-4 text-xs text-text3">Заявку подтвердит администратор — логин и пароль придут на вашу почту.</p>
        <div class="space-y-3">
          <label class="block"><span class="mb-1 block text-tiny uppercase text-text3">ФИО</span>
            <input v-model="fullName" placeholder="Иванов Иван Иванович"
                   class="h-11 w-full rounded-sm border border-border2 bg-card2 px-3.5 text-sm text-text outline-none focus:border-accent" /></label>
          <label class="block"><span class="mb-1 block text-tiny uppercase text-text3">Группа</span>
            <input v-model="group" placeholder="например, К104/2"
                   class="h-11 w-full rounded-sm border border-border2 bg-card2 px-3.5 text-sm text-text outline-none focus:border-accent" />
            <span class="mt-1 block text-tiny text-text3">Формат К…/номер. Если группа сдвоенная — введите свою часть.</span></label>
          <label class="block"><span class="mb-1 block text-tiny uppercase text-text3">Телефон</span>
            <div class="flex h-11 items-center rounded-sm border border-border2 bg-card2 focus-within:border-accent">
              <span class="select-none pl-3.5 pr-1 text-sm text-text3">+7</span>
              <input :value="phoneDisplay" @input="onPhone" inputmode="numeric" placeholder="(___) ___-__-__"
                     class="h-full flex-1 bg-transparent pr-3.5 text-sm text-text outline-none" />
            </div></label>
          <label class="block"><span class="mb-1 block text-tiny uppercase text-text3">Электронная почта (логин)</span>
            <input v-model="email" type="email" placeholder="student@yandex.ru"
                   class="h-11 w-full rounded-sm border border-border2 bg-card2 px-3.5 text-sm text-text outline-none focus:border-accent"
                   :class="email && !emailDomainOk ? 'border-red' : ''" />
            <span class="mt-1 block text-tiny" :class="email && !emailDomainOk ? 'text-red' : 'text-text3'">
              Разрешены только @yandex.ru, @mail.ru, @esstu.ru</span></label>
          <p v-if="error" class="text-sm text-red">{{ error }}</p>
        </div>
        <div class="mt-5 flex justify-end gap-2">
          <AppButton variant="ghost" size="sm" @click="emit('close')">Отмена</AppButton>
          <AppButton variant="green" size="sm" :disabled="saving || !canSubmit" @click="submit">
            {{ saving ? 'Отправка…' : 'Отправить заявку' }}
          </AppButton>
        </div>
      </template>

      <template v-else>
        <div class="py-4 text-center">
          <p class="text-3xl">📨</p>
          <p class="mt-2 text-sm font-semibold text-text">Заявка отправлена!</p>
          <p class="mt-1 text-sm text-text3">Когда администратор её подтвердит, логин и пароль придут на <b class="text-text">{{ email }}</b>.</p>
          <AppButton variant="green" size="sm" class="mt-4" @click="emit('close')">Понятно</AppButton>
        </div>
      </template>
    </div>
  </div>
</template>
