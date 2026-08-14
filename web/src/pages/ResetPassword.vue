<script setup>
/**
 * ResetPassword.vue — страница по ссылке из письма восстановления.
 *
 * Публичная (meta.public): человек сюда приходит именно потому, что войти не может.
 *
 * ⚠️ Токен берём из query и НИКУДА не сохраняем — ни в localStorage, ни в стор. Он
 * одноразовый и живёт полчаса; сохранённая копия пережила бы смену пароля и осталась бы
 * лежать в браузере общего компьютера колледжа.
 */
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { authApi } from '@/api/endpoints'
import { useLocaleStore } from '@/stores/locale'
import AppButton from '@/components/ui/AppButton.vue'
import BrandLogo from '@/components/BrandLogo.vue'

const route = useRoute()
const router = useRouter()
const locale = useLocaleStore()
const t = (k, f) => locale.t(k, f)

const token = ref('')
const pw = ref('')
const pw2 = ref('')
const busy = ref(false)
const error = ref('')
const done = ref(false)

onMounted(() => { token.value = String(route.query.token || '') })

// Проверка ровно та же, что на сервере (восемь символов). Второе, более строгое правило
// на клиенте отправило бы человека по кругу: сервер бы такой пароль принял.
const canSubmit = computed(() =>
  !busy.value && token.value && pw.value.length >= 8 && pw.value === pw2.value)

async function submit() {
  error.value = ''
  if (pw.value !== pw2.value) {
    error.value = t('resetPassword.mismatch', 'Пароли не совпадают')
    return
  }
  busy.value = true
  try {
    await authApi.recoverConfirm(token.value, pw.value)
    done.value = true
    // Небольшая пауза, чтобы человек успел прочитать, что всё получилось.
    setTimeout(() => router.replace('/login'), 2200)
  } catch (e) {
    // Причину показываем как есть: она приходит с сервера уже человеческой («ссылка
    // недействительна или истекла»), и подменять её общим «ошибка» значит оставить
    // человека без единственной подсказки, что делать дальше.
    error.value = e?.response?.data?.detail
      || t('resetPassword.failed', 'Не удалось сменить пароль. Запросите восстановление заново.')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="min-h-screen flex items-center justify-center p-4 bg-bg">
    <div class="w-full max-w-md rounded-2xl border border-line bg-card p-6 sm:p-8">
      <div class="flex flex-col items-center gap-3 mb-6">
        <BrandLogo class="w-14 h-14" />
        <h1 class="text-xl font-semibold text-text text-center">
          {{ t('resetPassword.title', 'Новый пароль') }}
        </h1>
      </div>

      <div v-if="!token" class="text-sm text-red text-center">
        {{ t('resetPassword.noToken', 'Ссылка неполная. Откройте её из письма целиком.') }}
      </div>

      <div v-else-if="done" class="text-sm text-accent text-center">
        {{ t('resetPassword.done', 'Пароль изменён. Сейчас откроется страница входа.') }}
      </div>

      <form v-else class="flex flex-col gap-4" @submit.prevent="submit">
        <label class="flex flex-col gap-1.5">
          <span class="text-xs text-muted">{{ t('resetPassword.newPw', 'Новый пароль') }}</span>
          <input v-model="pw" type="password" autocomplete="new-password" minlength="8"
                 class="w-full rounded-xl border border-line bg-bg px-3 py-2.5 text-text" />
        </label>
        <label class="flex flex-col gap-1.5">
          <span class="text-xs text-muted">{{ t('resetPassword.repeat', 'Повторите пароль') }}</span>
          <input v-model="pw2" type="password" autocomplete="new-password" minlength="8"
                 class="w-full rounded-xl border border-line bg-bg px-3 py-2.5 text-text" />
        </label>

        <p class="text-xs text-muted">
          {{ t('resetPassword.hint', 'Не короче 8 символов.') }}
        </p>
        <p v-if="error" class="text-sm text-red">{{ error }}</p>

        <AppButton type="submit" :disabled="!canSubmit">
          {{ busy ? t('resetPassword.saving', 'Сохранение…') : t('resetPassword.submit', 'Сменить пароль') }}
        </AppButton>
        <router-link to="/login" class="text-xs text-muted text-center hover:text-text">
          {{ t('resetPassword.backToLogin', 'Вернуться ко входу') }}
        </router-link>
      </form>
    </div>
  </div>
</template>
