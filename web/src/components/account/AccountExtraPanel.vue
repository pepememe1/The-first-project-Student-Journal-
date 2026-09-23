<script setup>
/**
 * AccountExtraPanel.vue — «доп. данные» в редакторе пользователя (4.0).
 *
 * Две вещи, и обе — про безопасность аккаунта, а не про учёбу:
 *   • СВЕРКА КОНТАКТОВ. Слева то, что человек сообщил колледжу лично (вписывает
 *     администратор), справа — что он указал сам в профиле. Не совпало — поле горит
 *     красным: это повод спросить студента, не угнали ли аккаунт (угнавший меняет СВОЮ
 *     почту, до записи колледжа ему не дотянуться). Код подтверждения входа при
 *     расхождении на почту не уходит — сервер решает это сам.
 *   • СТАРТОВЫЙ ПАРОЛЬ. Пока студент не сменил выданный колледжем пароль, его можно
 *     посмотреть и скопировать. Сменил — «Студент сменил пароль», доступен только сброс.
 *     Пароль, придуманный самим человеком, не виден никому — это держит сервер сверкой
 *     хеша, а не эта панель.
 *
 * `login` пуст при СОЗДАНИИ пользователя: пароля ещё нет, а контакты сохраняются тем же
 * `save(login)`, который зовёт форма после создания.
 */
import { ref, watch, computed } from 'vue'
import { Copy, RotateCw } from '@lucide/vue'
import { accountApi } from '@/api/endpoints'
import { copyText } from '@/utils/clipboard'
import { useToast } from '@/composables/useToast'
import { useConfirm } from '@/composables/useConfirm'
import { useLocaleStore } from '@/stores/locale'

const props = defineProps({
  login: { type: String, default: '' },
  isAdmin: { type: Boolean, default: true },
})
const loc = useLocaleStore()
const toast = useToast()
const { confirm } = useConfirm()
const data = ref(null)
const adminEmail = ref('')
const adminPhone = ref('')
const busy = ref(false)
const loadError = ref('')

const contacts = computed(() => data.value?.contacts || null)
const cred = computed(() => data.value?.credential || null)

async function load() {
  data.value = null
  loadError.value = ''
  if (!props.login) return
  try {
    data.value = (await accountApi.extra(props.login)).data
    adminEmail.value = data.value?.contacts?.admin_email || ''
    adminPhone.value = data.value?.contacts?.admin_phone || ''
  } catch (e) {
    loadError.value = e?.response?.data?.detail || loc.t('extra.loadFailed', 'Не удалось загрузить доп. данные')
  }
}
watch(() => props.login, load, { immediate: true })

//Красным — ТОЛЬКО расхождение. Пустое поле с одной стороны — не тревога, а «не знаем».
function stateCls(state) {
  return state === 'mismatch' ? 'border-red bg-red/10' : 'border-border2 bg-card2'
}

/** Сохранить запись колледжа. Зовёт форма редактора ПОСЛЕ основного сохранения. */
async function save(login) {
  const who = login || props.login
  if (!props.isAdmin || !who) return true
  const was = data.value?.contacts || {}
  if ((was.admin_email || '') === adminEmail.value.trim()
      && (was.admin_phone || '') === adminPhone.value.trim() && data.value) return true
  if (!adminEmail.value.trim() && !adminPhone.value.trim() && !data.value) return true
  try {
    const r = await accountApi.saveExtra(who, adminEmail.value.trim(), adminPhone.value.trim())
    if (data.value) data.value.contacts = r.data.contacts
    return true
  } catch (e) {
    toast.error(e?.response?.data?.detail || loc.t('extra.saveFailed', 'Не удалось сохранить контакты'))
    return false
  }
}
defineExpose({ save })

async function copyPassword() {
  if (await copyText(cred.value?.password || '')) toast.success(loc.t('password.copied', 'Пароль скопирован'))
  else toast.error(loc.t('password.copyFailed', 'Не удалось скопировать — выделите пароль и скопируйте вручную'))
}

async function reset() {
  if (!(await confirm({ title: loc.t('extra.resetConfirm', 'Выдать новый стартовый пароль? Все сессии студента будут закрыты.'), okText: loc.t('extra.reset', 'Сбросить'), danger: true }))) return
  busy.value = true
  try {
    const r = await accountApi.resetCredential(props.login)
    data.value = { ...(data.value || {}), credential: r.data.credential }
    toast.success(loc.t('extra.resetDone', 'Выдан новый стартовый пароль'))
  } catch (e) {
    toast.error(e?.response?.data?.detail || loc.t('extra.resetFailed', 'Не удалось сбросить пароль'))
  } finally { busy.value = false }
}
</script>

