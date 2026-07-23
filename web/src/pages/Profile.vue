<script setup>
// Profile — «Профиль» (порт dashboards "profile"): карточка пользователя + оформление
// (тема роумится через /me/prefs, поэтому доступна каждому — как у студента в проге).
import { computed, ref, onMounted } from 'vue'
import { Check, Fingerprint, Trash2, ShieldCheck, Volume2, VolumeX } from '@lucide/vue'
import { useAuthStore } from '@/stores/auth'
import { useThemeStore } from '@/stores/theme'
import { useTtsStore } from '@/stores/tts'
import { PRESETS, swatchColors } from '@/theme/palette'
import { authApi, meApi } from '@/api/endpoints'
import { platformAuthenticatorAvailable, enablePasskey } from '@/api/webauthn'
import Card from '@/components/ui/Card.vue'
import AppButton from '@/components/ui/AppButton.vue'
import NotificationsInbox from '@/components/NotificationsInbox.vue'

const auth = useAuthStore()
const theme = useThemeStore()
const tts = useTtsStore()

// Проба голоса при выборе — короткая фраза от лица Вектора, чтобы услышать разницу.
function previewVoice(v) {
  tts.setVoice(v)
  if (tts.enabled) tts.speak('Привет! Я Вектор. Буду озвучивать ответы этим голосом.')
}

// Вкладки профиля: настройки и почта уведомлений.
const tab = ref('profile')
const unread = ref(0)
async function loadUnread() {
  try { unread.value = (await meApi.unreadCount()).data.unread || 0 } catch { unread.value = 0 }
}
// Открыли «Уведомления» — значок обнулять сразу нельзя: письма станут прочитанными
// только по мере открытия. Пересчитываем по возвращении на вкладку профиля.
function switchTab(next) {
  tab.value = next
  if (next === 'profile') loadUnread()
}
const ROLE = { student: 'Студент', teacher: 'Преподаватель', admin: 'Администратор' }
const initial = computed(() => (auth.user?.name || '?').trim().charAt(0).toUpperCase())
const currentId = computed(() => theme.spec.id)
// Трёхцветный круг как в десктопе (_Swatch): акцент — верх, вторичный — низ-лево,
// поверхность режима — низ-право.
function swatchStyle(id) {
  const [accent, accent2, surface] = swatchColors({ ...theme.spec, id })
  return {
    background: `conic-gradient(${accent} 0deg 90deg, ${surface} 90deg 180deg, `
              + `${accent2} 180deg 270deg, ${accent} 270deg 360deg)`,
  }
}

// ── Вход по биометрии (passkeys) ────────────────────────────────────────────────
const canBiometric = ref(false)
const passkeys = ref([])
const pkBusy = ref(false)
const pkMsg = ref('')

