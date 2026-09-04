<script setup>
/**
 * MfaCard.vue — настройка второго фактора входа (код из приложения-аутентификатора).
 *
 * ⚠️ Отдельный компонент, а не ещё один блок в Settings.vue: там уже 600+ строк, и
 * состояние настройки (секрет, шаг подтверждения, коды восстановления) живёт своей
 * жизнью. Смешивать его с темой и шкалой оценок — верный способ однажды показать
 * коды восстановления не тому.
 *
 * ━━ ДВА ПУТИ ДОБАВИТЬ АККАУНТ, И ВЫБИРАЕТ ИХ УСТРОЙСТВО ━━━━━━━━━━━━━━━━━━━━━━━━━━
 * Замечание Ярослава дословно (02.09.2026): «сделать чтобы грейдбук сам перекидывал в
 * google приложение и там сам добавлялся, а то если куаркод на экране то чтобы его
 * отсканить нужен другой телефон, а вот на пк да нужен куаркод».
 *
 *   • НА ТЕЛЕФОНЕ — крупная кнопка со ссылкой `otpauth://`. Google Authenticator (и
 *     любой другой аутентификатор) перехватывает эту схему и заводит запись САМ,
 *     ничего вводить не нужно. QR-код на своём же экране бесполезен: чтобы его снять,
 *     нужен второй телефон;
 *   • НА КОМПЬЮТЕРЕ — QR-код. Ссылку открывать нечем, аутентификатор живёт на
 *     телефоне, и без кода остаётся переписывать тридцать два символа руками.
 *
 * Ни один из путей не убран совсем: на телефоне QR разворачивается по ссылке (вдруг
 * аутентификатор стоит на другом устройстве), на компьютере остаётся и ссылка, и сам
 * ключ. Скрыт ровно тот, который в этом случае мешает.
 *
 * 🔒 QR РИСУЕМ САМИ (`server/app/qr.py`), а не сторонним сервисом и не библиотекой.
 * В картинку кодируется СЕКРЕТ второго фактора: запрос к генератору вроде
 * `api.qrserver.com` — это отправка секрета третьей стороне, притом иностранной
 * (п. 5.6.1 политики ВСГУТУ). Сервер присылает не разметку, а размер и `d` для
 * одного `<path>` — вставлять ответ сервера через `v-html` не приходится.
 */
import { ref, onMounted, computed } from 'vue'
import { authApi } from '@/api/endpoints'
import { isHandheld } from '@/utils/device.js'

const status = ref({ enabled: false, required: false, recovery_left: 0 })
const busy = ref(false)
const message = ref('')
const error = ref('')

//Шаг настройки: '' — ничего, 'setup' — показали секрет, 'codes' — показали коды.
const step = ref('')
const secret = ref('')
const uri = ref('')
const qr = ref(null)          // {size, path} — матрица кода, посчитанная сервером
const code = ref('')
const recoveryCodes = ref([])
const disableCode = ref('')

//На телефоне ведущий путь — кнопка в приложение, на компьютере — QR. Второй путь не
//исчезает, а сворачивается под ссылку: аутентификатор бывает и на другом устройстве.
const handheld = isHandheld()
const showQr = ref(false)
const qrVisible = computed(() => !handheld || showQr.value)

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
    //QR может не прийти от старого сервера — тогда работают ключ и ссылка. Настройка
    //от этого не ломается, просто становится менее удобной.
    qr.value = data.qr && data.qr.path ? data.qr : null
    showQr.value = false
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
    //Секрет и его QR убираем с экрана сразу: они больше не нужны, а висеть на общем
    //компьютере колледжа им незачем.
    secret.value = ''
    uri.value = ''
    qr.value = null
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

    <!-- Шаг 1: перенос аккаунта в приложение -->
    <div v-if="step === 'setup'" class="space-y-3">
      <!-- ТЕЛЕФОН: одна кнопка, приложение заводит запись само. -->
      <template v-if="handheld">
        <p class="text-sm text-text3">
          Нажмите — откроется приложение-аутентификатор и добавит аккаунт само.
          Вводить ничего не нужно.
        </p>
        <a :href="uri"
           class="block rounded-md bg-accent px-4 py-3 text-center text-sm font-semibold text-white">
          Добавить в приложение-аутентификатор
        </a>
        <p class="text-xs text-text3">
          Ничего не открылось — значит аутентификатор ещё не установлен. Подойдёт любой
          (Google Authenticator, Яндекс Ключ, Aegis): мы никуда ничего не отправляем,
          код считается на самом телефоне.
        </p>
      </template>

      <!-- КОМПЬЮТЕР: QR, потому что ссылку тут открывать нечем. -->
      <p v-else class="text-sm text-text3">
        Откройте приложение-аутентификатор на телефоне и наведите камеру на код.
      </p>

      <!-- ⚠️ Цвета ЖЁСТКИЕ, а не токены темы, и это осознанное исключение из правила
           «не хардкодить цвета». Код читает камера, а не человек: на тёмной теме
           тёмный код на тёмном фоне не распознаётся вовсе, и выглядит это как
           «телефон не видит», а не как ошибка вёрстки. Белое поле обязательно. -->
      <div v-if="qr && qrVisible" class="flex justify-center">
        <svg :viewBox="`0 0 ${qr.size} ${qr.size}`" role="img"
             aria-label="QR-код для приложения-аутентификатора"
             class="h-56 w-56 rounded-md sm:h-64 sm:w-64" shape-rendering="crispEdges">
          <rect :width="qr.size" :height="qr.size" fill="#ffffff" />
          <path :d="qr.path" fill="#000000" />
        </svg>
      </div>

      <!-- Второй путь не убран, а свёрнут: аутентификатор бывает на другом устройстве. -->
      <button v-if="handheld && qr && !showQr" type="button"
              class="text-sm text-accent underline" @click="showQr = true">
        Показать QR-код (если аутентификатор на другом устройстве)
      </button>

      <details class="text-sm">
        <summary class="cursor-pointer text-text3">Ввести ключ вручную</summary>
        <div class="mt-2 flex flex-wrap items-center gap-2">
          <code class="select-all break-all rounded-md border border-border bg-card2 px-3 py-2 text-sm text-text">{{ secret }}</code>
          <button type="button" class="text-sm text-accent underline" @click="copy(secret)">Скопировать</button>
        </div>
      </details>

      <div class="flex flex-wrap items-center gap-2 border-t border-border pt-3">
        <span class="w-full text-sm text-text3">
          Приложение показывает шестизначный код и меняет его каждые 30 секунд.
          Введите текущий, чтобы включить второй фактор.
        </span>
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
    <div v-else class="space-y-3">
      <!-- Где ещё спросят код. Раньше об этом не говорилось нигде, и человек узнавал
           о требовании кода при смене пароля в самый неподходящий момент. -->
      <p v-if="status.enabled" class="text-sm text-text3">
        Код спрашивается при входе, при смене пароля по ссылке из письма и при
        продлении сессии, если к аккаунту подбирали пароль.
      </p>

      <div class="flex flex-wrap items-center gap-3">
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
    </div>

    <p v-if="error" class="text-sm text-red">{{ error }}</p>
    <p v-else-if="message" class="text-sm text-text3">{{ message }}</p>
  </div>
</template>
