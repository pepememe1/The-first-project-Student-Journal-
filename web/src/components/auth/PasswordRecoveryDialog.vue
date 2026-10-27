<script setup>
/**
 * PasswordRecoveryDialog.vue — «Забыли пароль?» кодом из письма (27.10.2026, Влад).
 *
 * Появляется на странице входа после двух неудачных попыток. Три шага:
 *   1) логин и почта → сервер шлёт код, ТОЛЬКО если почта совпадает и с подтверждённой
 *      в профиле, и с той, что вписал администратор;
 *   2) код из письма → одноразовый ключ;
 *   3) новый пароль дважды → смена тем же `/auth/recover/confirm`, что у ссылки из письма.
 *
 * ⚠️ Ответ на шаге 1 ОДИНАКОВЫЙ, совпала почта или нет: иначе форма «логин + почта»
 * выдавала бы почту любого студента. Поэтому текст говорит «если почта совпадает», а
 * не «код отправлен».
 *
 * ⚠️ Старое окно `RecoverDialog.vue` (ссылкой, без логина) НЕ заменено и не удалено: оно
 * под выключателем самообслуживания страницы входа и вернётся вместе с регистрацией.
 */
import { ref, computed, nextTick, onMounted } from 'vue'
import { authApi } from '@/api/endpoints'
import { useLocaleStore } from '@/stores/locale'
import { saveCredential } from '@/utils/credentialStore'
import AppButton from '@/components/ui/AppButton.vue'
import GbIcon from '@/components/ui/GbIcon.vue'

const props = defineProps({ login: { type: String, default: '' } })
const emit = defineEmits(['close', 'done'])
const loc = useLocaleStore()

const MIN = 8
const step = ref('email')               // email → code → password
const who = ref(props.login.trim())
const email = ref('')
const code = ref('')
const token = ref('')
const next = ref('')
const repeat = ref('')
const mfaCode = ref('')
const needMfa = ref(false)
const show = ref(false)
const busy = ref(false)
const error = ref('')
const firstField = ref(null)

const emailOk = computed(() => who.value.trim() && /\S+@\S+\.\S+/.test(email.value))
const codeOk = computed(() => /^\d{6}$/.test(code.value))
const mismatch = computed(() => repeat.value && next.value !== repeat.value)
const passOk = computed(() => next.value.length >= MIN && next.value === repeat.value
  && (!needMfa.value || mfaCode.value.trim()))

function focusFirst() { nextTick(() => firstField.value?.focus()) }
onMounted(focusFirst)

function fail(e, fallback) {
  error.value = e?.response?.data?.detail || fallback
}

async function sendCode() {
  if (!emailOk.value || busy.value) return
  busy.value = true
  error.value = ''
  try {
    await authApi.recoverCodeStart(who.value.trim(), email.value.trim().toLowerCase())
    step.value = 'code'
    focusFirst()
  } catch (e) {
    fail(e, loc.t('recoverCode.sendFailed', 'Не удалось запросить код. Попробуйте ещё раз.'))
  } finally { busy.value = false }
}

function onCodeInput(ev) {
  code.value = String(ev.target.value || '').replace(/\D/g, '').slice(0, 6)
  ev.target.value = code.value
  if (codeOk.value) checkCode()
}

async function checkCode() {
  if (!codeOk.value || busy.value) return
  busy.value = true
  error.value = ''
  try {
    const { data } = await authApi.recoverCodeVerify(who.value.trim(), code.value)
    token.value = data.token
    step.value = 'password'
    focusFirst()
  } catch (e) {
    code.value = ''
    fail(e, loc.t('recoverCode.codeFailed', 'Код не подошёл или истёк. Запросите новый.'))
  } finally { busy.value = false }
}

async function savePassword() {
  if (!passOk.value || busy.value) return
  busy.value = true
  error.value = ''
  try {
    const { data } = await authApi.recoverConfirm(token.value, next.value, mfaCode.value.trim())
    const login = data?.login || who.value.trim()
    await saveCredential(login, next.value)
    emit('done', { login, password: next.value })
  } catch (e) {
    //Второй фактор у человека включён — сервер сказал это признаком, а не текстом.
    if (e?.response?.headers?.['x-gb-reason'] === 'mfa_required') needMfa.value = true
    fail(e, loc.t('recoverCode.saveFailed', 'Не удалось сменить пароль.'))
  } finally { busy.value = false }
}

function again() {
  step.value = 'email'
  code.value = ''
  error.value = ''
  focusFirst()
}
</script>