async function loadPasskeys() {
  try { passkeys.value = (await authApi.webauthnList()).data.credentials || [] } catch { passkeys.value = [] }
}
onMounted(async () => {
  loadUnread()
  tts.refreshStatus()
  try { canBiometric.value = await platformAuthenticatorAvailable() } catch { canBiometric.value = false }
  if (canBiometric.value) await loadPasskeys()
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
    <Card>
      <div class="flex items-center gap-4">
        <div class="grid size-16 place-items-center rounded-full bg-accent text-2xl font-extrabold text-white">{{ initial }}</div>
        <div>
          <p class="font-title text-xl font-extrabold text-text">{{ auth.user?.name }}</p>
          <p class="text-sm text-text3">{{ ROLE[auth.role] }} · {{ auth.user?.login }}</p>
        </div>
      </div>
    </Card>

    <!-- Вкладки: настройки профиля и почта уведомлений. -->
    <div class="flex gap-1 border-b border-border">
      <button v-for="t in [{ id: 'profile', label: 'Профиль' }, { id: 'inbox', label: 'Уведомления' }]"
              :key="t.id" type="button"
              class="-mb-px border-b-2 px-4 py-2 text-sm font-medium transition-colors"
              :class="tab === t.id
                ? 'border-accent text-accent'
                : 'border-transparent text-text3 hover:text-text'"
              @click="switchTab(t.id)">
        {{ t.label }}
        <span v-if="t.id === 'inbox' && unread"
              class="ml-1.5 inline-grid min-w-4 place-items-center rounded-full bg-accent px-1 text-tiny font-bold text-white">
          {{ unread }}
        </span>
      </button>
    </div>

    <Card v-if="tab === 'inbox'" title="Уведомления"
          subtitle="Оценки и изменения расписания">
      <NotificationsInbox />
    </Card>

    <Card v-if="tab === 'profile'" title="Оформление" subtitle="Тема сохраняется за вашим аккаунтом">
      <div class="mb-4 flex gap-2">
        <AppButton :variant="theme.isDark ? 'ghost' : 'green'" @click="theme.setMode('light')">Светлая</AppButton>
        <AppButton :variant="theme.isDark ? 'green' : 'ghost'" @click="theme.setMode('dark')">Тёмная</AppButton>
      </div>
      <div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <button v-for="p in PRESETS" :key="p.id" type="button"
                class="flex items-center gap-2.5 rounded-md border p-2.5 text-left transition-colors"
                :class="currentId === p.id ? 'border-accent bg-accent-glow' : 'border-border hover:border-accent'"
                @click="theme.setPreset(p.id)">
          <span class="relative size-7 shrink-0 rounded-full border border-black/10" :style="swatchStyle(p.id)">
            <span v-if="currentId === p.id"
                  class="absolute -right-1 -top-1 grid size-3.5 place-items-center rounded-full bg-accent text-white ring-2 ring-card">
              <Check class="size-2" />
            </span>
          </span>
          <span class="truncate text-xs font-medium text-text">{{ p.name }}</span>
        </button>
      </div>
    </Card>

    <!-- Озвучка Вектора: включение и выбор голоса. Настройка устройства (хранится
         локально), поэтому доступна каждой роли. По умолчанию включена, голос мужской. -->
    <Card v-if="tab === 'profile'" title="Озвучка Вектора"
          subtitle="Вектор проговаривает свои ответы вслух">
      <div class="mb-4 flex gap-2">
        <AppButton :variant="tts.enabled ? 'green' : 'ghost'" @click="tts.setEnabled(true)">
          <Volume2 class="mr-2 inline size-4" />Включена
        </AppButton>
        <AppButton :variant="tts.enabled ? 'ghost' : 'green'" @click="tts.setEnabled(false)">
          <VolumeX class="mr-2 inline size-4" />Выключена
        </AppButton>
      </div>

      <div v-if="tts.enabled">
        <p class="mb-2 text-sm font-medium text-text2">Голос</p>
        <div class="flex gap-2">
          <button type="button" @click="previewVoice('male')"
                  class="flex-1 rounded-md border p-3 text-left transition-colors"
                  :class="tts.voice === 'male' ? 'border-accent bg-accent-glow' : 'border-border hover:border-accent'">
            <span class="block text-sm font-semibold text-text">Мужской</span>
            <span class="block text-xs text-text3">Полегче и мягче · по умолчанию</span>
          </button>
          <button type="button" @click="previewVoice('female')"
                  class="flex-1 rounded-md border p-3 text-left transition-colors"
                  :class="tts.voice === 'female' ? 'border-accent bg-accent-glow' : 'border-border hover:border-accent'">
            <span class="block text-sm font-semibold text-text">Женский</span>
            <span class="block text-xs text-text3">Нажмите, чтобы прослушать</span>
          </button>
        </div>
        <p v-if="!tts.available" class="mt-3 text-xs text-text3">
          Серверный синтез сейчас недоступен — озвучка идёт средствами браузера
          (голоса зависят от вашего устройства).
        </p>
      </div>
    </Card>

    <!-- Вход по биометрии (passkeys) — виден только на устройствах с Face ID/отпечатком. -->
    <Card v-if="canBiometric && tab === 'profile'" title="Вход по биометрии"
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
