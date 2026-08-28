<script setup>
/**
 * InviteRegister.vue — регистрация студента по ссылке-приглашению куратора.
 *
 * Публичная (meta.public): человек приходит сюда ДО того, как у него появился аккаунт.
 *
 * Отличие от обычной заявки на экране входа принципиальное: там человек сам называет
 * группу и ждёт, пока администратор одобрит его по одной. Здесь одобрением служит сама
 * ссылка — её выдал куратор группы, — поэтому аккаунт заводится сразу.
 *
 * ⚠️ ГРУППУ ПОКАЗЫВАЕМ ДО ФОРМЫ. Приглашение приходит переслаными сообщениями, и человек
 * должен видеть, КУДА он вступает, прежде чем оставит ФИО и почту: «просто заполните
 * форму» — это подпись под неизвестным. Название приезжает с сервера по токену
 * (`GET /auth/invite/{token}`), а не берётся из ссылки: в ссылке его нет и быть не
 * должно — иначе его можно было бы подменить в адресной строке.
 *
 * ⚠️ Токен НИКУДА не сохраняем: он одноразовое право на регистрацию, а компьютер в
 * колледже общий.
 */
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { authApi } from '@/api/endpoints'
import { useLocaleStore } from '@/stores/locale'
import AppButton from '@/components/ui/AppButton.vue'
import BrandLogo from '@/components/BrandLogo.vue'

const route = useRoute()
const locale = useLocaleStore()
const t = (k, f, p) => locale.t(k, f, p)

const token = ref('')
const checking = ref(true)
const group = ref('')
const note = ref('')
const invalid = ref('')          // причина, по которой ссылка не годится

const fullName = ref('')
const email = ref('')
const phone = ref('')
const busy = ref(false)
const error = ref('')
const done = ref(null)           // {login, sent, password}

onMounted(async () => {
  token.value = String(route.params.token || route.query.token || '')
  if (!token.value) {
    invalid.value = t('invite.noToken', 'Ссылка неполная. Откройте её целиком.')
    checking.value = false
    return
  }
  try {
    const { data } = await authApi.inviteInfo(token.value)
    group.value = data.group
    note.value = data.note || ''
  } catch (e) {
    // Причина приходит с сервера уже человеческой («срок действия истёк», «отозвано») —
    // подменять её общим «ошибка» значит оставить человека без единственной подсказки,
    // что делать: просить у куратора новую ссылку.
    invalid.value = e?.response?.data?.detail
      || t('invite.badLink', 'Ссылка недействительна. Попросите у куратора новую.')
  } finally {
    checking.value = false
  }
})

const canSubmit = computed(() =>
  !busy.value && fullName.value.trim().split(/\s+/).length >= 2
  && email.value.includes('@') && phone.value.replace(/\D/g, '').length >= 10)

async function submit() {
  error.value = ''
  busy.value = true
  try {
    const { data } = await authApi.registerByInvite({
      token: token.value, full_name: fullName.value.trim(),
      email: email.value.trim(), phone: phone.value.trim(),
    })
    done.value = data
  } catch (e) {
    error.value = e?.response?.data?.detail
      || t('invite.failed', 'Не удалось зарегистрироваться. Попробуйте ещё раз.')
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
          {{ t('invite.title', 'Регистрация в журнале') }}
        </h1>
      </div>

      <p v-if="checking" class="text-sm text-muted text-center">
        {{ t('invite.checking', 'Проверяем приглашение…') }}
      </p>

      <div v-else-if="invalid" class="text-sm text-red text-center">
        {{ invalid }}
      </div>

      <!-- Готово. Пароль показываем ТОЛЬКО если письмо не ушло: иначе он лёг бы в
           историю браузера общего компьютера. Без почты альтернативы нет — иначе
           человек не узнает пароль вовсе. -->
      <div v-else-if="done" class="flex flex-col gap-3 text-sm">
        <p class="text-accent">{{ t('invite.done', 'Готово! Аккаунт создан.') }}</p>
        <p class="text-text">{{ t('invite.yourLogin', 'Логин') }}: <b>{{ done.login }}</b></p>
        <p v-if="done.sent" class="text-muted">
          {{ t('invite.mailed', 'Пароль отправлен на вашу почту.') }}
        </p>
        <template v-else>
          <p class="text-text">
            {{ t('invite.yourPassword', 'Пароль') }}:
            <b class="select-all text-lg">{{ done.password }}</b>
          </p>
          <p class="text-red text-xs">
            {{ t('invite.savePassword', 'Письмо отправить не удалось — сохраните пароль сейчас, второй раз он не покажется.') }}
          </p>
        </template>
        <router-link to="/login"
                     class="mt-2 text-center text-sm text-accent hover:underline">
          {{ t('invite.goLogin', 'Перейти ко входу') }}
        </router-link>
      </div>

      <form v-else class="flex flex-col gap-4" @submit.prevent="submit">
        <!-- Куда именно вступает человек — до всех полей. -->
        <div class="rounded-xl border border-line bg-bg px-3 py-2.5">
          <div class="text-xs text-muted">{{ t('invite.joiningGroup', 'Вы регистрируетесь в группу') }}</div>
          <div class="text-lg font-semibold text-text">{{ group }}</div>
          <div v-if="note" class="text-xs text-muted mt-0.5">{{ note }}</div>
        </div>

        <label class="flex flex-col gap-1.5">
          <span class="text-xs text-muted">{{ t('invite.fullName', 'Фамилия Имя Отчество') }}</span>
          <input v-model="fullName" autocomplete="name"
                 class="w-full rounded-xl border border-line bg-bg px-3 py-2.5 text-text" />
        </label>
        <label class="flex flex-col gap-1.5">
          <span class="text-xs text-muted">{{ t('invite.email', 'Почта (станет логином)') }}</span>
          <input v-model="email" type="email" autocomplete="email"
                 class="w-full rounded-xl border border-line bg-bg px-3 py-2.5 text-text" />
        </label>
        <label class="flex flex-col gap-1.5">
          <span class="text-xs text-muted">{{ t('invite.phone', 'Телефон') }}</span>
          <input v-model="phone" type="tel" autocomplete="tel"
                 class="w-full rounded-xl border border-line bg-bg px-3 py-2.5 text-text" />
        </label>

        <p class="text-xs text-muted">
          {{ t('invite.mailHint', 'Разрешены почты @yandex.ru, @mail.ru, @esstu.ru. Пароль придёт письмом.') }}
        </p>
        <p v-if="error" class="text-sm text-red">{{ error }}</p>

        <AppButton type="submit" :disabled="!canSubmit">
          {{ busy ? t('invite.sending', 'Отправляем…') : t('invite.submit', 'Зарегистрироваться') }}
        </AppButton>
        <router-link to="/login" class="text-xs text-muted text-center hover:text-text">
          {{ t('invite.haveAccount', 'У меня уже есть аккаунт') }}
        </router-link>
      </form>
    </div>
  </div>
</template>
