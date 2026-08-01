<script setup>
// Settings — «Настройки» (для студента/преподавателя/админа). Сюда вынесены персональные
// настройки, раньше сваленные в «Профиль»: оформление (темы), вход по биометрии (2FA) и
// озвучка Вектора. В «Профиле» остаются только сведения об аккаунте и уведомления.
import { ref, onMounted } from 'vue'
import { Fingerprint, Trash2, ShieldCheck, Volume2, VolumeX, AudioLines, GraduationCap, Check, Mic, MicOff, BellOff, RefreshCw, TriangleAlert } from '@lucide/vue'
import { authApi, meApi } from '@/api/endpoints'
import { platformAuthenticatorAvailable, enablePasskey } from '@/api/webauthn'
import { useTtsStore } from '@/stores/tts'
import { useVoiceStore } from '@/stores/voice'
import { useAuthStore } from '@/stores/auth'
import { SCALES } from '@/utils/grading'
import Card from '@/components/ui/Card.vue'
import AppButton from '@/components/ui/AppButton.vue'
import ToggleRow from '@/components/ui/ToggleRow.vue'
import ThemeCustomizer from '@/pages/admin/ThemePage.vue'
import LanguagePicker from '@/components/ui/LanguagePicker.vue'
import { useLocaleStore } from '@/stores/locale'

const tts = useTtsStore()
const auth = useAuthStore()
const voice = useVoiceStore()
const loc = useLocaleStore()

// ── Уведомления: какие категории человек согласен получать ───────────────────────
// Настройка АККАУНТА, а не устройства: решение «слать или нет» принимает сервер до
// отправки (rustore_push.notify_login). Держать её в localStorage было бы бессмысленно —
// пуш уже прилетел бы на телефон, и выключать его было бы поздно.
//
// Ключи обязаны совпадать с rustore_push.ALL_CATEGORIES: сервер знает только их.
const NOTIFY_KINDS = [
  { key: 'grades', label: 'Оценки', hint: 'Новая оценка и исправление уже выставленной' },
  { key: 'homework', label: 'Домашние задания', hint: 'Преподаватель задал работу на дом' },
  { key: 'schedule', label: 'Расписание', hint: 'Замены и правки в расписании вашей группы' },
  { key: 'messages', label: 'Сообщения', hint: 'Личные чаты, группы и каналы' },
  { key: 'events', label: 'Мероприятия', hint: 'Олимпиады, конкурсы, объявления' },
  { key: 'reminders', label: 'Напоминания', hint: 'То, о чём вы сами просили напомнить' },
]
const notify = ref(Object.fromEntries(NOTIFY_KINDS.map((k) => [k.key, true])))
const notifySaving = ref('')
const notifyError = ref('')

async function loadNotify() {
  try {
    const { data } = await meApi.getPrefs()
    const box = data?.prefs?.notify || {}
    // ОТСУТСТВИЕ ключа значит «включено» — ровно как трактует его сервер. Иначе первый
    // же заход в настройки показал бы всё выключенным, хотя уведомления приходят.
    for (const k of NOTIFY_KINDS) {
      notify.value[k.key] = box[k.key] !== false
    }
  } catch { /* не загрузилось — показываем значения по умолчанию */ }
}

async function toggleNotify(key, value) {
  const prev = notify.value[key]
  notify.value[key] = value          // отвечаем сразу: переключатель не должен «залипать»
  notifySaving.value = key
  notifyError.value = ''
  try {
    await meApi.setPrefs({ notify: { ...notify.value } })
  } catch (e) {
    // Откатываем ВИДИМОЕ состояние: молча оставить переключатель в новом положении
    // значит соврать — человек уверен, что отключил, а уведомления продолжают идти.
    notify.value[key] = prev
    notifyError.value = e.response?.data?.detail || 'Не удалось сохранить настройку.'
  } finally {
    notifySaving.value = ''
  }
}

