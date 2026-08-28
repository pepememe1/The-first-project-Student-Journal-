<script setup>
// TeacherSuggestionsDialog — «кто ведёт предмет» по расписанию портала.
//
// ━━ ЗАЧЕМ ━━
// Портал ВСГУТУ пишет преподавателя в каждой ячейке, но у нас связь «кто ведёт»
// (`SubjectHours.teacher_id`) велась отдельно и руками. Поэтому смена расписания меняла
// предметы группы и молча оставляла преподавателя без журнала — жалоба Ярослава
// 28.08.2026: «изменилось расписание, а предметы, которые преподаёт препод, не
// изменились».
//
// ⚠️ ЭКРАН ПРЕДЛАГАЕТ, А НЕ НАЗНАЧАЕТ. Разбор ФИО в ячейке портала best-effort: на живых
// данных встречается «АФХД ИМТЕНОВА Л.Ф.» — к фамилии прилипла аббревиатура предмета.
// Молчаливое назначение по такой строке дало бы чужому преподавателю доступ к оценкам и
// посещаемости чужой группы. Поэтому применяется только отмеченное человеком.
//
// ⚠️ Строки, требующие решения, идут ПЕРВЫМИ (сортирует сервер), а «уже согласовано» и
// «портал молчит» — в конце и свёрнуты. Список на сотню строк, где нужное перемешано с
// ненужным, читают один раз, а потом перестают.
import { ref, computed, onMounted } from 'vue'
import { X, Check, AlertTriangle, HelpCircle, Users, Minus } from '@lucide/vue'
import AppButton from '@/components/ui/AppButton.vue'
import { useLocaleStore } from '@/stores/locale'
import { useToast } from '@/composables/useToast'
import { adminApi } from '@/api/endpoints'

const emit = defineEmits(['close', 'applied'])
const locale = useLocaleStore()
const toast = useToast()

const loading = ref(true)
const building = ref(false)
const items = ref([])
const saving = ref(false)
//Выбор человека: hours_id -> teacher_id. Пусто = «не трогать эту строку».
const picked = ref({})
const showSettled = ref(false)

//Состояния, требующие решения. `ok` и `no_portal` сюда не входят: по ним делать нечего.
const ACTIONABLE = ['assign', 'conflict', 'ambiguous', 'unknown']

const STATE_META = {
  assign: { icon: Check, cls: 'text-green', key: 'assign' },
  conflict: { icon: Users, cls: 'text-orange', key: 'conflict' },
  ambiguous: { icon: HelpCircle, cls: 'text-orange', key: 'ambiguous' },
  unknown: { icon: AlertTriangle, cls: 'text-red', key: 'unknown' },
  no_portal: { icon: Minus, cls: 'text-text3', key: 'noPortal' },
  ok: { icon: Check, cls: 'text-text3', key: 'ok' },
}

const actionable = computed(() => items.value.filter((i) => ACTIONABLE.includes(i.state)))
const settled = computed(() => items.value.filter((i) => !ACTIONABLE.includes(i.state)))

//Сколько строк реально уедет на сервер — это же число показываем на кнопке, чтобы
//«Применить» никогда не означало «применить неизвестно что».
const chosenCount = computed(() =>
  Object.entries(picked.value).filter(([, v]) => v !== undefined && v !== null).length)

async function load() {
  loading.value = true
  try {
    const { data } = await adminApi.teacherSuggestions()
    items.value = data.items || []
    building.value = !!data.building
    //Уверенные предложения отмечаем ЗАРАНЕЕ: они и есть основная работа экрана, а
    //снять галочку дешевле, чем поставить сотню. Спорные (conflict/ambiguous) не
    //отмечаем никогда — там выбор и есть суть.
    const pre = {}
    for (const it of items.value) {
      if (it.state === 'assign' && it.suggested_teacher_id) {
        pre[it.hours_id] = it.suggested_teacher_id
      }
    }
    picked.value = pre
  } catch {
    items.value = []
    toast.error(locale.t('teacherSuggest.loadFailed', 'Не удалось получить подсказки из расписания'))
  } finally { loading.value = false }
}
onMounted(load)

