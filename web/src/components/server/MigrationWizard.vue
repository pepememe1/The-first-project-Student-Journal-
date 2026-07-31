<script setup>
// MigrationWizard — перенос сервера на другую машину (например, с арендованного VPS на
// компьютер ВСГУТУ).
//
// ━━ ПОЧЕМУ ПОШАГОВО, А НЕ ОДНОЙ КНОПКОЙ ━━
// Переносится боевая база с персональными данными всего колледжа. Кнопка «Перенести» с
// полоской прогресса скрывает главное: НА КАКОМ ИМЕННО шаге всё встало. А встать может
// на каждом — не хватило места, не пустил ключ, не поднялась служба. Человек, у которого
// сайт лежит, должен видеть точку отказа и подсказку, а не 40 %.
//
// ━━ ЧТО ЗДЕСЬ НАМЕРЕННО НЕ АВТОМАТИЗИРОВАНО ━━
// Старый сервер НЕ удаляется и НЕ выключается насовсем. Он остаётся рабочим запасным
// вариантом: пока новый не проверен живыми людьми, стирать единственную работающую
// копию нельзя. Переключение домена тоже делается руками — это смена DNS, и она не
// должна происходить как побочный эффект нажатия кнопки.
import { ref } from 'vue'
import { Check, X, ChevronRight, TriangleAlert } from '@lucide/vue'
import { deskServerApi } from '@/api/endpoints'
import AppButton from '@/components/ui/AppButton.vue'

const props = defineProps({
  servers: { type: Array, default: () => [] },
})

const source = ref('')
const target = ref('')
const plan = ref(null)
const busy = ref(false)
const error = ref('')
// Состояние по шагам: { [id]: { ok, log, hint, done } }
const state = ref({})
const current = ref('')

async function buildPlan() {
  error.value = ''
  plan.value = null
  state.value = {}
  if (!source.value || !target.value) { error.value = 'Выберите оба сервера'; return }
  busy.value = true
  try {
    plan.value = (await deskServerApi.migrationPlan(source.value, target.value)).data
  } catch (e) {
    error.value = e?.response?.data?.detail || 'Не удалось составить план'
  } finally {
    busy.value = false
  }
}

async function runStep(stepId) {
  busy.value = true
  current.value = stepId
  error.value = ''
  try {
    const { data } = await deskServerApi.migrationStep(source.value, target.value, stepId)
    state.value = { ...state.value, [stepId]: { ...data, done: true } }
  } catch (e) {
    state.value = {
      ...state.value,
      [stepId]: { ok: false, done: true, log: '', hint: e?.response?.data?.detail || 'Шаг не выполнен' },
    }
  } finally {
    busy.value = false
    current.value = ''
  }
}

// Шаг доступен, только когда ВСЕ предыдущие прошли. Порядок здесь не украшение:
// копировать данные до остановки службы значит скопировать базу в момент записи.
function unlocked(index) {
  if (!plan.value) return false
  return plan.value.steps.slice(0, index).every((s) => state.value[s.id]?.ok)
}

const named = (id) => props.servers.find((s) => s.id === id)?.name || id
</script>

<template>
  <div class="flex flex-col gap-4">
    <div class="grid gap-3 sm:grid-cols-2">
      <label class="block">
        <span class="mb-1 block text-sm font-medium text-text2">Откуда (работает сейчас)</span>
        <select v-model="source"
                class="h-10 w-full rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent">
          <option value="">— выберите —</option>
          <option v-for="s in servers" :key="s.id" :value="s.id">{{ s.name }} · {{ s.host }}</option>
        </select>
      </label>
      <label class="block">
        <span class="mb-1 block text-sm font-medium text-text2">Куда (новый сервер)</span>
        <select v-model="target"
                class="h-10 w-full rounded-sm border border-border2 bg-card2 px-3 text-sm text-text outline-none focus:border-accent">
          <option value="">— выберите —</option>
          <option v-for="s in servers" :key="s.id" :value="s.id">{{ s.name }} · {{ s.host }}</option>
        </select>
      </label>
    </div>

    <div class="flex flex-wrap items-center gap-3">
      <AppButton :disabled="busy" @click="buildPlan">Составить план</AppButton>
      <p v-if="error" class="text-sm text-red">{{ error }}</p>
    </div>

    <template v-if="plan">
      <div class="flex items-start gap-2.5 rounded-lg border border-yellow/50 bg-card2 p-3 text-sm text-text2">
        <TriangleAlert class="mt-0.5 size-4 shrink-0 text-yellow" />
        <p>{{ plan.warning }}</p>
      </div>

      <ol class="flex flex-col gap-2">
        <li v-for="(s, i) in plan.steps" :key="s.id"
            class="rounded-lg border p-3"
            :class="state[s.id]?.done
              ? (state[s.id].ok ? 'border-accent/50' : 'border-red/50')
              : 'border-border'">
          <div class="flex items-center gap-3">
            <span class="grid size-7 shrink-0 place-items-center rounded-full text-xs font-bold"
                  :class="state[s.id]?.done
                    ? (state[s.id].ok ? 'bg-accent text-white' : 'bg-red text-white')
                    : 'bg-card2 text-text3'">
              <Check v-if="state[s.id]?.ok" class="size-4" />
              <X v-else-if="state[s.id]?.done" class="size-4" />
              <template v-else>{{ i + 1 }}</template>
            </span>
            <span class="min-w-0 flex-1 text-sm font-medium text-text">{{ s.title }}</span>
            <AppButton v-if="!state[s.id]?.ok" variant="ghost"
                       :disabled="busy || !unlocked(i)"
                       @click="runStep(s.id)">
              {{ current === s.id ? 'Выполняем…' : (state[s.id]?.done ? 'Повторить' : 'Выполнить') }}
              <ChevronRight class="ml-1 inline size-4" />
            </AppButton>
          </div>

          <pre v-if="state[s.id]?.log"
               class="mt-2 max-h-40 overflow-auto whitespace-pre-wrap break-all rounded-sm bg-card2 p-2 font-mono text-tiny text-text3">{{ state[s.id].log }}</pre>
          <p v-if="state[s.id]?.hint" class="mt-2 text-xs"
             :class="state[s.id].ok ? 'text-text3' : 'text-red'">{{ state[s.id].hint }}</p>
        </li>
      </ol>

      <div v-if="plan.steps.every((s) => state[s.id]?.ok)"
           class="rounded-lg border border-accent/50 bg-card2 p-3 text-sm text-text2">
        <p class="font-semibold text-text">Перенос завершён.</p>
        <p class="mt-1">
          Новый сервер ({{ named(target) }}) отвечает. Осталось РУЧНОЕ действие: перевести
          домен на его адрес в DNS и убедиться, что сертификат выпустился.
          Старый сервер ({{ named(source) }}) не тронут — пока новый не проверен людьми,
          не выключайте его.
        </p>
      </div>
    </template>
  </div>
</template>
