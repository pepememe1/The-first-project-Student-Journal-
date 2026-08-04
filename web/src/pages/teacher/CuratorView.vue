<script setup>
// CuratorView — режим КУРАТОРА (teacher с назначенными группами). В отличие от журнала
// преподавателя (только свои предметы), куратор видит ВСЕ предметы своей группы, но
// ТОЛЬКО НА ЧТЕНИЕ: группа → предмет → студенты с оценками и средним. Данные — из
// role-scoped /web/curator/* (сервер проверяет group ∈ curated_groups).
import { ref, computed, watch, onMounted } from 'vue'
import { curatorApi, adminApi, termsApi } from '@/api/endpoints'
import EmptyState from '@/components/ui/EmptyState.vue'
import RiskBadge from '@/components/ui/RiskBadge.vue'
import { useConfirm } from '@/composables/useConfirm'
import { useToast } from '@/composables/useToast'
import { useLocaleStore } from '@/stores/locale'

const { confirm } = useConfirm()
const toast = useToast()
const locale = useLocaleStore()

const groups = ref([])
const group = ref('')
const subjects = ref([])
const subject = ref('')
const data = ref(null)
const loading = ref(false)

// ── ЗЕТ / перевод на курс (docs/PLAN-ZET.md §7.4 — «главная фича» отчёта куратора) ──
const viewMode = ref('journal')   // 'journal' | 'zet' | 'risk'
// Риск отчисления по группе (3.6). Грузится ОДИН раз на смену группы, а не по открытию
// вкладки: счётчик на самой вкладке обязан быть верным до того, как на неё нажали, —
// иначе куратор просто не узнает, что там кто-то есть.
const riskReport = ref(null)
const riskLoading = ref(false)
const zetReport = ref(null)       // {min_zet, students:[...]}
const zetLoading = ref(false)
const zetThresholdDraft = ref('')
const selectedForPromote = ref([])
const promoting = ref(false)

async function loadZetReport() {
  if (!group.value) { zetReport.value = null; return }
  zetLoading.value = true
  selectedForPromote.value = []
  try {
    zetReport.value = (await curatorApi.zetReport(group.value, termParams())).data
    zetThresholdDraft.value = zetReport.value.min_zet ?? ''
  } catch { zetReport.value = null } finally { zetLoading.value = false }
}
// ⚠️ Наблюдатель за ЗЕТ-отчётом заводится НИЖЕ, после объявления `term` (см. конец
// блока «Учебный период»). Здесь его быть не может: `const term` не поднимается, и
// обращение к нему выше объявления валит ВЕСЬ setup — вкладка «Курирование» открывалась
// пустой страницей, а не «нет данных».

async function saveThreshold() {
  const v = zetThresholdDraft.value
  try {
    await adminApi.setZetThreshold({
      group: group.value, ...termParams(),
      min_zet: (v === '' || v === null) ? null : Number(v),
    })
    toast.success(locale.t('curatorView.thresholdSaved', 'Порог сохранён'))
    await loadZetReport()
  } catch (e) { toast.error(e?.response?.data?.detail || locale.t('curatorView.thresholdSaveFailed', 'Не удалось сохранить порог')) }
}

const eligibleIds = computed(() =>
  (zetReport.value?.students || []).filter((s) => s.eligible).map((s) => s.student_id))
function toggleSelectAllEligible(on) {
  selectedForPromote.value = on ? eligibleIds.value.slice() : []
}

async function doPromote() {
  const names = (zetReport.value.students || [])
    .filter((s) => selectedForPromote.value.includes(s.student_id))
    .map((s) => s.display_name)
  const ok = await confirm({
    title: locale.t('curatorView.confirmPromoteTitle', 'Перевод на следующий курс'),
    message: locale.t('curatorView.confirmPromoteMessage', { names: names.join(', ') }),
    okText: locale.t('curatorView.confirmPromoteOk', 'Перевести'),
  })
  if (!ok) return
  promoting.value = true
  try {
    const r = await adminApi.promoteGroup({
      group: group.value, ...termParams(), student_ids: selectedForPromote.value,
    })
    toast.success(locale.t('curatorView.promotedToast', { n: r.data.promoted.length }))
    await loadZetReport()
  } catch (e) { toast.error(e?.response?.data?.detail || locale.t('curatorView.promoteFailed', 'Не удалось перевести')) }
  finally { promoting.value = false }
}

