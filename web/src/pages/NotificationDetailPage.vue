<script setup>
// NotificationDetailPage — одно уведомление ПОЛНОЦЕННОЙ СТРАНИЦЕЙ, как письмо в почтовом
// ящике (05.10.2026, требование Ярослава: «нажимаем на уведомление — открывается
// полноценная страница с ним, по аналогии с электронным почтовым ящиком; в превью —
// просто надпись, а если открыть — расширенная информация, дедлайн, задача и подобное»).
//
// До этого письмо раскрывалось на месте списка тремя строками: тема, вид и текст. Всё,
// что сервер знал сверх текста (`payload`: прежняя и новая оценка, беседа, задачи
// трекера со сроками), до человека не доходило вовсе — показать было негде.
//
// ⚠️ У письма СВОЙ АДРЕС (`…/notifications/<id>`), и это не украшение:
//   • «назад» в браузере и на телефоне возвращает к списку, а не выкидывает из раздела;
//   • нажатие пуша «Вам дали задание» открывает именно это письмо;
//   • обновление страницы не теряет открытое.
// Чужой или несуществующий id сервер отдаёт как 404 — показываем «письмо не найдено».
import { ref, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, ArrowRight, CalendarClock, SquareKanban } from '@lucide/vue'
import { meApi } from '@/api/endpoints'
import { isStaleSession } from '@/api/responseOwner'
import { useAuthStore } from '@/stores/auth'
import { useLocaleStore } from '@/stores/locale'
import { routeForEvent } from '@/services/push'
import { kindMeta } from '@/config/notificationKinds'
import { deadlineState, fmtHours } from '@/utils/tracker'
import { useTrackerLabels, PRIORITY_STYLE, KIND_STYLE } from '@/composables/useTrackerLabels'
import AppButton from '@/components/ui/AppButton.vue'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const locale = useLocaleStore()
const L = useTrackerLabels()

const item = ref(null)
const loading = ref(true)
const missing = ref(false)
const failed = ref(false)

async function load() {
  const id = String(route.params.id || '')
  loading.value = true
  missing.value = false
  failed.value = false
  item.value = null
  try {
    // Сервер этим же запросом помечает письмо прочитанным: открыл — значит прочёл.
    const { data } = await meApi.getEvent(id)
    if (String(route.params.id || '') === id) item.value = data
  } catch (e) {
    if (isStaleSession(e)) return
    if (e?.response?.status === 404) missing.value = true
    else failed.value = true              //нет связи — не то же самое, что «письма нет»
  } finally { loading.value = false }
}
watch(() => route.params.id, load, { immediate: true })

const meta = computed(() => kindMeta(item.value?.kind))
const payload = computed(() => item.value?.payload || {})
const base = computed(() => `/${auth.role || 'student'}`)

function back() {
  // Пришли из списка — возвращаемся туда же, где стояли (вкладка, прокрутка). Открыли
  // письмо по прямой ссылке или из пуша — истории нет, идём в список явно.
  if (window.history.state?.back) router.back()
  else router.push(`${base.value}/notifications`)
}

const BCP47 = { ru: 'ru-RU', en: 'en-US', zh: 'zh-CN' }
const when = computed(() => {
  const d = new Date(item.value?.created_at || '')
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleString(BCP47[locale.active] || 'ru-RU',
    { day: 'numeric', month: 'long', year: 'numeric', hour: '2-digit', minute: '2-digit' })
})

// ── письмо трекера: задачи со сроками ────────────────────────────────────────────────
const tasks = computed(() => (item.value?.kind === 'tracker' ? (payload.value.tasks || []) : []))
const openTask = (t) => router.push({
  path: `${base.value}/messages`,
  query: { chat: payload.value.conversation_id, tracker: '1', work: t.project_id || '', task: t.id },
})
const openTracker = () => router.push({
  path: `${base.value}/messages`, query: { chat: payload.value.conversation_id, tracker: '1' },
})
const dueClass = (t) => ({ overdue: 'text-red', today: 'text-orange' }[deadlineState(t)] || 'text-text')

// ── остальные виды: куда ведёт письмо ────────────────────────────────────────────────
// Тот же расчёт, что у нажатия пуша (`routeForEvent`) — второго списка «вид → раздел»
// не заводим: он разошёлся бы с первым, и письмо вело бы не туда, куда его же пуш.
const target = computed(() => (item.value && item.value.kind !== 'tracker'
  ? routeForEvent(item.value, auth.role) : null))
