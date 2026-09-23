<script setup>
/**
 * SessionsDialog.vue — «Сессии»: где открыт этот аккаунт (4.0).
 *
 * Крестик закрывает одну сессию, кнопка внизу — все, кроме текущей. Закрытая сессия
 * получает 401 на следующем же запросе: отзыв проверяет сервер в одной точке
 * (`deps.get_current_user`), здесь только кнопки.
 *
 * ⚠️ Местоположение показывается, только если на сервере лежит ЛОКАЛЬНАЯ база GeoIP.
 * Внешние сервисы геолокации не вызываются никогда (адрес человека, отправленный
 * иностранному сервису, — трансграничная передача ПДн), поэтому «неизвестно» здесь —
 * честный ответ, а не поломка.
 */
import { ref, onMounted } from 'vue'
import { X, Monitor, Smartphone, ShieldCheck } from '@lucide/vue'
import { accountApi } from '@/api/endpoints'
import AppButton from '@/components/ui/AppButton.vue'
import { useConfirm } from '@/composables/useConfirm'
import { useToast } from '@/composables/useToast'
import { useLocaleStore } from '@/stores/locale'

const emit = defineEmits(['close'])
const loc = useLocaleStore()
const toast = useToast()
const { confirm } = useConfirm()
const list = ref([])
const loading = ref(true)
const busy = ref(false)

const BCP47 = { ru: 'ru-RU', en: 'en-US', zh: 'zh-CN' }
function fmt(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  return isNaN(d) ? '—' : d.toLocaleString(BCP47[loc.active] || 'ru-RU',
    { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}
function isPhone(s) { return /Android|iOS/.test(s.device || '') }

async function load() {
  loading.value = true
  try { list.value = (await accountApi.sessions()).data.sessions || [] }
  catch { list.value = [] }
  finally { loading.value = false }
}
onMounted(load)

async function closeOne(s) {
  if (s.current && !(await confirm({ title: loc.t('sessions.closeCurrentConfirm', 'Это текущая сессия — вы выйдете с этого устройства.'), okText: loc.t('sessions.close', 'Закрыть'), danger: true }))) return
  busy.value = true
  try {
    await accountApi.revokeSession(s.id)
    await load()
  } catch (e) {
    toast.error(e?.response?.data?.detail || loc.t('sessions.closeFailed', 'Не удалось закрыть сессию'))
  } finally { busy.value = false }
}

async function closeOthers() {
  if (!(await confirm({ title: loc.t('sessions.closeOthersConfirm', 'Выйти на всех устройствах, кроме этого? Доверие к ним тоже будет снято.'), okText: loc.t('sessions.closeOthers', 'Выйти из всех сессий'), danger: true }))) return
  busy.value = true
  try {
    const n = (await accountApi.revokeOthers()).data.revoked || 0
    toast.success(loc.t('sessions.closedN', { n }))
    await load()
  } catch (e) {
    toast.error(e?.response?.data?.detail || loc.t('sessions.closeFailed', 'Не удалось закрыть сессию'))
  } finally { busy.value = false }
}
</script>

<template>
  <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" @click.self="emit('close')">
    <div class="flex max-h-[85vh] w-full max-w-lg flex-col rounded-lg border border-border bg-card shadow-card">
      <div class="flex items-center justify-between border-b border-border px-5 py-3">
        <h3 class="font-title text-lg font-bold text-text">{{ loc.t('sessions.title', 'Сессии') }}</h3>
        <button type="button" class="text-text3 hover:text-text" :aria-label="loc.t('common.close', 'Закрыть')" @click="emit('close')">
          <X class="size-5" />
        </button>
      </div>
      <div class="min-h-0 flex-1 overflow-y-auto px-5 py-3">
        <p v-if="loading" class="py-6 text-center text-sm text-text3">{{ loc.t('common.loading') }}</p>
        <p v-else-if="!list.length" class="py-6 text-center text-sm text-text3">{{ loc.t('sessions.none', 'Открытых сессий нет') }}</p>
        <ul v-else class="space-y-2">
          <li v-for="s in list" :key="s.id"
              class="flex items-start gap-3 rounded-md border px-3 py-2.5"
              :class="s.current ? 'border-accent/50 bg-accent-glow' : 'border-border'">
            <Smartphone v-if="isPhone(s)" class="mt-0.5 size-4 shrink-0 text-text3" />
            <Monitor v-else class="mt-0.5 size-4 shrink-0 text-text3" />
            <div class="min-w-0 flex-1 text-sm">
              <div class="flex flex-wrap items-center gap-2">
                <span class="font-medium text-text">{{ s.device }}</span>
                <span v-if="s.current" class="rounded-full bg-accent px-2 py-0.5 text-tiny font-semibold text-white">{{ loc.t('sessions.current', 'это устройство') }}</span>
                <span v-if="s.trusted" class="inline-flex items-center gap-1 text-tiny text-accent" :title="loc.t('sessions.trustedHint', 'Доверенное устройство: вход без кода из письма')">
                  <ShieldCheck class="size-3" />{{ loc.t('sessions.trusted', 'доверенное') }}</span>
              </div>
              <div class="mt-0.5 text-tiny text-text3">
                {{ s.ip || '—' }} · {{ s.location || loc.t('sessions.locationUnknown', 'местоположение неизвестно') }}
              </div>
              <div class="text-tiny text-text3">{{ loc.t('sessions.lastSeen', { when: fmt(s.last_seen_at) }) }}</div>
            </div>
            <button type="button" :disabled="busy" class="text-text3 transition-colors hover:text-red disabled:opacity-50"
                    :aria-label="loc.t('sessions.close', 'Закрыть')" :title="loc.t('sessions.close', 'Закрыть')" @click="closeOne(s)">
              <X class="size-4" />
            </button>
          </li>
        </ul>
      </div>
      <div class="border-t border-border px-5 py-3">
        <AppButton variant="red" size="sm" class="w-full" :disabled="busy || list.filter((s) => !s.current).length === 0" @click="closeOthers">
          {{ loc.t('sessions.closeOthers', 'Выйти из всех сессий') }}
        </AppButton>
        <p class="mt-2 text-center text-tiny text-text3">{{ loc.t('sessions.closeOthersHint', 'Кроме этого устройства.') }}</p>
      </div>
    </div>
  </div>
</template>