// Учебный период (архив прошлых семестров)
const terms = ref([])
const term = ref(null)
const currentTerm = ref(null)
const isArchive = computed(() => term.value && currentTerm.value &&
  (term.value.year !== currentTerm.value.year || term.value.semester !== currentTerm.value.semester))
function termLabel(t) {
  if (!t) return ''
  const sem = t.semester === 1
    ? locale.t('curatorView.termAutumn', 'осенний')
    : locale.t('curatorView.termSpring', 'весенний')
  return locale.t('curatorView.termLabelFormat', { year: t.year, semester: sem })
}
function termKey(t) { return t ? `${t.year}|${t.semester}` : '' }
function selectTerm(k) { term.value = terms.value.find((t) => termKey(t) === k) || currentTerm.value }
function termParams() { return term.value ? { year: term.value.year, semester: term.value.semester } : {} }

//Здесь, а не рядом с `loadZetReport`: наблюдателю нужен уже объявленный `term`.
watch([group, term, viewMode], () => { if (viewMode.value === 'zet') loadZetReport() })

onMounted(async () => {
  try { groups.value = (await curatorApi.groups()).data.groups || [] } catch { groups.value = [] }
  group.value = groups.value[0] || ''
  try {
    const t = (await termsApi.list()).data
    currentTerm.value = t.current
    const all = (t.terms || []).slice()
    if (!all.some((x) => x.year === t.current.year && x.semester === t.current.semester)) all.unshift(t.current)
    terms.value = all
    term.value = t.current
  } catch { /* */ }
  // Загрузку предметов вызываем ЯВНО, когда И группа, И термин уже выставлены. Раньше
  // это делал только watch([group, term]) — но group и term задаются в разные моменты
  // (между ними await termsApi), и предметы грузились в гонке с ещё не готовым термином,
  // из-за чего вкладка показывала «нет предметов» даже при наличии занятий.
  await loadSubjects()
  //Риск грузим сразу: счётчик на вкладке должен быть правдой с первого показа страницы.
  loadRisk()
})

async function loadSubjects() {
  subjects.value = []; subject.value = ''; data.value = null
  if (!group.value) return
  try {
    subjects.value = (await curatorApi.subjects(group.value, termParams())).data.subjects || []
    subject.value = subjects.value[0] || ''
  } catch { subjects.value = [] }
}
watch([group, term], loadSubjects, { immediate: false })

async function loadRisk() {
  riskReport.value = null
  if (!group.value) return
  riskLoading.value = true
  //Анти-гоночная защита ровно та же, что в расписании (3.5.6): группа, ДЛЯ которой
  //запрошен ответ, фиксируется ДО await и сверяется ПОСЛЕ. Быстрое переключение групп
  //иначе показывает риск чужой группы — самый неприятный сорт ошибки в этой функции.
  const forGroup = group.value
  try {
    const { data: r } = await curatorApi.risk(forGroup)
    if (forGroup !== group.value) return
    riskReport.value = r
  } catch {
    if (forGroup === group.value) riskReport.value = null
  } finally {
    if (forGroup === group.value) riskLoading.value = false
  }
}
watch(group, loadRisk)

async function load() {
  if (!group.value || !subject.value) { data.value = null; return }
  loading.value = true
  try { data.value = (await curatorApi.groupSubject(group.value, subject.value, termParams())).data }
  catch { data.value = null } finally { loading.value = false }
}
watch(subject, load)

