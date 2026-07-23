<script setup>
// CuratorView — режим КУРАТОРА (teacher с назначенными группами). В отличие от журнала
// преподавателя (только свои предметы), куратор видит ВСЕ предметы своей группы, но
// ТОЛЬКО НА ЧТЕНИЕ: группа → предмет → студенты с оценками и средним. Данные — из
// role-scoped /web/curator/* (сервер проверяет group ∈ curated_groups).
import { ref, computed, watch, onMounted } from 'vue'
import { curatorApi, termsApi } from '@/api/endpoints'
import EmptyState from '@/components/ui/EmptyState.vue'

const groups = ref([])
const group = ref('')
const subjects = ref([])
const subject = ref('')
const data = ref(null)
const loading = ref(false)

// Учебный период (архив прошлых семестров)
const terms = ref([])
const term = ref(null)
const currentTerm = ref(null)
const isArchive = computed(() => term.value && currentTerm.value &&
  (term.value.year !== currentTerm.value.year || term.value.semester !== currentTerm.value.semester))
function termLabel(t) { return t ? `${t.year} · ${t.semester === 1 ? 'осенний' : 'весенний'} семестр` : '' }
function termKey(t) { return t ? `${t.year}|${t.semester}` : '' }
function selectTerm(k) { term.value = terms.value.find((t) => termKey(t) === k) || currentTerm.value }
function termParams() { return term.value ? { year: term.value.year, semester: term.value.semester } : {} }

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
</script>

<template>
  <div class="space-y-4">
    <EmptyState v-if="!groups.length" title="Вы не куратор"
                message="Администратор пока не назначил вам курируемые группы." />
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
        <span class="text-xs text-text3 sm:ml-auto sm:self-center">👁 Только просмотр (куратор)</span>
      </div>

      <EmptyState v-if="!subjects.length" title="Нет предметов"
                  :message="`В группе ${group} за этот семестр нет занятий.`" />
      <p v-else-if="loading" class="text-sm text-text3">Загрузка…</p>
      <EmptyState v-else-if="!data?.students?.length" title="Нет студентов" :message="`В группе ${group} нет студентов.`" />

      <div v-else class="overflow-x-auto rounded-lg border border-border bg-card shadow-card">
        <table class="w-max text-sm">
          <thead>
            <tr class="border-b-2 border-accent bg-bg2 text-text2">
              <th class="sticky left-0 z-10 bg-bg2 px-4 py-3 text-left text-tiny font-semibold uppercase tracking-wide">Студент</th>
              <th v-for="l in data.lessons" :key="l.id" class="w-28 border-l border-border align-top px-2 py-2">
                <div class="text-xs font-bold text-text">{{ l.type }} №{{ l.number }}</div>
                <div class="text-[11px] font-normal normal-case text-text3">{{ l.date || '—' }}</div>
              </th>
              <th class="border-l-2 border-accent/40 px-4 py-3 text-right text-tiny font-semibold uppercase tracking-wide">Средн.</th>
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
  </div>
</template>
