<script setup>
/**
 * InviteDialog.vue — ссылки-приглашения в учебную группу.
 *
 * Куратор (или админ) выдаёт ссылку, кидает её в чат группы, студенты заводят себе
 * аккаунты сами. Приглашение И ЕСТЬ одобрение — второго круга согласований нет, в этом
 * весь смысл; поэтому у ссылки три ограничителя, и все три видны здесь же.
 *
 * ⚠️ Список показывает СОСТОЯНИЕ каждой ссылки («жива / отозвана / срок вышел / мест
 * нет»), а не только её текст. Иначе куратор раздаст мёртвую ссылку и узнает об этом от
 * студентов, а не от экрана.
 * ⚠️ Права проверяет СЕРВЕР: здесь мы лишь не показываем кнопку тем, у кого её быть не
 * должно. Скрытая кнопка — не защита.
 */
import { ref, watch, onMounted } from 'vue'
import { X, Copy, Check, Ban } from '@lucide/vue'
import { adminApi } from '@/api/endpoints'
import { useLocaleStore } from '@/stores/locale'
import { copyText } from '@/utils/clipboard'
import AppButton from '@/components/ui/AppButton.vue'

const props = defineProps({ group: { type: String, required: true } })
const emit = defineEmits(['close'])
const locale = useLocaleStore()
const t = (k, f, p) => locale.t(k, f, p)

const rows = ref([])
const loading = ref(false)
const creating = ref(false)
const error = ref('')
const copied = ref('')

const days = ref(14)
const maxUses = ref(60)
const note = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try { rows.value = (await adminApi.invites(props.group)).data.invites || [] }
  catch (e) { error.value = e?.response?.data?.detail || t('invites.loadFailed', 'Не удалось загрузить приглашения') }
  finally { loading.value = false }
}
onMounted(load)
watch(() => props.group, load)

async function create() {
  creating.value = true
  error.value = ''
  try {
    await adminApi.createInvite(props.group,
      { days: Number(days.value), maxUses: Number(maxUses.value), note: note.value.trim() })
    note.value = ''
    await load()
  } catch (e) {
    error.value = e?.response?.data?.detail || t('invites.createFailed', 'Не удалось создать приглашение')
  } finally { creating.value = false }
}

async function revoke(token) {
  try { await adminApi.revokeInvite(token); await load() }
  catch (e) { error.value = e?.response?.data?.detail || t('invites.revokeFailed', 'Не удалось отозвать') }
}

async function copy(link) {
  if (await copyText(link)) {
    copied.value = link
    setTimeout(() => { if (copied.value === link) copied.value = '' }, 1800)
  }
}

// Дата в местном времени устройства: сервер отдаёт UTC, а куратор думает в своём часовом
// поясе (Улан-Удэ +8) — «истекает 3 сентября» и «истекает 2 сентября 23:00» это разные
// сообщения для того, кто планирует набор группы.
const BCP47 = { ru: 'ru-RU', en: 'en-US', zh: 'zh-CN' }
function when(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso
    : d.toLocaleDateString(BCP47[locale.locale] || 'ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric' })
}
</script>

