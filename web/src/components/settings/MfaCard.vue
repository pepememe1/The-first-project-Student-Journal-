<script setup>
/**
 * MfaCard.vue — настройка второго фактора входа (код из приложения).
 *
 * ⚠️ Отдельный компонент, а не ещё один блок в Settings.vue: там уже 600+ строк, и
 * состояние настройки (секрет, шаг подтверждения, коды восстановления) живёт своей
 * жизнью. Смешивать его с темой и шкалой оценок — верный способ однажды показать
 * коды восстановления не тому.
 *
 * 🔒 QR-кода здесь НЕТ намеренно, и это осознанный размен. Рисовать его пришлось бы
 * либо сторонней библиотекой (лишний пакет в поставке, лишняя строка в SBOM и лишний
 * вопрос на приёмке в реестр), либо через внешний сервис — а это отправка секрета
 * второго фактора чужому серверу, то есть ровно то, от чего второй фактор защищает.
 * Вместо него — секрет крупно, с кнопкой копирования, и ссылка `otpauth://`, которую
 * телефон открывает сам. Аутентификаторы принимают ручной ввод все без исключения.
 */
import { ref, onMounted } from 'vue'
import { authApi } from '@/api/endpoints'

const status = ref({ enabled: false, required: false, recovery_left: 0 })
const busy = ref(false)
const message = ref('')
const error = ref('')

//Шаг настройки: '' — ничего, 'setup' — показали секрет, 'codes' — показали коды.
const step = ref('')
const secret = ref('')
const uri = ref('')
const code = ref('')
const recoveryCodes = ref([])
const disableCode = ref('')

async function load() {
  try {
    status.value = (await authApi.mfaStatus()).data
  } catch {
    /* статус — не условие работы страницы */
  }
}
onMounted(load)

async function begin() {
  busy.value = true; error.value = ''; message.value = ''
  try {
    const { data } = await authApi.mfaSetup()
    secret.value = data.secret
    uri.value = data.uri
    step.value = 'setup'
  } catch (e) {
    error.value = e.response?.data?.detail || 'Не удалось начать настройку'
  } finally { busy.value = false }
}

async function confirm() {
  busy.value = true; error.value = ''
  try {
    const { data } = await authApi.mfaConfirm(code.value.replace(/\D/g, ''))
    recoveryCodes.value = data.recovery_codes || []
    step.value = 'codes'
    code.value = ''
    //Секрет с экрана убираем сразу: он больше не нужен, а висеть на общем
    //компьютере колледжа ему незачем.
    secret.value = ''
    uri.value = ''
    await load()
  } catch (e) {
    error.value = e.response?.data?.detail || 'Код не подошёл'
  } finally { busy.value = false }
}

async function disable() {
  busy.value = true; error.value = ''
  try {
    await authApi.mfaDisable(disableCode.value.trim())
    disableCode.value = ''
    message.value = 'Второй фактор отключён'
    await load()
  } catch (e) {
    error.value = e.response?.data?.detail || 'Код не подошёл'
  } finally { busy.value = false }
}

async function regenerate() {
  busy.value = true; error.value = ''
  try {
    const { data } = await authApi.mfaRegenerate(disableCode.value.trim())
    recoveryCodes.value = data.recovery_codes || []
    step.value = 'codes'
    disableCode.value = ''
    await load()
  } catch (e) {
    error.value = e.response?.data?.detail || 'Код не подошёл'
  } finally { busy.value = false }
}

function copy(text) {
  navigator.clipboard?.writeText(text).then(
    () => { message.value = 'Скопировано' },
    () => { message.value = 'Скопировать не вышло — выделите вручную' },
  )
}

function downloadCodes() {
  //Файл собираем в браузере: коды не должны ходить через сервер ещё раз.
  const body = [
    'GradeBookAI — коды восстановления второго фактора',
    'Каждый код срабатывает ОДИН раз. Храните отдельно от телефона.',
    '',
    ...recoveryCodes.value,
  ].join('\n')
  const url = URL.createObjectURL(new Blob([body], { type: 'text/plain;charset=utf-8' }))
  const a = document.createElement('a')
  a.href = url
  a.download = 'gradebook-recovery-codes.txt'
  a.click()
  URL.revokeObjectURL(url)
}
</script>

