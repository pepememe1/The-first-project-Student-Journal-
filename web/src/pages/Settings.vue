<script setup>
// Settings — «Настройки» (для студента/преподавателя/админа). Сюда вынесены персональные
// настройки, раньше сваленные в «Профиль»: оформление (темы), вход по биометрии (2FA) и
// озвучка Вектора. В «Профиле» остаются только сведения об аккаунте и уведомления.
import { ref, onMounted } from 'vue'
import { Fingerprint, Trash2, ShieldCheck, Volume2, VolumeX, AudioLines, GraduationCap, Check } from '@lucide/vue'
import { authApi, meApi } from '@/api/endpoints'
import { platformAuthenticatorAvailable, enablePasskey } from '@/api/webauthn'
import { useTtsStore } from '@/stores/tts'
import { useAuthStore } from '@/stores/auth'
import { SCALES } from '@/utils/grading'
import Card from '@/components/ui/Card.vue'
import AppButton from '@/components/ui/AppButton.vue'
import ThemeCustomizer from '@/pages/admin/ThemePage.vue'

const tts = useTtsStore()
const auth = useAuthStore()

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
  <div class="space-y-6">
    <!-- Оформление (полный кастомайзер тем: пресеты + свой цвет + режим + расписание). -->
    <div>
      <h2 class="mb-3 font-title text-lg font-extrabold text-text">Оформление</h2>
      <ThemeCustomizer />
    </div>

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
