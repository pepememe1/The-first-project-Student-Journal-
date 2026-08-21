<script setup>
// CoursesPage — список учебных курсов (аналог раздела «Курсы» портала колледжа).
// Скоуп считает сервер: студент видит свою группу, преподаватель — свои, админ — все.
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { BookOpen, Search, Plus, Paperclip, ClipboardList, Archive, Loader2, X } from '@lucide/vue'
import { coursesApi } from '@/api/endpoints'
import { useAuthStore } from '@/stores/auth'
import { useLocaleStore } from '@/stores/locale'

const router = useRouter()
const auth = useAuthStore()
const loc = useLocaleStore()
const t = (k, f) => loc.t(k, f)

const courses = ref([])
const loading = ref(true)
const q = ref('')
const includeArchived = ref(false)
const canCreate = computed(() => auth.role === 'teacher' || auth.role === 'admin')

// Диалог создания
const showCreate = ref(false)
const draft = ref({ title: '', subject: '', group_name: '' })
const creating = ref(false)
const createError = ref('')

async function load() {
  loading.value = true
  try {
    const { data } = await coursesApi.list(q.value.trim(), includeArchived.value)
    courses.value = data.courses || []
  } catch { courses.value = [] } finally { loading.value = false }
}
onMounted(load)

function open(c) { router.push(`/${auth.role}/courses/${c.id}`) }

async function submitCreate() {
  const title = draft.value.title.trim()
  if (!title || creating.value) return
  creating.value = true; createError.value = ''
  try {
    const { data } = await coursesApi.create({
      title, subject: draft.value.subject.trim(), group_name: draft.value.group_name.trim(),
    })
    showCreate.value = false
    draft.value = { title: '', subject: '', group_name: '' }
    router.push(`/${auth.role}/courses/${data.id}`)
  } catch (e) {
    createError.value = e?.response?.data?.detail || t('courses.createError', 'Не удалось создать курс')
  } finally { creating.value = false }
}
</script>

<template>
  <div>
    <!-- Панель: поиск + создать -->
    <div class="mb-4 flex flex-wrap items-center gap-2">
      <div class="relative min-w-0 flex-1">
        <Search class="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-text3" />
        <input v-model="q" @keydown.enter="load" @input="load"
               :placeholder="t('courses.search', 'Поиск курса…')"
               class="h-input w-full rounded-lg border border-border2 bg-card pl-9 pr-3 text-sm text-text outline-none focus:border-accent" />
      </div>
      <label v-if="canCreate" class="flex shrink-0 items-center gap-1.5 text-xs text-text2">
        <input type="checkbox" v-model="includeArchived" @change="load" class="accent-[var(--gb-accent)]" />
        {{ t('courses.showArchived', 'С архивом') }}
      </label>
      <button v-if="canCreate" type="button" @click="showCreate = true"
              class="flex h-input shrink-0 items-center gap-1.5 rounded-lg bg-accent px-3.5 text-sm font-semibold text-white hover:bg-accent2">
        <Plus class="size-4" /> {{ t('courses.create', 'Создать курс') }}
      </button>
    </div>

    <div v-if="loading" class="grid place-items-center py-16 text-text3">
      <Loader2 class="size-6 animate-spin" />
    </div>

    <div v-else-if="!courses.length" class="grid place-items-center gap-2 py-16 text-center text-text3">
      <BookOpen class="size-10 opacity-40" />
      <p>{{ t('courses.empty', 'Курсов пока нет') }}</p>
    </div>

    <!-- Сетка карточек -->
    <div v-else class="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
      <button v-for="c in courses" :key="c.id" type="button" @click="open(c)"
              class="group flex flex-col rounded-xl border border-border2 bg-card p-4 text-left shadow-card transition-colors hover:border-accent">
        <div class="mb-2 flex items-start gap-2">
          <span class="grid size-9 shrink-0 place-items-center rounded-lg bg-accent-glow text-accent">
            <BookOpen class="size-5" />
          </span>
          <div class="min-w-0 flex-1">
            <p class="truncate text-xs text-text3">{{ c.subject || '—' }}<span v-if="c.group_name"> · {{ c.group_name }}</span></p>
            <p class="line-clamp-2 font-title text-sm font-bold text-text group-hover:text-accent">{{ c.title }}</p>
          </div>
          <Archive v-if="c.archived" class="size-4 shrink-0 text-text3" :title="t('courses.archived', 'В архиве')" />
        </div>
        <p v-if="c.authors?.length" class="mb-2 truncate text-xs text-text2">{{ c.authors.join(', ') }}</p>
        <div class="mt-auto flex items-center gap-3 text-xs text-text3">
          <span class="flex items-center gap-1"><Paperclip class="size-3.5" />{{ c.materials_count }}</span>
          <span class="flex items-center gap-1"><ClipboardList class="size-3.5" />{{ c.assignments_count }}</span>
        </div>
      </button>
    </div>

    <!-- Диалог создания -->
    <transition name="fade">
      <div v-if="showCreate" class="fixed inset-0 z-[70] grid place-items-center p-4"
           style="background: var(--gb-overlay)" @click.self="showCreate = false">
        <div class="w-full max-w-md rounded-xl border border-border2 bg-card p-4 shadow-card">
          <div class="mb-3 flex items-center gap-2">
            <BookOpen class="size-5 shrink-0 text-accent" />
            <p class="min-w-0 flex-1 truncate font-title text-base font-bold text-text">{{ t('courses.create', 'Создать курс') }}</p>
            <button type="button" @click="showCreate = false" :aria-label="t('common.close', 'Закрыть')"
                    class="grid size-7 shrink-0 place-items-center rounded text-text3 hover:bg-bg2 hover:text-text"><X class="size-4" /></button>
          </div>
          <label class="mb-1 block text-xs text-text2">{{ t('courses.fTitle', 'Название') }}</label>
          <input v-model="draft.title" maxlength="200"
                 class="mb-3 h-input w-full rounded-md border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent" />
          <div class="mb-3 grid grid-cols-2 gap-2">
            <div>
              <label class="mb-1 block text-xs text-text2">{{ t('courses.fSubject', 'Предмет') }}</label>
              <input v-model="draft.subject" maxlength="120"
                     class="h-input w-full rounded-md border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent" />
            </div>
            <div>
              <label class="mb-1 block text-xs text-text2">{{ t('courses.fGroup', 'Группа') }}</label>
              <input v-model="draft.group_name" maxlength="40" placeholder="К74-1"
                     class="h-input w-full rounded-md border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent" />
            </div>
          </div>
          <p v-if="auth.role === 'teacher'" class="mb-2 text-xs text-text3">
            {{ t('courses.teacherHint', 'Создать курс можно только по своей группе и предмету.') }}
          </p>
          <p v-if="createError" class="mb-2 text-xs text-red">{{ createError }}</p>
          <div class="flex justify-end gap-2">
            <button type="button" @click="showCreate = false"
                    class="rounded-md border border-border2 px-3 py-2 text-sm text-text2 hover:border-accent">{{ t('common.cancel', 'Отмена') }}</button>
            <button type="button" @click="submitCreate" :disabled="!draft.title.trim() || creating"
                    class="flex items-center gap-1.5 rounded-md bg-accent px-3 py-2 text-sm font-semibold text-white hover:bg-accent2 disabled:opacity-50">
              <Loader2 v-if="creating" class="size-4 animate-spin" />{{ t('courses.create', 'Создать курс') }}
            </button>
          </div>
        </div>
      </div>
    </transition>
  </div>
</template>

<style scoped>
.fade-enter-active, .fade-leave-active { transition: opacity 0.15s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