<template>
  <div class="space-y-4">
    <p v-if="loadError" class="text-sm text-red">{{ loadError }}</p>

    <!-- Стартовый пароль -->
    <div v-if="login">
      <span class="mb-1 block text-tiny uppercase text-text3">{{ loc.t('extra.startPassword', 'Стартовый пароль') }}</span>
      <div v-if="cred?.state === 'issued'" class="flex gap-2">
        <input :value="cred.password" readonly
               class="h-10 min-w-0 flex-1 rounded-sm border border-border2 bg-card2 px-3 font-mono text-sm text-text outline-none" />
        <button type="button" :title="loc.t('password.copy', 'Скопировать пароль')" :aria-label="loc.t('password.copy', 'Скопировать пароль')"
                class="grid size-10 shrink-0 place-items-center rounded-sm border border-border2 bg-card2 text-text3 hover:border-accent hover:text-accent"
                @click="copyPassword"><Copy class="size-4" /></button>
        <button type="button" :disabled="busy" :title="loc.t('extra.reset', 'Сбросить')" :aria-label="loc.t('extra.reset', 'Сбросить')"
                class="grid size-10 shrink-0 place-items-center rounded-sm border border-border2 bg-card2 text-text3 hover:border-accent hover:text-accent disabled:opacity-50"
                @click="reset"><RotateCw class="size-4" /></button>
      </div>
      <div v-else-if="cred" class="flex flex-wrap items-center justify-between gap-2 rounded-sm border border-border2 bg-card2 px-3 py-2 text-sm">
        <span class="text-text2">{{ cred.state === 'changed'
          ? loc.t('extra.studentChanged', 'Студент сменил пароль')
          : loc.t('extra.notIssued', 'Стартовый пароль не выдавался') }}</span>
        <button type="button" :disabled="busy" class="text-xs font-semibold text-accent hover:underline disabled:opacity-50" @click="reset">
          {{ cred.state === 'changed' ? loc.t('extra.reset', 'Сбросить') : loc.t('extra.issue', 'Выдать') }}</button>
      </div>
      <p class="mt-1 text-tiny text-text3">{{ loc.t('extra.passwordHint', 'Пароль, придуманный самим человеком, не виден никому. Сброс выдаёт новый стартовый.') }}</p>
    </div>

    <!-- Контакты: запись колледжа против указанного самим — только администратору -->
    <template v-if="isAdmin">
      <div class="grid grid-cols-2 gap-2 text-tiny uppercase text-text3">
        <span>{{ loc.t('extra.fromCollege', 'Сообщил колледжу') }}</span>
        <span>{{ loc.t('extra.fromProfile', 'Указал в профиле') }}</span>
      </div>
      <div class="grid grid-cols-2 gap-2">
        <input v-model="adminEmail" type="email" :placeholder="loc.t('account.email', 'Почта')"
               class="h-10 min-w-0 rounded-sm border px-3 text-sm text-text outline-none focus:border-accent"
               :class="stateCls(contacts?.email_state)" />
        <div class="flex h-10 min-w-0 items-center truncate rounded-sm border px-3 text-sm"
             :class="stateCls(contacts?.email_state)">
          <span class="truncate text-text2">{{ contacts?.self_email || '—' }}</span>
          <span v-if="contacts?.self_email_verified" class="ml-1 shrink-0 text-tiny text-accent">✓</span>
        </div>
        <input v-model="adminPhone" inputmode="tel" :placeholder="loc.t('account.phone', 'Телефон')"
               class="h-10 min-w-0 rounded-sm border px-3 text-sm text-text outline-none focus:border-accent"
               :class="stateCls(contacts?.phone_state)" />
        <div class="flex h-10 min-w-0 items-center truncate rounded-sm border px-3 text-sm text-text2"
             :class="stateCls(contacts?.phone_state)">{{ contacts?.self_phone || '—' }}</div>
      </div>
      <p v-if="contacts?.email_state === 'mismatch' || contacts?.phone_state === 'mismatch'" class="text-sm text-red">
        {{ loc.t('extra.mismatch', 'Данные расходятся — уточните у студента, не заходил ли в аккаунт кто-то другой.') }}</p>
      <p class="text-tiny text-text3">{{ contacts?.confirm_channel
        ? loc.t('extra.channel', { to: contacts.confirm_channel })
        : loc.t('extra.noChannel', 'Подтверждение входа по почте не действует: почта не подтверждена или расходится с записью колледжа.') }}</p>
    </template>
  </div>
</template>