const actionLabel = computed(() => ({
  grade: locale.t('notifications.action.journal'),
  grade_changed: locale.t('notifications.action.journal'),
  homework: locale.t('notifications.action.journal'),
  schedule_changed: locale.t('notifications.action.schedule'),
  mention: locale.t('notifications.action.chat'),
  reminder: locale.t('notifications.action.chat'),
  password_changed: locale.t('notifications.action.sessions'),
}[item.value?.kind] || locale.t('notifications.action.open')))

// Подробности из payload, которые можно показать строкой «подпись: значение».
const facts = computed(() => {
  const p = payload.value
  const out = []
  if (item.value?.subject) out.push([locale.t('notifications.fact.subject'), item.value.subject])
  if (p.old !== undefined && p.new !== undefined && (p.old || p.new)) {
    out.push([locale.t('notifications.fact.change'), `${p.old || '—'} → ${p.new || '—'}`])
  }
  if (p.group) out.push([locale.t('notifications.fact.group'), p.group])
  if (p.count) out.push([locale.t('notifications.fact.lessons'), String(p.count)])
  if (p.first_at) out.push([locale.t('notifications.fact.firstAt'), p.first_at])
  return out
})
</script>

<template>
  <div class="mx-auto w-full max-w-3xl">
    <button type="button" @click="back"
            class="mb-3 inline-flex items-center gap-1.5 rounded-md px-1 py-1 text-sm text-text3 transition-colors hover:text-accent">
      <ArrowLeft class="size-4" />{{ locale.t('notifications.backToList', 'К списку') }}
    </button>

    <p v-if="loading" class="py-10 text-center text-sm text-text3">{{ locale.t('notifications.loading', 'Загружаем…') }}</p>
    <div v-else-if="missing" class="rounded-xl border border-border bg-card p-8 text-center">
      <p class="font-title text-lg font-bold text-text">{{ locale.t('notifications.notFoundTitle') }}</p>
      <p class="mt-1 text-sm text-text3">{{ locale.t('notifications.notFoundText') }}</p>
    </div>
    <div v-else-if="failed" class="rounded-xl border border-border bg-card p-8 text-center">
      <p class="text-sm text-text3">{{ locale.t('notifications.loadFailed', 'Не удалось получить уведомления. Проверьте связь и обновите страницу.') }}</p>
      <AppButton class="mt-3" variant="ghost" @click="load">{{ locale.t('tracker.retry') }}</AppButton>
    </div>

    <article v-else-if="item" class="overflow-hidden rounded-xl border border-border bg-card shadow-card">
      <!-- шапка письма: от кого, тема, когда -->
      <header class="border-b border-border p-4 sm:p-6">
        <div class="flex items-start gap-3">
          <span class="grid size-11 shrink-0 place-items-center rounded-full bg-accent-glow text-accent">
            <component :is="meta.icon" class="size-5" />
          </span>
          <div class="min-w-0 flex-1">
            <h1 class="break-words font-title text-xl font-extrabold leading-tight text-text sm:text-2xl">
              {{ item.title || locale.t(meta.i18n) }}
            </h1>
            <p class="mt-1 text-sm text-text3">
              <span class="font-semibold text-text2">{{ locale.t(meta.i18n) }}</span>
              <template v-if="item.kind === 'tracker' && payload.conversation"> · {{ locale.t('notifications.fromChat', { chat: payload.conversation }) }}</template>
              <template v-if="when"> · {{ when }}</template>
            </p>
          </div>
        </div>
      </header>

      <div class="space-y-4 p-4 sm:p-6">
        <!-- ── письмо трекера ── -->
        <template v-if="item.kind === 'tracker'">
          <p v-if="payload.assigned_by" class="text-sm text-text2">
            {{ locale.t('notifications.tracker.assignedBy', { name: payload.assigned_by }) }}
          </p>
          <ul class="space-y-3">
            <li v-for="t in tasks" :key="t.id" class="rounded-xl border border-border2 bg-card2 p-3 sm:p-4">
              <div class="flex flex-wrap items-center gap-2 text-xs text-text3">
                <component :is="(KIND_STYLE[t.kind] || KIND_STYLE.task).icon" class="size-4"
                           :style="{ color: (KIND_STYLE[t.kind] || KIND_STYLE.task).color }" />
                <span class="font-semibold tabular-nums">{{ t.key }}</span>
                <span>{{ L.kind.value[t.kind] || L.kind.value.task }}</span>
                <span v-if="t.project">· {{ t.project }}</span>
                <span v-if="t.column">· {{ t.column }}</span>
              </div>
              <h2 class="mt-1 break-words text-base font-semibold text-text">{{ t.title }}</h2>
              <dl class="mt-2 grid grid-cols-1 gap-x-6 gap-y-1.5 text-sm sm:grid-cols-2">
                <div class="flex items-center gap-2">
                  <dt class="flex shrink-0 items-center gap-1 text-text3"><CalendarClock class="size-4" />{{ L.t('tracker.field.deadline') }}</dt>
                  <dd class="font-semibold" :class="t.deadline ? dueClass(t) : 'text-text3'">
                    {{ t.deadline ? L.fmtDate(t.deadline) : L.t('tracker.noDeadline') }}
                  </dd>
                </div>
                <div class="flex items-center gap-2">
                  <dt class="shrink-0 text-text3">{{ L.t('tracker.field.priority') }}</dt>
                  <dd class="flex items-center gap-1 text-text">
                    <component :is="(PRIORITY_STYLE[t.priority] || PRIORITY_STYLE.normal).icon" class="size-4"
                               :style="{ color: (PRIORITY_STYLE[t.priority] || PRIORITY_STYLE.normal).color }" />
                    {{ L.priority.value[t.priority] || L.priority.value.normal }}
                  </dd>
                </div>
                <div v-if="t.start_date" class="flex items-center gap-2">
                  <dt class="shrink-0 text-text3">{{ L.t('tracker.field.start') }}</dt>
                  <dd class="text-text">{{ L.fmtDate(t.start_date) }}</dd>
                </div>
                <div v-if="t.estimate" class="flex items-center gap-2">
                  <dt class="shrink-0 text-text3">{{ L.t('tracker.field.estimate') }}</dt>
                  <dd class="text-text">{{ fmtHours(t.estimate, L.hoursUnit.value) }}</dd>
                </div>
                <div v-if="t.checklist_total" class="flex items-center gap-2">
                  <dt class="shrink-0 text-text3">{{ L.t('tracker.checklist') }}</dt>
                  <dd class="text-text">{{ locale.t('notifications.tracker.checklistItems', { n: t.checklist_total }) }}</dd>
                </div>
              </dl>
              <p v-if="t.description" class="mt-3 whitespace-pre-line break-words border-t border-border pt-3 text-sm leading-relaxed text-text2">
                {{ t.description }}
              </p>
              <div class="mt-3 flex justify-end">
                <AppButton @click="openTask(t)">
                  <SquareKanban class="mr-1.5 inline size-4" />{{ locale.t('notifications.tracker.openTask') }}
                </AppButton>
              </div>
            </li>
          </ul>
          <!-- Письмо помнит задачу такой, какой она была в момент назначения. -->
          <p class="text-xs text-text3">{{ locale.t('notifications.tracker.snapshotHint') }}</p>
          <button v-if="tasks.length > 1" type="button" @click="openTracker"
                  class="inline-flex items-center gap-1.5 text-sm text-accent hover:underline">
            {{ locale.t('notifications.tracker.openAll') }}<ArrowRight class="size-4" />
          </button>
        </template>

        <!-- ── остальные письма ── -->
        <template v-else>
          <p class="whitespace-pre-line break-words text-[15px] leading-relaxed text-text">
            {{ item.body || locale.t('notifications.defaultBody', 'Откройте журнал, чтобы посмотреть подробности.') }}
          </p>
          <dl v-if="facts.length" class="grid grid-cols-1 gap-x-6 gap-y-1.5 rounded-xl border border-border2 bg-card2 p-3 text-sm sm:grid-cols-2">
            <div v-for="[label, value] in facts" :key="label" class="flex items-baseline gap-2">
              <dt class="shrink-0 text-text3">{{ label }}</dt>
              <dd class="min-w-0 break-words font-semibold text-text">{{ value }}</dd>
            </div>
          </dl>
          <div v-if="target" class="flex justify-end">
            <AppButton @click="router.push(target)">{{ actionLabel }}<ArrowRight class="ml-1.5 inline size-4" /></AppButton>
          </div>
        </template>
      </div>
    </article>
  </div>
</template>
