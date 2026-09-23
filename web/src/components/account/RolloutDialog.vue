<script setup>
/**
 * RolloutDialog.vue — «Выкатить данные групп» (4.0).
 *
 * В начале года группе раздают лист: №, ФИО, логин, пароль. Администратор выбирает
 * подраздел (колледж / бакалавриат / заочное), курс и группу; куратор видит только
 * СВОИ группы — но это решает СЕРВЕР (`/web/accounts/rollout/groups`), здесь лишь
 * показываем то, что пришло.
 *
 * Студенты отмечены по умолчанию; снятая галочка — студента нет в документе.
 * Пароли в документе:
 *   • уже выданный стартовый — тот же (повторная выгрузка не делает вчерашний лист ложью);
 *   • пароля не было — генерируется;
 *   • студент сменил пароль сам — пометка, пароль не сбрасывается;
 *   • пароль задан до 4.0 — пометка, НЕ сбрасывается (иначе первая же выгрузка выбила
 *     бы из журнала всех, кто им уже пользуется). Перевыдать можно явной галочкой,
 *     и только администратору.
 */
import { ref, computed, onMounted } from 'vue'
import { X } from '@lucide/vue'
import { accountApi } from '@/api/endpoints'
import AppButton from '@/components/ui/AppButton.vue'
import { useToast } from '@/composables/useToast'
import { useLocaleStore } from '@/stores/locale'
import { useAuthStore } from '@/stores/auth'

const emit = defineEmits(['close'])
const loc = useLocaleStore()
const toast = useToast()
const auth = useAuthStore()
const isAdmin = computed(() => auth.role === 'admin')

const sections = ref([])
const groups = ref([])
const section = ref('')
const course = ref(0)
const group = ref('')
const students = ref([])
const picked = ref(new Set())
const resetExisting = ref(false)
const loading = ref(true)
const busy = ref(false)
const error = ref('')

onMounted(async () => {
  try {
    const { data } = await accountApi.rolloutGroups()
    sections.value = data.sections || []
    groups.value = data.groups || []
    section.value = sections.value[0]?.key || ''
    //Куратору с одной группой нечего выбирать — сразу открываем её.
    if (groups.value.length === 1) pickGroup(groups.value[0].name)
  } catch (e) {
    error.value = e?.response?.data?.detail || loc.t('rollout.loadFailed', 'Не удалось загрузить группы')
  } finally { loading.value = false }
})

const inSection = computed(() => groups.value.filter((g) => g.section === section.value))
const courses = computed(() => [...new Set(inSection.value.map((g) => g.course || 0))].sort((a, b) => a - b))
const inCourse = computed(() => inSection.value.filter((g) => !course.value || (g.course || 0) === course.value))

function pickSection(k) { section.value = k; course.value = 0; group.value = ''; students.value = [] }

async function pickGroup(name) {
  group.value = name
  students.value = []
  error.value = ''
  try {
    const { data } = await accountApi.rolloutStudents(name)
    students.value = data.students || []
    picked.value = new Set(students.value.map((s) => s.id))
  } catch (e) {
    error.value = e?.response?.data?.detail || loc.t('rollout.loadFailed', 'Не удалось загрузить группы')
  }
}

