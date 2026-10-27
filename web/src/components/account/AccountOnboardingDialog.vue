<script setup>
/**
 * AccountOnboardingDialog.vue — первичная настройка учётки (27.10.2026, Влад).
 *
 * Студент вошёл по паролю из листа группы — сразу просим привязать почту и придумать
 * свой пароль. Пока он живёт на выданном, пароль знает каждый, кто держал лист в руках.
 *
 * Порядок: почта (обязана совпасть с той, что вписал администратор) → код из письма →
 * новый пароль дважды, с предложением сохранить его в браузере. После этого учётка
 * принадлежит студенту: администратор её пароль не сбросит и в лист выдачи не возьмёт,
 * а забытый пароль восстанавливается кодом на эту же почту.
 *
 * ⚠️ «Позже» прячет окно до следующего входа, а не навсегда: просьба, которую можно
 * закрыть одним нажатием и больше не увидеть, превращает бумажный пароль в вечный.
 * Отказ помнится в памяти вкладки по ЛОГИНУ — смена человека за общим компьютером
 * колледжа окно не гасит.
 */
import { ref, computed, nextTick, onMounted, watch } from 'vue'
import { accountApi } from '@/api/endpoints'
import { useAuthStore } from '@/stores/auth'
import { useLocaleStore } from '@/stores/locale'
import { useToast } from '@/composables/useToast'
import { saveCredential } from '@/utils/credentialStore'
import { postponed, postpone } from '@/utils/onboardingPostpone'
import AppButton from '@/components/ui/AppButton.vue'
import GbIcon from '@/components/ui/GbIcon.vue'

const auth = useAuthStore()
const loc = useLocaleStore()
const toast = useToast()

const MIN = 8
const open = ref(false)
const view = ref(null)
const step = ref('email')               // email → code → password
const email = ref('')
const sentTo = ref('')
const code = ref('')
const next = ref('')
const repeat = ref('')
const mfaCode = ref('')
const needMfa = ref(false)
const show = ref(false)
const busy = ref(false)
const error = ref('')
const firstField = ref(null)

const login = computed(() => auth.user?.login || '')
const mismatch = computed(() => repeat.value && next.value !== repeat.value)
const passOk = computed(() => next.value.length >= MIN && next.value === repeat.value
  && (!needMfa.value || mfaCode.value.trim()))

function focusFirst() { nextTick(() => firstField.value?.focus()) }
function fail(e, fallback) { error.value = e?.response?.data?.detail || fallback }

async function check() {
  if (auth.role !== 'student' || !login.value || postponed(login.value)) return
  try {
    const { data } = await accountApi.onboarding()
    view.value = data
    if (!data?.needed) return
    step.value = data.step === 'password' ? 'password' : 'email'
    open.value = true
    focusFirst()
  } catch { /* нет связи — спросим при следующем входе, журнал важнее */ }
}
onMounted(check)
//Вход другим человеком в той же вкладке — проверяем заново.
watch(login, (now, before) => { if (now && now !== before) { open.value = false; check() } })

function later() {
  postpone(login.value)
  open.value = false
}

async function sendCode() {
  if (busy.value || !/\S+@\S+\.\S+/.test(email.value)) return
  busy.value = true
  error.value = ''
  try {
    const { data } = await accountApi.onboardingEmail(email.value.trim().toLowerCase())
    sentTo.value = data?.sent_to || email.value.trim()
    step.value = 'code'
    focusFirst()
  } catch (e) {
    fail(e, loc.t('onboarding.sendFailed', 'Не удалось отправить код.'))
  } finally { busy.value = false }
}

function onCodeInput(ev) {
  code.value = String(ev.target.value || '').replace(/\D/g, '').slice(0, 6)
  ev.target.value = code.value
  if (code.value.length === 6) checkCode()
}

async function checkCode() {
  if (busy.value || code.value.length !== 6) return
  busy.value = true
  error.value = ''
  try {
    await accountApi.emailConfirm(code.value)
    step.value = 'password'
    focusFirst()
  } catch (e) {
    code.value = ''
    fail(e, loc.t('onboarding.codeFailed', 'Код не подошёл.'))
  } finally { busy.value = false }
}