// ── Пуши на этом телефоне: почему их может не быть ───────────────────────────────
// Уведомления — единственная часть продукта, отказ которой невидим: и человек, и мы
// узнаём о нём только по отсутствию сообщений, то есть никогда. Поэтому состояние
// моста показываем явно.
const pushInfo = ref(null)
async function loadPushInfo() {
  try {
    const push = await import('@/services/push')
    if (!push.isAvailable()) return          // сайт/десктоп — раздела просто нет
    pushInfo.value = push.diagnostics() || { has_token: false, error: '', permission: true }
  } catch { pushInfo.value = null }
}

// ── Версия веб-части (обновления «по воздуху») ───────────────────────────────────
const bundle = ref(null)          // { version } | null — вне приложения null
const bundleBusy = ref(false)
const bundleMsg = ref('')
const otaLog = ref([])            // последние события обновления (см. main.js)

async function loadBundle() {
  try {
    const { CapacitorUpdater } = await import('@capgo/capacitor-updater')
    const cur = await CapacitorUpdater.current()
    bundle.value = { version: cur?.bundle?.version || 'встроенная' }
  } catch { bundle.value = null }
  try {
    otaLog.value = JSON.parse(localStorage.getItem('gb_ota_log') || '[]')
  } catch { otaLog.value = [] }
}

async function checkUpdate() {
  bundleBusy.value = true
  bundleMsg.value = ''
  try {
    const { CapacitorUpdater } = await import('@capgo/capacitor-updater')
    const latest = await CapacitorUpdater.getLatest()
    if (!latest?.version || latest.version === bundle.value?.version) {
      bundleMsg.value = 'У вас последняя версия.'
    } else {
      bundleMsg.value = `Доступна версия ${latest.version}. Она установится при следующем запуске приложения.`
    }
  } catch (e) {
    bundleMsg.value = `Не удалось проверить обновление: ${e?.message || e}`
  } finally {
    bundleBusy.value = false
  }
}

// ── Шкала оценивания (§ролей, 3.3.1) — только препод: в ЧЁМ он вводит/видит оценки.
// Средний балл/итоговая всё равно всегда в 5-балльной — сервер сам конвертирует.
const scaleOptions = Object.entries(SCALES).map(([id, s]) => ({ id, label: s.label }))
const gradingScale = ref('5')
const scaleSaving = ref(false)
async function loadGradingScale() {
  try {
    const { data } = await meApi.getPrefs()
    gradingScale.value = data?.prefs?.grading_scale || '5'
  } catch { /* дефолт "5" уже стоит */ }
}
async function pickScale(id) {
  if (id === gradingScale.value || scaleSaving.value) return
  scaleSaving.value = true
  try {
    await meApi.setPrefs({ grading_scale: id })
    gradingScale.value = id
  } finally { scaleSaving.value = false }
}

// ── Озвучка Вектора: 3 режима (Голос → Бубнеж → Выкл) + выбор голоса ──────────────
function cycleVoiceMode() {
  tts.unlock()          // «разбудить» AudioContext из жеста — иначе проба не зазвучит
  tts.cycleMode()
  if (tts.mode === 'mumble') previewMumble()
}
function previewVoice(v) {
  tts.unlock()
  tts.setVoice(v)
  if (tts.mode === 'voice') tts.speak('Привет! Я Вектор. Буду озвучивать ответы этим голосом.')
}
function previewMumble() {
  tts.unlock()
  tts.speak('Привет! Я Вектор.')
}

// ── Вход по биометрии (passkeys / 2FA) ───────────────────────────────────────────
const canBiometric = ref(false)
const passkeys = ref([])
const pkBusy = ref(false)
const pkMsg = ref('')

async function loadPasskeys() {
  try { passkeys.value = (await authApi.webauthnList()).data.credentials || [] } catch { passkeys.value = [] }
}
onMounted(async () => {
  tts.refreshStatus()
  //Список микрофонов — БЕЗ запроса разрешения (ask=false): всплывающее окно «разрешить
  //микрофон» при простом заходе в настройки выглядит как попытка подслушать. Названия
  //подтянутся по кнопке «Обновить список», то есть по осознанному действию.
  voice.refresh(false)
  loadNotify()
  loadPushInfo()
  loadBundle()
  try { canBiometric.value = await platformAuthenticatorAvailable() } catch { canBiometric.value = false }
  if (canBiometric.value) await loadPasskeys()
  if (auth.role === 'teacher') await loadGradingScale()
})

