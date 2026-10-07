<script setup>
/**
 * ContactsCard.vue — почта и телефон для защиты входа (4.0).
 *
 * Подтверждённая почта становится СПОСОБОМ ЗАЩИТЫ: вход с нового устройства требует
 * код из письма (кроме доверенных устройств). Подтверждается только кодом — иначе код
 * входа ушёл бы на адрес, который вписал кто угодно.
 *
 * Телефон кодом не подтверждается и кодов не получает: сервиса SMS у колледжа нет (и
 * он был бы новым получателем персональных данных). Телефон нужен для сверки с тем,
 * что студент сообщил колледжу лично: не совпало — администратор видит красное поле.
 *
 * 🔒 Любая правка — с ТЕКУЩИМ ПАРОЛЕМ (07.10.2026, OWASP ASVS V7.5.1). На почту приходит
 * код входа, по телефону администратор сверяет человека перед выдачей нового пароля: кто
 * подменил их на свои — забрал аккаунт. Раньше для этого хватало открытой вкладки на
 * общем компьютере. Проверяет СЕРВЕР; поле здесь — чтобы было куда ввести. Пароль
 * стирается из поля после каждого удачного действия.
 */
import { ref, onMounted } from 'vue'
import { accountApi } from '@/api/endpoints'
import AppButton from '@/components/ui/AppButton.vue'
import { useToast } from '@/composables/useToast'
import { useConfirm } from '@/composables/useConfirm'
import { useLocaleStore } from '@/stores/locale'

const loc = useLocaleStore()
const toast = useToast()
const { confirm } = useConfirm()
const info = ref(null)
const email = ref('')
const phone = ref('')
const code = ref('')
const sentTo = ref('')
const busy = ref(false)
const error = ref('')
const current = ref('')          //текущий пароль — подтверждение личности для правки
const mfaCode = ref('')
const needMfa = ref(false)       //сервер сказал, что у человека включён второй фактор
const currentInput = ref(null)

/** Пароль введён? Нет — говорим об этом рядом с полем и ставим в него курсор. */
function havePassword() {
  if (current.value) return true
  error.value = loc.t('account.passwordNeeded', 'Введите текущий пароль — он нужен, чтобы изменить почту или телефон')
  currentInput.value?.focus()
  return false
}

/** Отказ сервера → текст рядом с полем; «нужен код» открывает поле второго фактора. */
function explain(e, fallback) {
  if (e?.response?.headers?.['x-gb-reason'] === 'mfa_required') needMfa.value = true
  error.value = e?.response?.data?.detail || fallback
}

function forgetPassword() { current.value = mfaCode.value = '' }

async function load() {
  try {
    info.value = (await accountApi.contacts()).data
    phone.value = info.value.self_phone || ''
  } catch { info.value = null }
}
onMounted(load)

async function sendCode() {
  if (!havePassword()) return
  busy.value = true
  error.value = ''
  try {
    sentTo.value = (await accountApi.emailStart(email.value.trim(), current.value, mfaCode.value.trim())).data.sent_to || ''
    forgetPassword()
  } catch (e) {
    explain(e, loc.t('account.codeSendFailed', 'Не удалось отправить код'))
  } finally { busy.value = false }
}

async function confirmCode() {
  busy.value = true
  error.value = ''
  try {
    info.value = (await accountApi.emailConfirm(code.value.trim())).data
    email.value = code.value = sentTo.value = ''
    toast.success(loc.t('account.emailVerified', 'Почта подтверждена'))
  } catch (e) {
    error.value = e?.response?.data?.detail || loc.t('account.codeWrong', 'Код не подошёл')
  } finally { busy.value = false }
}

async function removeEmail() {
  if (!havePassword()) return
  if (!(await confirm({ title: loc.t('account.removeEmailConfirm', 'Убрать почту? Вход с новых устройств перестанет спрашивать код.'), okText: loc.t('common.delete'), danger: true }))) return
  error.value = ''
  try {
    info.value = (await accountApi.emailRemove(current.value, mfaCode.value.trim())).data
    forgetPassword()
  } catch (e) {
    //Молчать нельзя: почта осталась, а человек уверен, что убрал её.
    explain(e, loc.t('account.emailRemoveFailed', 'Не удалось убрать почту'))
  }
}

async function savePhone() {
  if (!havePassword()) return
  busy.value = true
  error.value = ''
  try {
    info.value = (await accountApi.setPhone(phone.value.trim(), current.value, mfaCode.value.trim())).data
    phone.value = info.value.self_phone || ''
    forgetPassword()
    toast.success(loc.t('account.phoneSaved', 'Телефон сохранён'))
  } catch (e) {
    explain(e, loc.t('account.phoneFailed', 'Не удалось сохранить телефон'))
  } finally { busy.value = false }
}
</script>