function gradeClass(v) {
  v = (v || '').trim().split(' ')[0]
  if (v === '5' || v === '✓') return 'text-accent font-bold'
  if (v === '4') return 'text-blue font-bold'
  if (v === '3') return 'text-orange font-bold'
  if (v === '2' || v === 'Н') return 'text-red font-bold'
  if (v === 'Б' || v === 'О') return 'text-text3 font-semibold'
  return 'text-text2'
}
function avgClass(a) {
  const n = Number(a) || 0
  if (n >= 4.5) return 'text-accent'
  if (n >= 3.5) return 'text-blue'
  if (n >= 3) return 'text-orange'
  if (n > 0) return 'text-red'
  return 'text-text3'
}

// ── Экспорт отчёта успеваемости (Excel/Word, выбор групп) ───────────────────────────
const showExport = ref(false)
const exporting = ref(false)
const pickedGroups = ref([])       // отмеченные группы (галочки = одна/несколько/все)
function openExport() {
  // По умолчанию отмечаем текущую группу — самый частый сценарий.
  pickedGroups.value = group.value ? [group.value] : groups.value.slice()
  showExport.value = true
}
function toggleAllGroups(on) { pickedGroups.value = on ? groups.value.slice() : [] }

async function exportReport(fmt) {
  if (!pickedGroups.value.length) return
  exporting.value = true
  try {
    // 'all' — когда выбраны все курируемые (короче URL и понятнее в аудите).
    const scope = pickedGroups.value.length === groups.value.length
      ? 'all' : pickedGroups.value.join(',')
    const { data: blob } = await curatorApi.report(scope, fmt, termParams())
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    const many = pickedGroups.value.length > 1
    a.download = `Успеваемость_${many ? 'группы' : pickedGroups.value[0]}`
      .replaceAll('/', '-') + (fmt === 'docx' ? '.docx' : '.xlsx')
    a.click()
    URL.revokeObjectURL(url)
    showExport.value = false
  } catch { /* сеть/сервер — тихо, кнопка станет снова активной */ } finally {
    exporting.value = false
  }
}
</script>