<template>
  <div class="space-y-4">
    <!-- Обязательность объявляем СРАЗУ и до настройки: администратор должен понимать,
         почему разделы закрыты, а не искать, кто отобрал у него доступ. -->
    <div v-if="status.required && !status.enabled"
         class="flex items-start gap-3 rounded-lg border border-red/40 bg-red/10 px-3 py-2.5 text-sm">
      <span class="text-text">
        Для роли администратора второй фактор <b>обязателен</b>. Пока он не настроен,
        административные разделы отвечают отказом.
      </span>
    </div>

    <div v-if="status.enabled"
         class="flex items-start gap-3 rounded-lg border border-border bg-card2 px-3 py-2.5 text-sm text-text3">
      <span>
        Второй фактор включён. Осталось кодов восстановления:
        <b :class="status.recovery_left <= 2 ? 'text-red' : 'text-text'">{{ status.recovery_left }}</b>.
        <template v-if="status.recovery_left <= 2">
          Их стоит перевыпустить — когда они закончатся, потерянный телефон будет
          означать обращение к администратору сервера.
        </template>
      </span>
    </div>

    <!-- Шаг 1: секрет -->
    <div v-if="step === 'setup'" class="space-y-3">
      <p class="text-sm text-text3">
        Добавьте аккаунт в приложение-аутентификатор — вручную по ключу ниже или
        по ссылке, если открываете эту страницу с телефона.
      </p>
      <div class="flex flex-wrap items-center gap-2">
        <code class="select-all break-all rounded-md border border-border bg-card2 px-3 py-2 text-sm text-text">{{ secret }}</code>
        <button type="button" class="text-sm text-accent underline" @click="copy(secret)">Скопировать</button>
      </div>
      <a :href="uri" class="inline-block text-sm text-accent underline">Открыть в приложении на этом устройстве</a>

      <div class="flex flex-wrap items-center gap-2 pt-2">
        <input v-model="code" inputmode="numeric" maxlength="6" placeholder="000000"
               class="h-11 w-32 rounded-sm border border-border2 bg-card2 px-3 text-center text-lg tracking-widest text-text outline-none focus:border-accent" />
        <button type="button" class="rounded-md bg-accent px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50"
                :disabled="busy || code.replace(/\D/g, '').length < 6" @click="confirm">
          Подтвердить
        </button>
        <button type="button" class="text-sm text-text3 underline" @click="step = ''">Отмена</button>
      </div>
    </div>

    <!-- Шаг 2: коды восстановления. Показываются ОДИН раз — на сервере только хеши. -->
    <div v-else-if="step === 'codes'" class="space-y-3">
      <p class="text-sm text-text">
        <b>Сохраните коды восстановления.</b> Они показываются один раз: на сервере
        хранятся только их отпечатки, и повторить показ невозможно.
      </p>
      <ul class="grid grid-cols-2 gap-2 rounded-md border border-border bg-card2 p-3 sm:grid-cols-3">
        <li v-for="c in recoveryCodes" :key="c" class="select-all font-mono text-sm text-text">{{ c }}</li>
      </ul>
      <div class="flex flex-wrap gap-3">
        <button type="button" class="text-sm text-accent underline" @click="downloadCodes">Скачать файлом</button>
        <button type="button" class="text-sm text-accent underline" @click="copy(recoveryCodes.join('\n'))">Скопировать</button>
        <button type="button" class="text-sm text-text3 underline" @click="step = ''">Я сохранил</button>
      </div>
    </div>

    <!-- Обычное состояние -->
    <div v-else class="flex flex-wrap items-center gap-3">
      <button v-if="!status.enabled" type="button" :disabled="busy"
              class="rounded-md bg-accent px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50"
              @click="begin">
        {{ busy ? 'Настраиваем…' : 'Настроить второй фактор' }}
      </button>

      <template v-else>
        <input v-model="disableCode" placeholder="Код из приложения"
               class="h-11 w-44 rounded-sm border border-border2 bg-card2 px-3 text-text outline-none focus:border-accent" />
        <button type="button" class="text-sm text-accent underline" :disabled="busy || !disableCode"
                @click="regenerate">
          Перевыпустить коды восстановления
        </button>
        <button type="button" class="text-sm text-red underline" :disabled="busy || !disableCode"
                @click="disable">
          Отключить
        </button>
      </template>
    </div>

    <p v-if="error" class="text-sm text-red">{{ error }}</p>
    <p v-else-if="message" class="text-sm text-text3">{{ message }}</p>
  </div>
</template>
