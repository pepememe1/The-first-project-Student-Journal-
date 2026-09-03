<script setup>
// AdminGroupArchive — архив УЧЕБНЫХ ГРУПП (03.09.2026, живая жалоба Влада: «начался
// новый учебный год, набрали новые группы, другие перешли на новый курс; если раньше
// группа была, но не перешла на следующий курс — она идёт в архив, где видно предметы,
// студентов, закреплённых преподавателей и куратора»).
//
// ⚠️ Кандидаты — ПРЕДЛОЖЕНИЕ, а не свершившийся факт. Группа пропадает из расписания и
// при сбое портала, а за ней живые студенты и оценки: автоматический архив в такой день
// унёс бы половину колледжа молча. Решение принимает человек, кнопкой.
//
// ⚠️ Имя группы уходит на сервер ПАРАМЕТРОМ и в ТЕЛЕ, никогда не сегментом пути:
// Starlette раскодирует `%2F` до роутинга, и «К74/1» разваливает маршрут.
import { ref, onMounted } from 'vue'
import { Archive, RotateCcw, RefreshCw, Users, BookOpen, GraduationCap } from '@lucide/vue'
import { adminApi } from '@/api/endpoints'
import EmptyState from '@/components/ui/EmptyState.vue'
import Badge from '@/components/ui/Badge.vue'
import { useLocaleStore } from '@/stores/locale'

const locale = useLocaleStore()
const loading = ref(false)
const busy = ref('')
const archived = ref([])
const candidates = ref([])
const opened = ref('')
const detail = ref(null)

async function load() {
  loading.value = true
  try {
    const { data } = await adminApi.groupArchive()
    archived.value = data.archived || []
    candidates.value = data.candidates || []
  } catch { archived.value = []; candidates.value = [] } finally { loading.value = false }
}

async function open(group) {
  if (opened.value === group) { opened.value = ''; detail.value = null; return }
  opened.value = group
  detail.value = null
  try { detail.value = (await adminApi.groupArchiveDetail(group)).data } catch { detail.value = null }
}

async function setArchived(group, value, reason = '') {
  busy.value = group
  try {
    await adminApi.setGroupArchived(group, value, reason)
    // Открытую карточку закрываем: она относилась к прежнему состоянию, и оставить её
    // значило бы показывать «в архиве» рядом с группой, только что возвращённой в работу.
    if (opened.value === group) { opened.value = ''; detail.value = null }
    await load()
  } finally { busy.value = '' }
}

async function witness() {
  busy.value = '*'
  try { await adminApi.groupArchiveWitness(); await load() } finally { busy.value = '' }
}

onMounted(load)
</script>