function toggle(it, teacherId) {
  const cur = picked.value[it.hours_id]
  const next = { ...picked.value }
  if (cur === teacherId) delete next[it.hours_id]
  else next[it.hours_id] = teacherId
  picked.value = next
}

async function apply() {
  const entries = Object.entries(picked.value)
    .filter(([, v]) => v !== undefined && v !== null)
    .map(([hours_id, teacher_id]) => ({ hours_id, teacher_id }))
  if (!entries.length) return
  saving.value = true
  try {
    const { data } = await adminApi.applyTeachers(entries)
    toast.success(locale.t('teacherSuggest.done', { n: data.applied }))
    emit('applied')
    await load()
  } catch {
    toast.error(locale.t('teacherSuggest.applyFailed', 'Не удалось применить назначения'))
  } finally { saving.value = false }
}
</script>

<template>
  <div class="fixed inset-0 z-[70] flex items-center justify-center bg-black/50 p-3"
       @click.self="emit('close')">
    <div class="flex max-h-[90vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-border2 bg-card shadow-xl">
      <div class="flex items-center gap-2 border-b border-border2 px-4 py-3">
        <h2 class="min-w-0 flex-1 truncate text-base font-semibold text-text">
          {{ locale.t('teacherSuggest.title', 'Кто ведёт предметы — по расписанию') }}
        </h2>
        <button type="button" @click="emit('close')" class="rounded-lg p-1 text-text3 hover:text-accent">
          <X class="size-5" />
        </button>
      </div>

      <div class="min-h-0 flex-1 overflow-y-auto p-4">
        <p v-if="loading" class="py-8 text-center text-sm text-text3">
          {{ locale.t('common.loading', 'Загрузка…') }}
        </p>

        <template v-else>
          <!-- Снимок расписания строится в фоне — сказать об этом честно, иначе неполный
               список читается как «портал ничего не знает». -->
          <p v-if="building" class="mb-3 rounded-lg border border-border2 bg-bg2 px-3 py-2 text-xs text-text2">
            {{ locale.t('teacherSuggest.building', 'Расписание ещё дочитывается с портала — список может быть неполным, зайдите ещё раз через минуту.') }}
          </p>

          <p class="mb-3 text-xs text-text3">
            {{ locale.t('teacherSuggest.hint', 'Отмечено — то, что будет назначено. Ничего не применяется, пока вы не нажмёте «Применить».') }}
          </p>

          <p v-if="!actionable.length" class="py-6 text-center text-sm text-text3">
            {{ locale.t('teacherSuggest.allSettled', 'Расхождений с расписанием нет') }}
          </p>

          <div v-else class="flex flex-col gap-2">
            <div v-for="it in actionable" :key="it.hours_id"
                 class="rounded-xl border border-border2 bg-bg2 p-3">
              <div class="mb-2 flex min-w-0 items-center gap-2">
                <component :is="STATE_META[it.state].icon" class="size-4 shrink-0"
                           :class="STATE_META[it.state].cls" />
                <span class="min-w-0 flex-1 truncate text-sm font-semibold text-text">
                  {{ it.group }} · {{ it.subject }}
                </span>
                <span class="shrink-0 text-tiny" :class="STATE_META[it.state].cls">
                  {{ locale.t(`teacherSuggest.state.${STATE_META[it.state].key}`, it.state) }}
                </span>
              </div>

              <p v-if="it.current_teacher" class="mb-2 text-xs text-text3">
                {{ locale.t('teacherSuggest.now', 'Сейчас') }}: {{ it.current_teacher }}
              </p>

              <!-- Варианты. Даже у «уверенного» показываем, ОТКУДА он взялся: строка
                   портала и число пар — иначе решение принимается вслепую. -->
              <div class="flex flex-col gap-1">
                <template v-for="p in it.portal" :key="p.name">
                  <button v-if="p.teacher_id" type="button" @click="toggle(it, p.teacher_id)"
                          class="flex w-full min-w-0 items-center gap-2 rounded-lg border px-2.5 py-1.5 text-left transition-colors"
                          :class="picked[it.hours_id] === p.teacher_id
                            ? 'border-accent bg-accent-glow' : 'border-border2 bg-card hover:border-accent'">
                    <span class="grid size-4 shrink-0 place-items-center rounded border"
                          :class="picked[it.hours_id] === p.teacher_id
                            ? 'border-accent bg-accent text-white' : 'border-border2'">
                      <Check v-if="picked[it.hours_id] === p.teacher_id" class="size-3" />
                    </span>
                    <span class="min-w-0 flex-1 truncate text-sm text-text">{{ p.teacher_name }}</span>
                    <span class="shrink-0 text-tiny text-text3">
                      {{ p.name }} · {{ locale.t('teacherSuggest.lessons', { n: p.lessons }) }}
                    </span>
                  </button>

                  <!-- Неоднозначно: портал назвал фамилию, а подходящих людей несколько.
                       Показываем всех — выбирает человек. -->
                  <template v-else-if="p.candidates.length">
                    <p class="px-1 text-tiny text-text3">
                      {{ p.name }} — {{ locale.t('teacherSuggest.pickOne', 'кто именно?') }}
                    </p>
                    <button v-for="c in p.candidates" :key="c.id" type="button"
                            @click="toggle(it, c.id)"
                            class="flex w-full min-w-0 items-center gap-2 rounded-lg border px-2.5 py-1.5 text-left transition-colors"
                            :class="picked[it.hours_id] === c.id
                              ? 'border-accent bg-accent-glow' : 'border-border2 bg-card hover:border-accent'">
                      <span class="grid size-4 shrink-0 place-items-center rounded border"
                            :class="picked[it.hours_id] === c.id
                              ? 'border-accent bg-accent text-white' : 'border-border2'">
                        <Check v-if="picked[it.hours_id] === c.id" class="size-3" />
                      </span>
                      <span class="min-w-0 flex-1 truncate text-sm text-text">{{ c.name }}</span>
                    </button>
                  </template>

                  <!-- Такого человека у нас нет вовсе: назначать нечего, но знать надо. -->
                  <p v-else class="px-1 text-tiny text-text3">
                    {{ p.name }} — {{ locale.t('teacherSuggest.noAccount', 'нет такого преподавателя в системе') }}
                  </p>
                </template>
              </div>
            </div>
          </div>

          <!-- Согласованное и «портал молчит» — свёрнуто: это не работа, это фон. -->
          <button v-if="settled.length" type="button" @click="showSettled = !showSettled"
                  class="mt-3 text-xs text-text3 underline-offset-2 hover:text-accent hover:underline">
            {{ showSettled ? locale.t('teacherSuggest.hideSettled', 'Скрыть остальные')
                           : locale.t('teacherSuggest.showSettled', { n: settled.length }) }}
          </button>
          <div v-if="showSettled" class="mt-2 flex flex-col gap-1">
            <div v-for="it in settled" :key="it.hours_id"
                 class="flex min-w-0 items-center gap-2 rounded-lg border border-border2 bg-card px-2.5 py-1.5">
              <component :is="STATE_META[it.state].icon" class="size-3.5 shrink-0 text-text3" />
              <span class="min-w-0 flex-1 truncate text-xs text-text2">{{ it.group }} · {{ it.subject }}</span>
              <span class="shrink-0 text-tiny text-text3">
                {{ it.current_teacher || locale.t(`teacherSuggest.state.${STATE_META[it.state].key}`, it.state) }}
              </span>
            </div>
          </div>
        </template>
      </div>

      <div class="flex shrink-0 items-center justify-between gap-2 border-t border-border2 px-4 py-3">
        <span class="min-w-0 truncate text-xs text-text3">
          {{ locale.t('teacherSuggest.selected', { n: chosenCount }) }}
        </span>
        <div class="flex shrink-0 gap-2">
          <AppButton variant="ghost" size="sm" @click="emit('close')">
            {{ locale.t('common.close', 'Закрыть') }}
          </AppButton>
          <AppButton size="sm" :disabled="!chosenCount || saving" @click="apply">
            {{ locale.t('teacherSuggest.apply', 'Применить') }}
          </AppButton>
        </div>
      </div>
    </div>
  </div>
</template>
