<script setup>
// RecoverDialog — восстановление пароля студента по e-mail (= логин). Сервер, если
// аккаунт есть, генерирует НОВЫЙ пароль, отзывает старый и шлёт его на почту. Ответ
// одинаковый независимо от наличия почты (не раскрываем, есть ли такой аккаунт).
import { ref, computed } from 'vue'
import { authApi } from '@/api/endpoints'
import AppButton from '@/components/ui/AppButton.vue'

const emit = defineEmits(['close'])
const email = ref('')
const saving = ref(false)
const error = ref('')
const done = ref(false)

const canSubmit = computed(() => /\S+@\S+\.\S+/.test(email.value))

async function submit() {
  if (!canSubmit.value) { error.value = 'Введите корректную почту'; return }
  saving.value = true
  error.value = ''
  try {
    await authApi.recover(email.value.trim().toLowerCase())
    done.value = true
  } catch (e) {
    error.value = e?.response?.data?.detail || 'Не удалось выполнить восстановление'
  } finally { saving.value = false }
}
</script>

<template>
  <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-4" @click.self="emit('close')">
    <div class="w-full max-w-sm rounded-2xl border border-border bg-card p-6 shadow-card">
      <h3 class="mb-1 font-title text-xl font-extrabold text-text">Восстановление пароля</h3>
      <template v-if="!done">
        <p class="mb-4 text-xs text-text3">Введите почту, привязанную к аккаунту (она же логин). Новый пароль придёт на неё.</p>
        <label class="block"><span class="mb-1 block text-tiny uppercase text-text3">Электронная почта</span>
          <input v-model="email" type="email" placeholder="student@yandex.ru" @keyup.enter="submit"
                 class="h-11 w-full rounded-sm border border-border2 bg-card2 px-3.5 text-sm text-text outline-none focus:border-accent" /></label>
        <p v-if="error" class="mt-2 text-sm text-red">{{ error }}</p>
        <div class="mt-5 flex justify-end gap-2">
          <AppButton variant="ghost" size="sm" @click="emit('close')">Отмена</AppButton>
          <AppButton variant="green" size="sm" :disabled="saving || !canSubmit" @click="submit">
            {{ saving ? 'Отправка…' : 'Восстановить' }}
          </AppButton>
        </div>
      </template>
      <template v-else>
        <div class="py-4 text-center">
          <p class="text-3xl">✅</p>
          <p class="mt-2 text-sm font-semibold text-text">Готово</p>
          <p class="mt-1 text-sm text-text3">Если аккаунт с такой почтой существует, новый пароль отправлен на <b class="text-text">{{ email }}</b>.</p>
          <AppButton variant="green" size="sm" class="mt-4" @click="emit('close')">Понятно</AppButton>
        </div>
      </template>
    </div>
  </div>
</template>