<template>
  <div v-dialog class="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto overscroll-contain bg-black/45 p-4"
       @click.self="emit('close')">
    <div class="my-auto w-full max-w-sm rounded-2xl border border-border bg-card p-6 shadow-card"
         role="dialog" aria-modal="true" aria-labelledby="recover-code-title">
      <div class="mb-1 flex items-center gap-2">
        <GbIcon name="key" class="size-5 text-accent" />
        <h3 id="recover-code-title" class="font-title text-xl font-extrabold text-text">
          {{ loc.t('recoverCode.title', 'Восстановление пароля') }}
        </h3>
      </div>
      <!-- Шаги видны, чтобы было понятно, сколько осталось: три коротких экрана читаются
           легче одной длинной формы, но без счётчика каждый следующий кажется лишним. -->
      <ol class="mb-4 flex gap-1.5" :aria-label="loc.t('recoverCode.steps', 'Шаги')">
        <li v-for="(s, i) in ['email', 'code', 'password']" :key="s"
            class="h-1 flex-1 rounded-full transition-colors"
            :class="['email', 'code', 'password'].indexOf(step) >= i ? 'bg-accent' : 'bg-border2'" />
      </ol>

      <form v-if="step === 'email'" class="space-y-3" @submit.prevent="sendCode">
        <p class="text-xs text-text3">
          {{ loc.t('recoverCode.emailHint', 'Укажите почту, которую вы привязали в профиле и сообщили колледжу. Код придёт на неё.') }}
        </p>
        <label class="block">
          <span class="mb-1 block text-tiny uppercase text-text3">{{ loc.t('recoverCode.login', 'Логин') }}</span>
          <input v-model="who" autocomplete="username" spellcheck="false" autocapitalize="off"
                 class="h-11 w-full rounded-sm border border-border2 bg-card2 px-3.5 text-sm text-text outline-none focus:border-accent" />
        </label>
        <label class="block">
          <span class="mb-1 block text-tiny uppercase text-text3">{{ loc.t('recoverCode.email', 'Электронная почта') }}</span>
          <input ref="firstField" v-model="email" type="email" autocomplete="email" placeholder="student@yandex.ru"
                 class="h-11 w-full rounded-sm border border-border2 bg-card2 px-3.5 text-sm text-text outline-none focus:border-accent" />
        </label>
        <p v-if="error" class="text-sm text-red" role="alert">{{ error }}</p>
        <div class="flex justify-end gap-2 pt-2">
          <AppButton type="button" variant="ghost" size="sm" @click="emit('close')">{{ loc.t('common.cancel', 'Отмена') }}</AppButton>
          <AppButton type="submit" variant="green" size="sm" :disabled="busy || !emailOk">
            {{ busy ? loc.t('recoverCode.sending', 'Отправляем…') : loc.t('recoverCode.send', 'Получить код') }}
          </AppButton>
        </div>
      </form>

      <form v-else-if="step === 'code'" class="space-y-3" @submit.prevent="checkCode">
        <p class="text-xs text-text3">
          {{ loc.t('recoverCode.codeHint', { email: email.trim() }) }}
        </p>
        <input ref="firstField" :value="code" inputmode="numeric" autocomplete="one-time-code"
               maxlength="6" placeholder="000000" :aria-label="loc.t('recoverCode.codeLabel', 'Код из письма')"
               class="h-12 w-full rounded-sm border border-border2 bg-card2 px-3.5 text-center font-mono text-xl tracking-[0.4em] text-text outline-none focus:border-accent"
               @input="onCodeInput" />
        <p v-if="error" class="text-sm text-red" role="alert">{{ error }}</p>
        <div class="flex flex-wrap items-center justify-between gap-2 pt-2">
          <button type="button" class="text-xs text-text3 underline-offset-2 hover:text-accent hover:underline" @click="again">
            {{ loc.t('recoverCode.again', 'Не пришёл код? Проверить почту') }}
          </button>
          <AppButton type="submit" variant="green" size="sm" :disabled="busy || !codeOk">
            {{ busy ? loc.t('recoverCode.checking', 'Проверяем…') : loc.t('recoverCode.check', 'Дальше') }}
          </AppButton>
        </div>
      </form>

      <!-- Скрытое поле логина — для менеджера паролей: без него браузер не знает, к какой
           учётке относится новый пароль, и предлагает сохранить его «без имени». -->
      <form v-else class="space-y-3" @submit.prevent="savePassword">
        <input type="text" :value="who" autocomplete="username" class="sr-only" tabindex="-1" aria-hidden="true" readonly />
        <p class="text-xs text-text3">{{ loc.t('recoverCode.passwordHint', 'Придумайте новый пароль и введите его дважды.') }}</p>
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
        <p class="text-tiny text-text3">{{ loc.t('recoverCode.minLength', { n: MIN }) }}</p>
        <p v-if="mismatch" class="text-sm text-red">{{ loc.t('account.passwordMismatch', 'Пароли не совпадают') }}</p>
        <p v-if="error" class="text-sm text-red" role="alert">{{ error }}</p>
        <div class="flex justify-end gap-2 pt-2">
          <AppButton type="button" variant="ghost" size="sm" @click="emit('close')">{{ loc.t('common.cancel', 'Отмена') }}</AppButton>
          <AppButton type="submit" variant="green" size="sm" :disabled="busy || !passOk">
            {{ busy ? loc.t('account.saving', 'Сохраняем…') : loc.t('recoverCode.save', 'Сохранить и войти') }}
          </AppButton>
        </div>
      </form>
    </div>
  </div>
</template>