function toggle(id) {
  const next = new Set(picked.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  picked.value = next
}
function toggleAll(on) { picked.value = on ? new Set(students.value.map((s) => s.id)) : new Set() }

function stateLabel(s) {
  if (s.state === 'issued') return loc.t('rollout.stateIssued', 'пароль выдан')
  if (s.state === 'changed') return loc.t('rollout.stateChanged', 'сменил пароль сам')
  if (s.state === 'preset') return loc.t('rollout.statePreset', 'пароль задан ранее')
  return loc.t('rollout.stateNone', 'будет выдан новый')
}

async function download() {
  if (!group.value || !picked.value.size) return
  busy.value = true
  error.value = ''
  try {
    const ids = students.value.filter((s) => picked.value.has(s.id)).map((s) => s.id)
    const { data: blob } = await accountApi.rolloutExport(group.value, ids, isAdmin.value && resetExisting.value)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${loc.t('rollout.fileName', 'Данные_входа')}_${group.value.replaceAll('/', '-')}.xlsx`
    a.click()
    URL.revokeObjectURL(url)
    toast.success(loc.t('rollout.done', 'Документ сохранён. Храните его в недоступном месте.'))
    await pickGroup(group.value)       //состояния обновились: «будет выдан» → «выдан»
  } catch (e) {
    let msg = ''
    try { msg = JSON.parse(await e?.response?.data?.text?.())?.detail || '' } catch { msg = '' }
    error.value = msg || loc.t('rollout.failed', 'Не удалось подготовить документ')
  } finally { busy.value = false }
}
</script>

<template>
  <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" @click.self="emit('close')">
    <div class="flex max-h-[88vh] w-full max-w-xl flex-col rounded-lg border border-border bg-card shadow-card">
      <div class="flex items-center justify-between border-b border-border px-5 py-3">
        <h3 class="font-title text-lg font-bold text-text">{{ loc.t('rollout.title', 'Выкатить данные групп') }}</h3>
        <button type="button" class="text-text3 hover:text-text" :aria-label="loc.t('common.close', 'Закрыть')" @click="emit('close')">
          <X class="size-5" />
        </button>
      </div>

      <div class="min-h-0 flex-1 space-y-3 overflow-y-auto px-5 py-3">
        <p v-if="loading" class="py-4 text-center text-sm text-text3">{{ loc.t('common.loading') }}</p>
        <template v-else>
          <p class="text-tiny text-text3">{{ loc.t('rollout.hint', 'Документ .xlsx: №, ФИО, логин, пароль. Уже выданные пароли повторяются, сменённые самим студентом не показываются.') }}</p>

          <div v-if="sections.length > 1" class="flex flex-wrap gap-2">
            <button v-for="s in sections" :key="s.key" type="button"
                    class="rounded-full border px-3 py-1.5 text-xs font-medium transition-colors"
                    :class="section === s.key ? 'border-accent bg-accent text-white' : 'border-border2 bg-card2 text-text2 hover:border-accent/50'"
                    @click="pickSection(s.key)">{{ loc.t(`rollout.section.${s.key}`, s.label) }}</button>
          </div>

          <div v-if="courses.length > 1" class="flex flex-wrap gap-2">
            <button type="button" class="rounded-full border px-3 py-1.5 text-xs font-medium"
                    :class="!course ? 'border-accent bg-accent text-white' : 'border-border2 bg-card2 text-text2'"
                    @click="course = 0">{{ loc.t('adminGroups.allCourses', 'Все курсы') }}</button>
            <button v-for="c in courses" :key="c" type="button" class="rounded-full border px-3 py-1.5 text-xs font-medium"
                    :class="course === c ? 'border-accent bg-accent text-white' : 'border-border2 bg-card2 text-text2'"
                    @click="course = c">{{ c ? loc.t('adminGroups.courseN', { n: c }) : loc.t('rollout.courseUnknown', 'курс не известен') }}</button>
          </div>

          <select :value="group" class="h-10 w-full rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent"
                  @change="pickGroup($event.target.value)">
            <option value="" disabled>{{ loc.t('rollout.pickGroup', 'Выберите группу') }}</option>
            <option v-for="g in inCourse" :key="g.name" :value="g.name">{{ g.name }} · {{ loc.t('rollout.studentsN', { n: g.students }) }}</option>
          </select>

          <div v-if="group">
            <div class="mb-1 flex items-center justify-between text-tiny text-text3">
              <span>{{ loc.t('rollout.pickedN', { n: picked.size, total: students.length }) }}</span>
              <span class="space-x-3">
                <button type="button" class="underline" @click="toggleAll(true)">{{ loc.t('rollout.all', 'всех') }}</button>
                <button type="button" class="underline" @click="toggleAll(false)">{{ loc.t('rollout.none', 'никого') }}</button>
              </span>
            </div>
            <p v-if="!students.length" class="py-3 text-center text-sm text-text3">{{ loc.t('rollout.noStudents', 'В группе нет студентов') }}</p>
            <ul class="divide-y divide-border rounded-md border border-border">
              <li v-for="(s, i) in students" :key="s.id">
                <label class="flex cursor-pointer items-center gap-3 px-3 py-2 text-sm hover:bg-bg2/60">
                  <input type="checkbox" class="size-4" :checked="picked.has(s.id)" @change="toggle(s.id)" />
                  <span class="w-6 text-right text-text3">{{ i + 1 }}</span>
                  <span class="min-w-0 flex-1 truncate text-text">{{ s.name }}</span>
                  <span class="shrink-0 text-tiny" :class="s.state === 'changed' ? 'text-orange' : 'text-text3'">{{ stateLabel(s) }}</span>
                </label>
              </li>
            </ul>
          </div>

          <label v-if="isAdmin && group" class="flex items-start gap-2 text-sm text-text2">
            <input v-model="resetExisting" type="checkbox" class="mt-0.5 size-4" />
            <span>{{ loc.t('rollout.resetExisting', 'Перевыдать пароли тем, у кого пароль задан ранее') }}
              <span class="block text-tiny text-text3">{{ loc.t('rollout.resetExistingHint', 'Их текущий пароль перестанет работать. Тех, кто сменил пароль сам, это не касается.') }}</span></span>
          </label>
          <p v-if="error" class="text-sm text-red">{{ error }}</p>
        </template>
      </div>

      <div class="flex justify-end gap-2 border-t border-border px-5 py-3">
        <AppButton variant="ghost" size="sm" @click="emit('close')">{{ loc.t('common.close', 'Закрыть') }}</AppButton>
        <AppButton variant="green" size="sm" :disabled="busy || !group || !picked.size" @click="download">
          {{ busy ? loc.t('rollout.preparing', 'Готовим…') : loc.t('rollout.download', 'Скачать .xlsx') }}
        </AppButton>
      </div>
    </div>
  </div>
</template>