async function savePassword() {
  if (busy.value || !passOk.value) return
  busy.value = true
  error.value = ''
  try {
    await accountApi.onboardingPassword(next.value, repeat.value, mfaCode.value.trim())
    await saveCredential(login.value, next.value)
    step.value = 'done'
    toast.success(loc.t('onboarding.doneToast', 'Почта привязана, пароль изменён'))
  } catch (e) {
    if (e?.response?.headers?.['x-gb-reason'] === 'mfa_required') needMfa.value = true
    fail(e, loc.t('onboarding.saveFailed', 'Не удалось сменить пароль.'))
  } finally { busy.value = false }
}

const stepIndex = computed(() => ['email', 'code', 'password', 'done'].indexOf(step.value))
</script>

<template>
  <div v-if="open" v-dialog class="fixed inset-0 z-[60] flex items-center justify-center overflow-y-auto overscroll-contain bg-black/50 p-4"
       @click.self="step === 'done' ? (open = false) : later()">
    <div class="my-auto w-full max-w-md rounded-2xl border border-border bg-card p-6 shadow-card"
         role="dialog" aria-modal="true" aria-labelledby="onboarding-title">
      <div class="mb-1 flex items-center gap-2">
        <GbIcon name="locked" class="size-5 text-accent" />
        <h3 id="onboarding-title" class="font-title text-xl font-extrabold text-text">
          {{ loc.t('onboarding.title', 'Защитите свою учётку') }}
        </h3>
      </div>
      <ol class="mb-4 flex gap-1.5" :aria-label="loc.t('recoverCode.steps', 'Шаги')">
        <li v-for="i in 3" :key="i" class="h-1 flex-1 rounded-full transition-colors"
            :class="stepIndex >= i - 1 ? 'bg-accent' : 'bg-border2'" />
      </ol>

      <!-- Почты колледжа нет — привязать нечего, и это не вина студента. -->
      <template v-if="step === 'email' && view && !view.admin_email_set">
        <p class="text-sm text-text2">{{ loc.t('onboarding.noAdminEmail', 'Администратор ещё не внёс вашу почту. Сообщите её куратору или администратору — после этого здесь можно будет привязать почту и сменить пароль.') }}</p>
        <div class="mt-5 flex justify-end">
          <AppButton variant="ghost" size="sm" @click="later">{{ loc.t('onboarding.later', 'Позже') }}</AppButton>
        </div>
      </template>

      <form v-else-if="step === 'email'" class="space-y-3" @submit.prevent="sendCode">
        <p class="text-sm text-text2">{{ loc.t('onboarding.lead', 'Вы вошли по паролю из листа группы. Привяжите почту и придумайте свой пароль — тогда никто, кроме вас, не сможет войти, а забытый пароль восстановится кодом из письма.') }}</p>
        <label class="block">
          <span class="mb-1 block text-tiny uppercase text-text3">{{ loc.t('onboarding.email', 'Почта, которую вы сообщили колледжу') }}</span>
          <input ref="firstField" v-model="email" type="email" autocomplete="email" placeholder="student@yandex.ru"
                 class="h-11 w-full rounded-sm border border-border2 bg-card2 px-3.5 text-sm text-text outline-none focus:border-accent" />
        </label>
        <p v-if="view && !view.mail_ready" class="text-xs text-orange">{{ loc.t('onboarding.mailOff', 'Отправка почты на сервере сейчас не настроена — код не придёт. Сообщите администратору.') }}</p>
        <p v-if="error" class="text-sm text-red" role="alert">{{ error }}</p>
        <div class="flex justify-end gap-2 pt-2">
          <AppButton type="button" variant="ghost" size="sm" @click="later">{{ loc.t('onboarding.later', 'Позже') }}</AppButton>
          <AppButton type="submit" variant="green" size="sm" :disabled="busy || !email.trim()">
            {{ busy ? loc.t('recoverCode.sending', 'Отправляем…') : loc.t('recoverCode.send', 'Получить код') }}
          </AppButton>
        </div>
      </form>

      <form v-else-if="step === 'code'" class="space-y-3" @submit.prevent="checkCode">
        <p class="text-sm text-text2">{{ loc.t('onboarding.codeHint', { email: sentTo }) }}</p>
        <input ref="firstField" :value="code" inputmode="numeric" autocomplete="one-time-code"
               maxlength="6" placeholder="000000" :aria-label="loc.t('recoverCode.codeLabel', 'Код из письма')"
               class="h-12 w-full rounded-sm border border-border2 bg-card2 px-3.5 text-center font-mono text-xl tracking-[0.4em] text-text outline-none focus:border-accent"
               @input="onCodeInput" />
        <p v-if="error" class="text-sm text-red" role="alert">{{ error }}</p>
        <div class="flex flex-wrap items-center justify-between gap-2 pt-2">
          <button type="button" class="text-xs text-text3 underline-offset-2 hover:text-accent hover:underline"
                  @click="step = 'email'; code = ''; error = ''">
            {{ loc.t('onboarding.changeEmail', 'Другой адрес') }}
          </button>
          <AppButton type="submit" variant="green" size="sm" :disabled="busy || code.length !== 6">
            {{ busy ? loc.t('recoverCode.checking', 'Проверяем…') : loc.t('recoverCode.check', 'Дальше') }}
          </AppButton>
        </div>
      </form>

      <form v-else-if="step === 'password'" class="space-y-3" @submit.prevent="savePassword">
        <input type="text" :value="login" autocomplete="username" class="sr-only" tabindex="-1" aria-hidden="true" readonly />
        <p class="text-sm text-text2">{{ loc.t('onboarding.passwordLead', 'Почта подтверждена. Теперь придумайте свой пароль и введите его дважды — браузер предложит его сохранить.') }}</p>
        <label class="block">
          <span class="mb-1 block text-tiny uppercase text-text3">{{ loc.t('account.newPassword', 'Новый пароль') }}</span>
          <input ref="firstField" v-model="next" :type="show ? 'text' : 'password'" autocomplete="new-password"
                 class="h-11 w-full rounded-sm border border-border2 bg-card2 px-3.5 text-sm text-text outline-none focus:border-accent" />
        </label>
        <label class="block">
          <span class="mb-1 block text-tiny uppercase text-text3">{{ loc.t('account.repeatPassword', 'Повторите новый пароль') }}</span>
          <input v-model="repeat" :type="show ? 'text' : 'password'" autocomplete="new-password"
                 class="h-11 w-full rounded-sm border bg-card2 px-3.5 text-sm text-text outline-none focus:border-accent"
                 :class="mismatch ? 'border-red' : 'border-border2'" />
        </label>
        <label v-if="needMfa" class="block">
          <span class="mb-1 block text-tiny uppercase text-text3">{{ loc.t('account.mfaCode', 'Код из приложения-аутентификатора') }}</span>
          <input v-model="mfaCode" inputmode="numeric" autocomplete="one-time-code" maxlength="11"
                 class="h-11 w-full rounded-sm border border-border2 bg-card2 px-3.5 text-sm text-text outline-none focus:border-accent" />
        </label>
        <label class="flex items-center gap-2 text-xs text-text3">
          <input v-model="show" type="checkbox" class="size-3.5" />{{ loc.t('login.show', 'Показать') }}
        </label>
        <p class="text-tiny text-text3">{{ loc.t('onboarding.passwordNote', { n: MIN }) }}</p>
        <p v-if="mismatch" class="text-sm text-red">{{ loc.t('account.passwordMismatch', 'Пароли не совпадают') }}</p>
        <p v-if="error" class="text-sm text-red" role="alert">{{ error }}</p>
        <div class="flex justify-end gap-2 pt-2">
          <AppButton type="button" variant="ghost" size="sm" @click="later">{{ loc.t('onboarding.later', 'Позже') }}</AppButton>
          <AppButton type="submit" variant="green" size="sm" :disabled="busy || !passOk">
            {{ busy ? loc.t('account.saving', 'Сохраняем…') : loc.t('onboarding.save', 'Сохранить пароль') }}
          </AppButton>
        </div>
      </form>

      <div v-else class="py-2 text-center">
        <p class="flex justify-center text-accent"><GbIcon name="ok" class="size-10" /></p>
        <p class="mt-2 text-sm font-semibold text-text">{{ loc.t('onboarding.doneTitle', 'Готово') }}</p>
        <p class="mt-1 text-sm text-text3">{{ loc.t('onboarding.doneText', 'Учётка теперь ваша: пароль знаете только вы. Забудете — нажмите «Забыли пароль?» на странице входа, код придёт на привязанную почту.') }}</p>
        <AppButton variant="green" size="sm" class="mt-4" @click="open = false">{{ loc.t('onboarding.close', 'Понятно') }}</AppButton>
      </div>
    </div>
  </div>
</template>