<template>
  <div class="space-y-4">
    <EmptyState v-if="!groups.length" :title="locale.t('curatorView.noCuratorTitle', 'Вы не куратор')"
                :message="locale.t('curatorView.noCuratorMessage', 'Администратор пока не назначил вам курируемые группы.')" />
    <template v-else>
      <div class="flex flex-wrap items-center gap-2 sm:gap-3">
        <select v-model="group" @change="loadSubjects"
                class="h-10 w-full rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent sm:w-auto">
          <option v-for="g in groups" :key="g" :value="g">{{ g }}</option>
        </select>
        <select v-model="subject" :disabled="!subjects.length"
                class="h-10 w-full rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent sm:w-auto sm:min-w-52">
          <option v-for="s in subjects" :key="s" :value="s">{{ s }}</option>
        </select>
        <select v-if="terms.length" :value="termKey(term)" @change="selectTerm($event.target.value)"
                class="h-10 rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent"
                :class="isArchive ? 'border-orange text-orange' : ''">
          <option v-for="t in terms" :key="termKey(t)" :value="termKey(t)">{{ termLabel(t) }}</option>
        </select>
        <button class="flex h-10 items-center gap-1.5 rounded-sm border border-accent bg-accent/10 px-3 text-sm font-medium text-accent hover:bg-accent/20 sm:ml-auto"
                @click="openExport">
          📊 {{ locale.t('curatorView.reportButton', 'Отчёт успеваемости') }}
        </button>
      </div>

      <!-- Журнал (read-only) / ЗЕТ·Перевод (docs/PLAN-ZET.md §7.4) -->
      <div class="flex gap-1 border-b border-border">
        <button type="button" @click="viewMode = 'journal'"
                class="border-b-2 px-3 py-2 text-sm font-medium"
                :class="viewMode === 'journal' ? 'border-accent text-accent' : 'border-transparent text-text3 hover:text-text2'">
          {{ locale.t('curatorView.tabJournal', 'Журнал') }} <span class="text-xs">👁</span>
        </button>
        <button type="button" @click="viewMode = 'zet'"
                class="border-b-2 px-3 py-2 text-sm font-medium"
                :class="viewMode === 'zet' ? 'border-accent text-accent' : 'border-transparent text-text3 hover:text-text2'">
          {{ locale.t('curatorView.tabZet', 'ЗЕТ · Перевод на курс') }}
        </button>
        <!-- Риск отчисления (3.6). Счётчик стоит прямо на вкладке: куратор обязан
             увидеть, что там кто-то есть, НЕ открывая её. -->
        <button type="button" @click="viewMode = 'risk'"
                class="flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm font-medium"
                :class="viewMode === 'risk' ? 'border-accent text-accent' : 'border-transparent text-text3 hover:text-text2'">
          {{ locale.t('curatorView.tabRisk', 'Риск отчисления') }}
          <span v-if="riskReport?.at_risk"
                class="rounded-full bg-red px-1.5 text-[11px] font-bold text-white">{{ riskReport.at_risk }}</span>
        </button>
      </div>

      <!-- Диалог экспорта: формат (Excel/Word) + выбор групп (галочки = одна/несколько/все) -->
      <div v-if="showExport" class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
           @click.self="showExport = false">
        <div class="w-full max-w-md rounded-lg border border-border bg-card p-5 shadow-card">
          <h3 class="mb-3 font-title text-lg font-bold text-text">{{ locale.t('curatorView.reportButton', 'Отчёт успеваемости') }}</h3>
          <p class="mb-2 text-xs text-text3">
            {{ locale.t('curatorView.exportDialogHint', 'Аналитика по группам: средние по предметам, посещаемость (Н/Б/О), долги, списки.') }}
          </p>

          <div class="mb-2 flex items-center justify-between">
            <span class="text-sm font-medium text-text2">{{ locale.t('curatorView.groupsLabel', 'Группы') }}</span>
            <div class="flex gap-3 text-xs">
              <button class="text-accent hover:underline" @click="toggleAllGroups(true)">{{ locale.t('curatorView.selectAll', 'выбрать все') }}</button>
              <button class="text-text3 hover:underline" @click="toggleAllGroups(false)">{{ locale.t('curatorView.clearSelection', 'снять') }}</button>
            </div>
          </div>
          <div class="mb-4 max-h-44 space-y-1 overflow-y-auto rounded-sm border border-border2 p-2">
            <label v-for="g in groups" :key="g"
                   class="flex cursor-pointer items-center gap-2 rounded-sm px-2 py-1.5 text-sm text-text hover:bg-bg2">
              <input type="checkbox" :value="g" v-model="pickedGroups" class="accent-accent" />
              {{ g }}
            </label>
          </div>

          <div class="flex flex-wrap gap-2">
            <button :disabled="exporting || !pickedGroups.length"
                    class="flex-1 rounded-sm bg-accent px-4 py-2.5 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50"
                    @click="exportReport('xlsx')">
              {{ exporting ? locale.t('curatorView.preparing', 'Готовим…') : `📗 ${locale.t('curatorView.excel', 'Excel')}` }}
            </button>
            <button :disabled="exporting || !pickedGroups.length"
                    class="flex-1 rounded-sm bg-blue px-4 py-2.5 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50"
                    @click="exportReport('docx')">
              {{ exporting ? locale.t('curatorView.preparing', 'Готовим…') : `📘 ${locale.t('curatorView.word', 'Word')}` }}
            </button>
            <button class="rounded-sm border border-border2 px-4 py-2.5 text-sm text-text2 hover:bg-bg2"
                    @click="showExport = false">{{ locale.t('common.cancel') }}</button>
          </div>
        </div>
      </div>

      <template v-if="viewMode === 'journal'">
        <p class="text-xs text-text3">👁 {{ locale.t('curatorView.readOnlyHint', 'Только просмотр (куратор) — оценки ставит преподаватель.') }}</p>
        <EmptyState v-if="!subjects.length" :title="locale.t('curatorView.noSubjectsTitle', 'Нет предметов')"
                    :message="locale.t('curatorView.noSubjectsMessage', { group })" />
        <p v-else-if="loading" class="text-sm text-text3">{{ locale.t('common.loading') }}</p>
        <EmptyState v-else-if="!data?.students?.length" :title="locale.t('curatorView.noStudentsTitle', 'Нет студентов')" :message="locale.t('curatorView.noStudentsMessage', { group })" />

        <div v-else class="overflow-x-auto rounded-lg border border-border bg-card shadow-card">
          <table class="w-max text-sm">
            <thead>
              <tr class="border-b-2 border-accent bg-bg2 text-text2">
                <th class="sticky left-0 z-10 bg-bg2 px-4 py-3 text-left text-tiny font-semibold uppercase tracking-wide">{{ locale.t('curatorView.colStudent', 'Студент') }}</th>
                <th v-for="l in data.lessons" :key="l.id" class="w-28 border-l border-border align-top px-2 py-2">
                  <div class="text-xs font-bold text-text">{{ l.type }} №{{ l.number }}</div>
                  <div class="text-[11px] font-normal normal-case text-text3">{{ l.date || '—' }}</div>
                </th>
                <th class="border-l-2 border-accent/40 px-4 py-3 text-right text-tiny font-semibold uppercase tracking-wide">{{ locale.t('curatorView.colAverage', 'Средн.') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(s, i) in data.students" :key="i"
                  class="border-b border-border last:border-0" :class="i % 2 ? 'bg-bg2/50' : ''">
                <td class="sticky left-0 z-10 whitespace-nowrap px-4 py-2 text-left font-medium text-text" :class="i % 2 ? 'bg-bg2' : 'bg-card'">
                  {{ s.surname }} {{ s.name }}
                </td>
                <td v-for="l in data.lessons" :key="l.id" class="border-l border-border px-2 py-2 text-center"
                    :class="gradeClass(s.grades[l.id])">{{ (s.grades[l.id] || '').split(' ')[0] || '·' }}</td>
                <td class="border-l-2 border-accent/20 px-4 py-2 text-right font-title text-base font-bold" :class="avgClass(s.average)">
                  {{ s.average || '—' }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>

      <!-- Риск отчисления по всей группе (3.6, dropout_risk.py) -->
      <template v-else-if="viewMode === 'risk'">
        <p class="text-xs text-text3">
          {{ locale.t('curatorView.riskHint', 'Показаны только те, у кого риск реально есть. Индекс складывается из фактов журнала — наведите на плашку, чтобы увидеть причины.') }}
        </p>
        <p v-if="riskLoading" class="text-sm text-text3">{{ locale.t('common.loading') }}</p>
        <EmptyState v-else-if="!riskReport?.students?.length"
                    :title="locale.t('curatorView.riskEmptyTitle', 'В зоне риска никого')"
                    :message="locale.t('curatorView.riskEmptyMessage', { group })" />
        <div v-else class="flex flex-col gap-3">
          <p class="text-sm text-text2">
            {{ locale.t('curatorView.riskSummary', { n: riskReport.at_risk, total: riskReport.total }) }}
          </p>
          <!-- Карточка на студента, а не строка таблицы: причин у каждого несколько, и
               в ячейку они не помещаются, а без причин индекс — приговор без объяснения. -->
          <div v-for="r in riskReport.students" :key="r.student_id"
               class="rounded-lg border border-border bg-card p-4 shadow-card">
            <div class="flex flex-wrap items-center justify-between gap-2">
              <span class="font-title text-base font-bold text-text">{{ r.full_name }}</span>
              <RiskBadge :risk="r.risk" compact />
            </div>
            <ul class="mt-2 flex flex-col gap-1">
              <li v-for="f in r.risk.factors" :key="f.code" class="text-sm text-text2">
                <span class="font-semibold text-text">{{ f.label }}.</span> {{ f.detail }}
              </li>
            </ul>
            <p v-if="r.risk.advice" class="mt-2 text-xs text-text3">→ {{ r.risk.advice }}</p>
          </div>
        </div>
      </template>

      <!-- ЗЕТ · Перевод на курс (docs/PLAN-ZET.md §7.4 — «главная фича») -->
      <template v-else>
        <div class="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-card p-3 shadow-card">
          <span class="text-sm text-text2">{{ locale.t('curatorView.thresholdLabel', 'Порог перевода (ЗЕТ):') }}</span>
          <input v-model="zetThresholdDraft" type="number" min="0" step="0.5" :placeholder="locale.t('curatorView.thresholdPlaceholder', 'не задан')"
                 class="h-9 w-28 rounded-sm border border-border2 bg-card2 px-2 text-sm text-text outline-none focus:border-accent" />
          <button type="button" @click="saveThreshold"
                  class="rounded-sm bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90">{{ locale.t('common.save') }}</button>
        </div>

        <p v-if="zetLoading" class="text-sm text-text3">{{ locale.t('common.loading') }}</p>
        <EmptyState v-else-if="!zetReport?.students?.length" :title="locale.t('curatorView.zetEmptyTitle', 'Пока пусто')"
                    :message="locale.t('curatorView.zetEmptyMessage', 'Ни один предмет группы ещё не получил ЗЕТ от администратора.')" />

        <div v-else class="overflow-x-auto rounded-lg border border-border bg-card shadow-card">
          <div class="flex items-center justify-between border-b border-border px-4 py-2">
            <div class="flex gap-3 text-xs">
              <button class="text-accent hover:underline" @click="toggleSelectAllEligible(true)">{{ locale.t('curatorView.selectEligible', 'выбрать готовых') }}</button>
              <button class="text-text3 hover:underline" @click="toggleSelectAllEligible(false)">{{ locale.t('curatorView.clearSelection', 'снять') }}</button>
            </div>
            <button type="button" :disabled="!selectedForPromote.length || promoting" @click="doPromote"
                    class="rounded-sm bg-accent px-3 py-1.5 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50">
              {{ promoting ? locale.t('curatorView.promoting', 'Перевод…') : `✅ ${locale.t('curatorView.promoteSelected', { n: selectedForPromote.length })}` }}
            </button>
          </div>
          <table class="w-full text-sm">
            <thead>
              <tr class="border-b-2 border-accent bg-bg2 text-text2">
                <th class="w-8 px-3 py-2"></th>
                <th class="px-3 py-2 text-left text-tiny font-semibold uppercase tracking-wide">{{ locale.t('curatorView.colStudent', 'Студент') }}</th>
                <th class="px-3 py-2 text-right text-tiny font-semibold uppercase tracking-wide">{{ locale.t('curatorView.colEarned', 'Набрано') }}</th>
                <th class="px-3 py-2 text-right text-tiny font-semibold uppercase tracking-wide">{{ locale.t('curatorView.colMissing', 'Не хватает') }}</th>
                <th class="px-3 py-2 text-left text-tiny font-semibold uppercase tracking-wide">{{ locale.t('curatorView.colUnsatisfied', 'Несданные предметы') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="s in zetReport.students" :key="s.student_id"
                  class="border-b border-border last:border-0">
                <td class="px-3 py-2 text-center">
                  <input type="checkbox" :value="s.student_id" v-model="selectedForPromote"
                         :disabled="!s.eligible" class="accent-accent" />
                </td>
                <td class="px-3 py-2 text-text">
                  <span :class="s.eligible ? 'text-accent' : 'text-red'">{{ s.eligible ? '✅' : '❌' }}</span>
                  {{ s.display_name }}
                </td>
                <td class="px-3 py-2 text-right text-text2">{{ s.earned }}/{{ s.total }}</td>
                <td class="px-3 py-2 text-right" :class="s.eligible ? 'text-text3' : 'text-red'">{{ s.eligible ? '—' : s.missing_zet }}</td>
                <td class="px-3 py-2 text-xs text-text3">{{ s.unsatisfied.join(', ') || '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>
    </template>
  </div>
</template>