<template>
  <div class="space-y-4">
    <p v-if="info && !info.mail_configured" class="rounded-md border border-orange/40 bg-orange/10 px-3 py-2 text-sm text-text2">
      {{ loc.t('account.mailNotConfigured', 'Отправка почты на сервере не настроена — подтвердить адрес сейчас нельзя.') }}
    </p>

    <div>
      <label for="contacts-current-password" class="mb-1 block text-tiny uppercase text-text3">{{ loc.t('account.currentPassword', 'Текущий пароль') }}</label>
      <p class="mb-2 text-tiny text-text3">{{ loc.t('account.contactsPasswordHint', 'Нужен, чтобы изменить почту или телефон: так посторонний за вашим открытым журналом не подменит их на свои.') }}</p>
      <input id="contacts-current-password" ref="currentInput" v-model="current" type="password" autocomplete="current-password"
             class="h-10 w-full rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent sm:max-w-xs" />
      <div v-if="needMfa" class="mt-2">
        <label for="contacts-mfa-code" class="mb-1 block text-tiny uppercase text-text3">{{ loc.t('account.mfaCode', 'Код из приложения-аутентификатора') }}</label>
        <input id="contacts-mfa-code" v-model="mfaCode" inputmode="numeric" autocomplete="one-time-code" maxlength="11"
               class="h-10 w-40 rounded-sm border border-border2 bg-card2 px-3 text-sm tracking-widest text-text outline-none focus:border-accent" />
      </div>
    </div>

    <div>
      <span class="mb-1 block text-tiny uppercase text-text3">{{ loc.t('account.email', 'Почта') }}</span>
      <div v-if="info && info.self_email" class="mb-2 flex flex-wrap items-center gap-2 text-sm">
        <span class="font-medium text-text">{{ info.self_email }}</span>
        <span v-if="info.self_email_verified" class="rounded-full bg-accent-glow px-2 py-0.5 text-tiny font-semibold text-accent">
          {{ loc.t('account.verified', 'подтверждена') }}</span>
        <button type="button" class="text-tiny text-text3 underline hover:text-red" @click="removeEmail">
          {{ loc.t('account.removeEmail', 'убрать') }}</button>
      </div>
      <p class="mb-2 text-tiny text-text3">{{ loc.t('account.emailHint', 'На подтверждённую почту придёт код, когда вы войдёте с нового устройства, и письмо о смене пароля.') }}</p>
      <div class="flex flex-wrap gap-2">
        <input v-model="email" type="email" placeholder="student@yandex.ru"
               class="h-10 min-w-0 flex-1 rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent" />
        <AppButton variant="ghost" size="sm" :disabled="busy || !email.trim()" @click="sendCode">
          {{ loc.t('account.sendCode', 'Прислать код') }}</AppButton>
      </div>
      <div v-if="sentTo" class="mt-2 flex flex-wrap items-center gap-2">
        <span class="text-tiny text-text3">{{ loc.t('account.codeSentTo', { to: sentTo }) }}</span>
        <input v-model="code" inputmode="numeric" maxlength="6" placeholder="000000"
               class="h-10 w-32 rounded-sm border border-border2 bg-card2 px-3 text-center text-sm tracking-widest text-text outline-none focus:border-accent" />
        <AppButton variant="green" size="sm" :disabled="busy || code.trim().length < 6" @click="confirmCode">
          {{ loc.t('account.confirm', 'Подтвердить') }}</AppButton>
      </div>
    </div>

    <div>
      <span class="mb-1 block text-tiny uppercase text-text3">{{ loc.t('account.phone', 'Телефон') }}</span>
      <p class="mb-2 text-tiny text-text3">{{ loc.t('account.phoneHint', 'Нужен для сверки с данными, которые вы сообщили колледжу. Коды на телефон не приходят.') }}</p>
      <div class="flex flex-wrap gap-2">
        <input v-model="phone" inputmode="tel" placeholder="+7 900 000-00-00"
               class="h-10 min-w-0 flex-1 rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent" />
        <AppButton variant="ghost" size="sm" :disabled="busy" @click="savePhone">{{ loc.t('common.save') }}</AppButton>
      </div>
    </div>
    <p v-if="error" class="text-sm text-red" role="alert">{{ error }}</p>
  </div>
</template>