<template>
  <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" @click.self="emit('close')">
    <div class="flex max-h-[85vh] w-full max-w-2xl flex-col rounded-lg border border-border bg-card p-5 shadow-card">
      <div class="mb-1 flex items-start justify-between gap-3">
        <div>
          <h3 class="font-title text-lg font-bold text-text">
            {{ t('invites.title', 'Приглашения в группу') }} {{ group }}
          </h3>
          <p class="mt-0.5 text-xs text-text3">
            {{ t('invites.subtitle', 'По ссылке студент заводит аккаунт сам — одобрять заявку не нужно.') }}
          </p>
        </div>
        <button type="button" class="text-text3 hover:text-text" @click="emit('close')"><X class="size-5" /></button>
      </div>

      <!-- Выдача -->
      <div class="mt-3 grid grid-cols-1 gap-2 rounded-sm border border-border2 bg-bg2 p-3 sm:grid-cols-4">
        <label class="flex flex-col gap-1">
          <span class="text-tiny uppercase text-text3">{{ t('invites.days', 'Дней') }}</span>
          <input v-model="days" type="number" min="1" max="90"
                 class="h-9 rounded-sm border border-border2 bg-card2 px-2 text-sm text-text outline-none focus:border-accent" />
        </label>
        <label class="flex flex-col gap-1">
          <span class="text-tiny uppercase text-text3">{{ t('invites.seats', 'Мест') }}</span>
          <input v-model="maxUses" type="number" min="1" max="300"
                 class="h-9 rounded-sm border border-border2 bg-card2 px-2 text-sm text-text outline-none focus:border-accent" />
        </label>
        <label class="flex flex-col gap-1 sm:col-span-2">
          <span class="text-tiny uppercase text-text3">{{ t('invites.note', 'Подпись (для себя)') }}</span>
          <input v-model="note" :placeholder="t('invites.notePlaceholder', 'например: 1 курс, сентябрь')"
                 class="h-9 rounded-sm border border-border2 bg-card2 px-2 text-sm text-text outline-none focus:border-accent" />
        </label>
      </div>
      <div class="mt-2 flex justify-end">
        <AppButton variant="green" size="sm" :disabled="creating" @click="create">
          {{ creating ? t('invites.creating', 'Создаём…') : t('invites.create', 'Создать ссылку') }}
        </AppButton>
      </div>

      <p v-if="error" class="mt-2 text-sm text-red">{{ error }}</p>

      <!-- Выданные -->
      <div class="mt-3 min-h-0 flex-1 space-y-2 overflow-y-auto pr-1">
        <p v-if="loading" class="p-3 text-center text-sm text-text3">{{ t('common.loading', 'Загрузка…') }}</p>
        <p v-else-if="!rows.length" class="p-3 text-center text-sm text-text3">
          {{ t('invites.empty', 'Ссылок пока нет.') }}
        </p>
        <div v-for="r in rows" :key="r.token"
             class="rounded-sm border border-border2 px-3 py-2.5"
             :class="r.alive ? '' : 'opacity-60'">
          <div class="flex items-center gap-2">
            <span class="rounded-sm px-1.5 py-0.5 text-[11px] font-semibold"
                  :class="r.alive ? 'bg-green/15 text-green' : 'bg-bg2 text-text3'">
              {{ r.alive ? t('invites.alive', 'действует') : r.reason }}
            </span>
            <span v-if="r.note" class="truncate text-xs text-text3">{{ r.note }}</span>
            <span class="ml-auto shrink-0 text-[11px] text-text3">
              {{ t('invites.until', 'до') }} {{ when(r.expires_at) }} ·
              {{ t('invites.usedOf', { used: r.uses, total: r.max_uses }) }}
            </span>
          </div>
          <div class="mt-1.5 flex items-center gap-2">
            <code class="min-w-0 flex-1 truncate rounded-sm bg-bg2 px-2 py-1 text-[11px] text-text2">{{ r.link }}</code>
            <button type="button" class="shrink-0 text-text3 hover:text-accent"
                    :title="t('invites.copy', 'Скопировать ссылку')" @click="copy(r.link)">
              <Check v-if="copied === r.link" class="size-4 text-green" />
              <Copy v-else class="size-4" />
            </button>
            <button v-if="r.alive" type="button" class="shrink-0 text-text3 hover:text-red"
                    :title="t('invites.revoke', 'Отозвать')" @click="revoke(r.token)">
              <Ban class="size-4" />
            </button>
          </div>
        </div>
      </div>

      <p class="mt-3 text-[11px] leading-snug text-text3">
        {{ t('invites.hint', 'Ссылка — это право зарегистрироваться в группе. Если она ушла не туда, отзовите её: срок и число мест сами по себе утечку не закрывают.') }}
      </p>
    </div>
  </div>
</template>