<template>
  <div class="space-y-6">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 class="text-xl font-semibold" style="color: var(--gb-text)">
          {{ locale.t('groupArchive.title', 'Архив групп') }}
        </h1>
        <p class="mt-1 text-sm" style="color: var(--gb-text-dim)">
          {{ locale.t('groupArchive.hint', 'Выпустившиеся группы не удаляются: студенты, оценки и занятия остаются доступны для просмотра.') }}
        </p>
      </div>
      <button class="gb-btn gb-btn-ghost" :disabled="busy === '*'" @click="witness">
        <RefreshCw :size="16" /> {{ locale.t('groupArchive.witness', 'Запомнить текущие курсы') }}
      </button>
    </div>

    <!-- Кандидаты -->
    <section v-if="candidates.length" class="gb-card p-4">
      <h2 class="mb-1 font-medium" style="color: var(--gb-text)">
        {{ locale.t('groupArchive.candidates', 'Похоже, выпустились') }}
      </h2>
      <p class="mb-3 text-sm" style="color: var(--gb-text-dim)">
        {{ locale.t('groupArchive.candidatesHint', 'Это предположение, а не решение — проверьте перед тем, как убирать.') }}
      </p>
      <ul class="space-y-2">
        <li v-for="c in candidates" :key="c.group"
            class="flex flex-wrap items-center justify-between gap-3 rounded-lg px-3 py-2"
            style="background: var(--gb-surface-2)">
          <div class="min-w-0">
            <div class="flex items-center gap-2">
              <span class="font-medium" style="color: var(--gb-text)">{{ c.group }}</span>
              <Badge tone="warn">{{ c.students }} {{ locale.t('groupArchive.students', 'студентов') }}</Badge>
            </div>
            <div class="text-sm" style="color: var(--gb-text-dim)">{{ c.reason }}</div>
          </div>
          <button class="gb-btn gb-btn-ghost" :disabled="busy === c.group"
                  @click="setArchived(c.group, true, c.reason)">
            <Archive :size="16" /> {{ locale.t('groupArchive.toArchive', 'В архив') }}
          </button>
        </li>
      </ul>
    </section>

    <!-- Уже в архиве -->
    <section class="gb-card p-4">
      <h2 class="mb-3 font-medium" style="color: var(--gb-text)">
        {{ locale.t('groupArchive.archived', 'В архиве') }}
      </h2>

      <EmptyState v-if="!loading && !archived.length"
                  :title="locale.t('groupArchive.empty', 'Архив пуст')"
                  :hint="locale.t('groupArchive.emptyHint', 'Сюда попадают группы, которые больше не учатся.')" />

      <ul v-else class="space-y-2">
        <li v-for="g in archived" :key="g.group" class="rounded-lg" style="background: var(--gb-surface-2)">
          <div class="flex flex-wrap items-center justify-between gap-3 px-3 py-2">
            <button class="min-w-0 text-left" @click="open(g.group)">
              <div class="flex items-center gap-2">
                <span class="font-medium" style="color: var(--gb-text)">{{ g.group }}</span>
                <Badge>{{ g.students }} {{ locale.t('groupArchive.students', 'студентов') }}</Badge>
              </div>
              <div class="text-sm" style="color: var(--gb-text-dim)">{{ g.archived_reason }}</div>
            </button>
            <button class="gb-btn gb-btn-ghost" :disabled="busy === g.group"
                    @click="setArchived(g.group, false)">
              <RotateCcw :size="16" /> {{ locale.t('groupArchive.restore', 'Вернуть в работу') }}
            </button>
          </div>

          <!-- Карточка: ровно то, что просили видеть в архиве -->
          <div v-if="opened === g.group && detail" class="border-t px-3 py-3"
               style="border-color: var(--gb-border)">
            <!-- ⚠️ `grid-cols-1` обязателен: без него на телефоне нет ни одной явной
                 колонки, браузер заводит неявную дорожку `auto`, и длинное название
                 предмета или ФИО растягивает ВСЮ колонку шире экрана. -->
            <div class="grid grid-cols-1 gap-4 md:grid-cols-3">
              <div>
                <div class="mb-1 flex items-center gap-2 text-sm font-medium" style="color: var(--gb-text)">
                  <BookOpen :size="15" /> {{ locale.t('groupArchive.subjects', 'Предметы') }}
                </div>
                <ul class="space-y-1 text-sm" style="color: var(--gb-text-dim)">
                  <li v-for="s in detail.subjects" :key="s.subject">
                    {{ s.subject }}
                    <span v-if="s.teachers.length"> — {{ s.teachers.join(', ') }}</span>
                  </li>
                  <li v-if="!detail.subjects.length">—</li>
                </ul>
              </div>
              <div>
                <div class="mb-1 flex items-center gap-2 text-sm font-medium" style="color: var(--gb-text)">
                  <Users :size="15" /> {{ locale.t('groupArchive.studentsList', 'Студенты') }}
                </div>
                <ul class="space-y-1 text-sm" style="color: var(--gb-text-dim)">
                  <li v-for="s in detail.students" :key="s.id">{{ s.name }}</li>
                  <li v-if="!detail.students.length">—</li>
                </ul>
              </div>
              <div>
                <div class="mb-1 flex items-center gap-2 text-sm font-medium" style="color: var(--gb-text)">
                  <GraduationCap :size="15" /> {{ locale.t('groupArchive.curators', 'Кураторы') }}
                </div>
                <ul class="space-y-1 text-sm" style="color: var(--gb-text-dim)">
                  <li v-for="c in detail.curators" :key="c">{{ c }}</li>
                  <li v-if="!detail.curators.length">—</li>
                </ul>
              </div>
            </div>
          </div>
        </li>
      </ul>
    </section>
  </div>
</template>