async function addPasskey() {
  pkBusy.value = true; pkMsg.value = ''
  try {
    const name = navigator.platform || 'Это устройство'
    await enablePasskey(name)
    pkMsg.value = 'Готово! Теперь можно входить по Face ID / отпечатку.'
    await loadPasskeys()
  } catch (e) {
    if (e?.name === 'NotAllowedError' || e?.name === 'AbortError') pkMsg.value = ''
    else pkMsg.value = e.response?.data?.detail || 'Не удалось включить биометрию.'
  } finally { pkBusy.value = false }
}
async function removePasskey(id) {
  pkBusy.value = true
  try { await authApi.webauthnDelete(id); await loadPasskeys() } finally { pkBusy.value = false }
}
function fmtDate(s) { return (s || '').slice(0, 10) }
</script>

<template>
  <!-- flex+gap, а НЕ space-y-*: в Tailwind 4 `space-y` разворачивается в правило с
       нулевой специфичностью, и любой конкурирующий margin съедает промежуток без следа
       в разметке (уже ловили на статистике студента). -->
  <div class="flex flex-col gap-6">
    <!-- Оформление (полный кастомайзер тем: пресеты + свой цвет + режим + расписание). -->
    <div>
      <h2 class="mb-3 font-title text-lg font-extrabold text-text">Оформление</h2>
      <ThemeCustomizer />
    </div>

    <!-- Язык интерфейса. Выбор делается ещё на экране входа (там глобус), здесь его
         можно сменить и, главное, ВЫКЛЮЧИТЬ перевод — не теряя выбранный язык. -->
    <Card :title="loc.t('settings.language')" :subtitle="loc.t('settings.languageHint')" pad>
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div class="flex flex-wrap gap-2">
          <button v-for="l in loc.locales" :key="l.code" type="button"
                  class="flex items-center gap-2 rounded-lg border px-3 py-2 text-sm transition-colors"
                  :class="l.code === loc.locale && loc.translateUi
                    ? 'border-accent bg-accent-glow text-text' : 'border-border text-text2 hover:border-accent'"
                  @click="loc.set(l.code)">
            <span class="text-base leading-none">{{ l.flag }}</span>{{ l.name }}
          </button>
        </div>
        <LanguagePicker />
      </div>

      <div class="mt-4">
        <ToggleRow :label="loc.t('settings.languageOff')"
                   :hint="loc.t('settings.languageOffHint')"
                   :model-value="!loc.translateUi"
                   @update:model-value="(v) => loc.setTranslateUi(!v)" />
      </div>
    </Card>

    <!-- Уведомления: что присылать. Настройка АККАУНТА — решение принимает сервер до
         отправки, поэтому она одинакова на телефоне, сайте и десктопе. -->
    <Card title="Уведомления" subtitle="Что присылать на телефон">
      <div class="flex flex-col gap-2">
        <ToggleRow v-for="k in NOTIFY_KINDS" :key="k.key"
                   :label="k.label" :hint="k.hint"
                   :model-value="notify[k.key]"
                   :disabled="notifySaving === k.key"
                   @update:model-value="(v) => toggleNotify(k.key, v)" />
      </div>

      <p v-if="notifyError" class="mt-3 text-sm text-red">{{ notifyError }}</p>
      <div class="mt-3 flex items-start gap-2.5 rounded-lg border border-border bg-card2 px-3 py-2.5 text-xs text-text3">
        <BellOff class="mt-0.5 size-4 shrink-0" />
        <p>Выключенное перестаёт приходить на телефон, но остаётся во вкладке
           «Уведомления» — историю оценок и заданий выключатель не стирает.</p>
      </div>

      <!-- Состояние пушей на ЭТОМ телефоне. Отказ доставки иначе невидим: и человек,
           и мы узнаём о нём только по отсутствию уведомлений, то есть никогда. -->
      <div v-if="pushInfo" class="mt-3">
        <div v-if="pushInfo.has_token && pushInfo.permission"
             class="flex items-start gap-2.5 rounded-lg border border-border bg-card2 px-3 py-2.5 text-xs text-text3">
          <ShieldCheck class="mt-0.5 size-4 shrink-0 text-accent" />
          <p>Этот телефон подключён к уведомлениям.</p>
        </div>
        <div v-else class="flex items-start gap-2.5 rounded-lg border border-red/40 bg-card2 px-3 py-2.5 text-xs text-text2">
          <TriangleAlert class="mt-0.5 size-4 shrink-0 text-red" />
          <p v-if="!pushInfo.permission">
            Показ уведомлений запрещён в настройках телефона — разрешите их для
            GradeBookAI, иначе ничего не придёт.
          </p>
          <p v-else>
            Телефон пока не подключён к уведомлениям.
            <template v-if="pushInfo.error"> Причина: {{ pushInfo.error }}.</template>
            Доставку обеспечивает RuStore — на телефоне без него уведомления работать
            не будут.
          </p>
        </div>
      </div>
    </Card>

    <!-- Версия веб-части. Только в приложении: на сайте и десктопе обновление приезжает
         обычной загрузкой страницы, и показывать номер бандла там не о чем. -->
    <Card v-if="bundle" title="Версия приложения"
          subtitle="Интерфейс обновляется сам, без переустановки из магазина">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <p class="text-sm text-text2">Установлена: <span class="font-semibold text-text">{{ bundle.version }}</span></p>
        <AppButton variant="ghost" :disabled="bundleBusy" @click="checkUpdate">
          <RefreshCw class="mr-2 inline size-4" />{{ bundleBusy ? 'Проверяем…' : 'Проверить обновление' }}
        </AppButton>
      </div>
      <p v-if="bundleMsg" class="mt-3 text-sm text-text3">{{ bundleMsg }}</p>

      <!-- Ход последних обновлений. Нужен, пока не выяснена причина, по которой бандл
           скачивается и не приживается: она остаётся на устройстве и в логи сервера не
           попадает. Человеку с телефоном достаточно прочитать строку и назвать её. -->
      <details v-if="otaLog.length" class="mt-3">
        <summary class="cursor-pointer text-xs text-text3">Что происходило с обновлениями</summary>
        <ul class="mt-2 flex flex-col gap-1 font-mono text-tiny text-text3">
          <li v-for="(e, i) in otaLog" :key="i" class="break-all">
            {{ e.at?.slice(5, 16).replace('T', ' ') }} · {{ e.kind }}
            <template v-if="e.data && Object.keys(e.data).length"> · {{ JSON.stringify(e.data) }}</template>
          </li>
        </ul>
      </details>
    </Card>

    <!-- Озвучка Вектора: Голос → Бубнеж → Выкл. -->
    <Card title="Озвучка Вектора" subtitle="Как Вектор проговаривает свои ответы">
      <button type="button"
              class="flex w-full items-center gap-3 rounded-md border border-border p-3 text-left transition-colors hover:border-accent"
              @click="cycleVoiceMode">
        <span class="grid size-10 shrink-0 place-items-center rounded-md"
              :class="tts.mode === 'off' ? 'bg-card2 text-text3' : 'bg-accent-glow text-accent'">
          <VolumeX v-if="tts.mode === 'off'" class="size-5" />
          <AudioLines v-else-if="tts.mode === 'mumble'" class="size-5" />
          <Volume2 v-else class="size-5" />
        </span>
        <span class="min-w-0 flex-1">
          <span class="block text-sm font-semibold text-text">{{ tts.modeLabel }}</span>
          <span class="block text-xs text-text3">Нажмите, чтобы переключить: Голос → Бубнеж → Выкл</span>
        </span>
      </button>

      <!-- Выбор голоса — только в режиме «Голос». -->
      <div v-if="tts.mode === 'voice'" class="mt-4">
        <p class="mb-2 text-sm font-medium text-text2">Голос</p>
        <div class="flex gap-2">
          <button type="button" @click="previewVoice('male')"
                  class="flex-1 rounded-md border p-3 text-left transition-colors"
                  :class="tts.voice === 'male' ? 'border-accent bg-accent-glow' : 'border-border hover:border-accent'">
            <span class="block text-sm font-semibold text-text">Мужской</span>
            <span class="block text-xs text-text3">По умолчанию · нажмите, чтобы услышать</span>
          </button>
          <button type="button" @click="previewVoice('female')"
                  class="flex-1 rounded-md border p-3 text-left transition-colors"
                  :class="tts.voice === 'female' ? 'border-accent bg-accent-glow' : 'border-border hover:border-accent'">
            <span class="block text-sm font-semibold text-text">Женский</span>
            <span class="block text-xs text-text3">Нажмите, чтобы услышать</span>
          </button>
        </div>
      </div>

      <!-- Бубнеж — короткое пояснение + проба. -->
      <div v-else-if="tts.mode === 'mumble'" class="mt-4 flex items-center justify-between gap-3 rounded-md border border-border bg-card2 px-3 py-2.5">
        <p class="text-xs text-text3">Имитация речи короткими сигналами (как голоса в играх), без интернета.</p>
        <AppButton variant="ghost" @click="previewMumble">Проверить</AppButton>
      </div>
    </Card>

    <!-- Голосовой ввод: тумблер + выбор микрофона (настройка ЭТОГО устройства). -->
    <Card title="Голосовой ввод" subtitle="Микрофон для «Вектора»: сказать вместо набора текста">
      <div v-if="!voice.supported"
           class="flex items-start gap-3 rounded-lg border border-border bg-card2 px-3 py-2.5 text-sm text-text3">
        <MicOff class="mt-0.5 size-4 shrink-0" />
        <p>Это устройство не умеет записывать звук — голосовой ввод недоступен.</p>
      </div>

      <template v-else>
        <button type="button" @click="voice.toggle()"
                class="flex w-full items-center gap-3 rounded-lg border border-border bg-card2 px-3 py-2.5 text-left transition-colors hover:border-accent">
          <span class="grid size-10 shrink-0 place-items-center rounded-md"
                :class="voice.enabled ? 'bg-accent-glow text-accent' : 'bg-card2 text-text3'">
            <Mic v-if="voice.enabled" class="size-5" />
            <MicOff v-else class="size-5" />
          </span>
          <span class="flex-1">
            <span class="block text-sm font-semibold text-text">
              {{ voice.enabled ? 'Включён' : 'Выключен' }}
            </span>
            <span class="block text-xs text-text3">
              {{ voice.enabled
                 ? 'Кнопка 🎤 доступна рядом с полем вопроса'
                 : 'Кнопка микрофона скрыта' }}
            </span>
          </span>
          <span class="relative h-6 w-11 shrink-0 rounded-full transition-colors"
                :class="voice.enabled ? 'bg-accent' : 'bg-border2'">
            <span class="absolute top-0.5 size-5 rounded-full bg-white transition-all"
                  :class="voice.enabled ? 'left-[22px]' : 'left-0.5'" />
          </span>
        </button>

        <!-- Выбор устройства. Названия микрофонов браузер раскрывает только после
             разрешения, поэтому запрашиваем его кнопкой — то есть из жеста человека. -->
        <div v-if="voice.enabled" class="mt-4">
          <div class="mb-2 flex items-center justify-between gap-2">
            <span class="text-sm font-medium text-text2">Микрофон</span>
            <button type="button" :disabled="voice.loading" @click="voice.refresh(true)"
                    class="text-xs text-accent hover:underline disabled:opacity-50">
              {{ voice.loading ? 'Ищем…' : 'Обновить список' }}
            </button>
          </div>

          <select :value="voice.deviceId" @change="voice.setDevice($event.target.value)"
                  class="h-10 w-full rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent">
            <option value="">Как в системе</option>
            <option v-for="d in voice.devices" :key="d.deviceId" :value="d.deviceId">{{ d.label }}</option>
          </select>

          <p v-if="voice.denied" class="mt-2 text-xs text-red">
            Доступ к микрофону запрещён. Разрешите запись в настройках браузера или системы.
          </p>
          <p v-else-if="!voice.devices.length" class="mt-2 text-xs text-text3">
            Нажмите «Обновить список», чтобы выбрать конкретный микрофон — до разрешения
            браузер не сообщает их названия.
          </p>
          <p v-else class="mt-2 text-xs text-text3">
            Речь распознаёт сервер, с которого открыт интерфейс. Внутри программы это
            локальный сервер на вашем компьютере — запись его не покидает.
          </p>
        </div>
      </template>
    </Card>

    <!-- Шкала оценивания — только преподаватель. -->
    <Card v-if="auth.role === 'teacher'" title="Шкала оценивания"
          subtitle="В чём вы вводите и видите оценки за практики/ДЗ. Средний балл и итоговая — всегда в 5-балльной">
      <div class="grid grid-cols-1 gap-2 sm:grid-cols-2">
        <button v-for="s in scaleOptions" :key="s.id" type="button" :disabled="scaleSaving"
                @click="pickScale(s.id)"
                class="flex items-center gap-2.5 rounded-md border p-3 text-left transition-colors disabled:opacity-50"
                :class="gradingScale === s.id ? 'border-accent bg-accent-glow' : 'border-border hover:border-accent'">
          <GraduationCap class="size-4 shrink-0 text-accent" />
          <span class="flex-1 text-sm font-medium text-text">{{ s.label }}</span>
          <Check v-if="gradingScale === s.id" class="size-4 shrink-0 text-accent" />
        </button>
      </div>
    </Card>

    <!-- Вход по биометрии / 2FA — виден только на устройствах с Face ID/отпечатком. -->
    <Card v-if="canBiometric" title="Вход по биометрии"
          subtitle="Быстрый вход по Face ID, отпечатку или ключу доступа — без пароля">
      <div class="flex items-start gap-3 rounded-lg border border-border bg-card2 px-3 py-2.5 text-sm text-text3">
        <ShieldCheck class="mt-0.5 size-4 shrink-0 text-accent" />
        <p>Приватный ключ хранится в защищённом чипе устройства и никогда его не покидает.
           Сервер знает только публичную часть. Пароль при таком входе не используется.</p>
      </div>

      <ul v-if="passkeys.length" class="mt-4 space-y-2">
        <li v-for="k in passkeys" :key="k.id"
            class="flex items-center justify-between rounded-md border border-border px-3 py-2">
          <div class="flex items-center gap-2.5 text-sm">
            <Fingerprint class="size-4 text-accent" />
            <span class="font-medium text-text">{{ k.device_name || 'Устройство' }}</span>
            <span class="text-tiny text-text3">добавлен {{ fmtDate(k.created_at) }}</span>
          </div>
          <button type="button" :disabled="pkBusy" class="text-text3 transition-colors hover:text-red disabled:opacity-50"
                  aria-label="Удалить ключ" @click="removePasskey(k.id)">
            <Trash2 class="size-4" />
          </button>
        </li>
      </ul>
      <p v-else class="mt-4 text-sm text-text3">Пока нет ни одного ключа на этом аккаунте.</p>

      <div class="mt-4 flex flex-wrap items-center gap-3">
        <AppButton variant="green" :disabled="pkBusy" @click="addPasskey">
          <Fingerprint class="mr-2 inline size-4" />{{ pkBusy ? 'Настраиваем…' : 'Добавить это устройство' }}
        </AppButton>
        <p v-if="pkMsg" class="text-sm font-medium text-accent">{{ pkMsg }}</p>
      </div>
    </Card>
  </div>
</template>
