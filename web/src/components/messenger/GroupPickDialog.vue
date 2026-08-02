<script setup>
// GroupPickDialog — выбор УЧЕБНОЙ ГРУППЫ из списка (объявления и т.п.).
// Раньше группу вводили руками через window.prompt: имена вида «К75/1» набирали с
// опечаткой (лишний пробел, латинская «K»), канал не находился, и это выглядело как
// «кнопка не работает». Список приходит с сервера — ошибиться нечем.
import { ref, computed, onMounted } from 'vue'
import { X } from '@lucide/vue'
import { messengerApi } from '@/api/endpoints'
import { useLocaleStore } from '@/stores/locale'

const locale = useLocaleStore()

const props = defineProps({
  title: { type: String, default: 'Выберите группу' },
  hint: { type: String, default: '' },
  submitLabel: { type: String, default: 'Открыть' },
  curatedOnly: { type: Boolean, default: false },   // только курируемые (отчёты)
  // Ошибку и «занятость» ведёт РОДИТЕЛЬ: он же делает запрос и знает его исход. Окно при
  // ошибке НЕ закрывается — иначе непонятно, получилось или нет.
  error: { type: String, default: '' },
  busy: { type: Boolean, default: false },
})
const emit = defineEmits(['pick', 'close'])

const groups = ref([])
const loading = ref(true)
const loadError = ref('')
const chosen = ref('')

const shown = computed(() =>
  props.curatedOnly ? groups.value.filter(g => g.curated) : groups.value)

onMounted(async () => {
  try {
    groups.value = (await messengerApi.myGroups()).data.groups || []
    chosen.value = shown.value[0]?.name || ''
  } catch (e) {
    loadError.value = e?.response?.data?.detail || locale.t('groupPick.loadFailed', 'Не удалось получить список групп')
  } finally { loading.value = false }
})
</script>

<template>
  <div class="fixed inset-0 z-50 grid place-items-center p-4" style="background: var(--gb-overlay)"
       @click.self="emit('close')">
    <div class="w-full max-w-sm rounded-xl border border-border2 bg-card shadow-card">
      <div class="flex items-center justify-between border-b border-border p-4">
        <h3 class="font-title text-lg font-bold text-text">{{ title }}</h3>
        <button type="button" @click="emit('close')" class="grid size-8 place-items-center rounded-md text-text3 hover:bg-bg2 hover:text-text"><X class="size-5" /></button>
      </div>
      <div class="p-4">
        <p v-if="hint" class="mb-3 text-sm text-text2">{{ hint }}</p>
        <p v-if="loading" class="text-sm text-text3">{{ locale.t('groupPick.loading', 'Загружаем группы…') }}</p>
        <template v-else>
          <select v-if="shown.length" v-model="chosen"
                  class="w-full rounded-lg border border-border2 bg-card2 px-3 py-2 text-sm text-text outline-none focus:border-accent">
            <option v-for="g in shown" :key="g.name" :value="g.name">{{ g.name }}</option>
          </select>
          <p v-else class="text-sm text-text3">
            {{ curatedOnly ? locale.t('groupPick.noCurated', 'Вы не курируете ни одной группы.') : locale.t('groupPick.noGroups', 'Подходящих групп нет.') }}
          </p>
        </template>
        <p v-if="loadError || error"
           class="mt-3 rounded-lg border border-red/40 bg-red/10 p-2 text-xs text-red">{{ loadError || error }}</p>
      </div>
      <div class="flex justify-end gap-2 border-t border-border p-3">
        <button type="button" @click="emit('close')" class="rounded-lg border border-border2 px-4 py-2 text-sm text-text2 hover:bg-bg2">{{ locale.t('common.cancel') }}</button>
        <button type="button" :disabled="!chosen || busy" @click="emit('pick', chosen)"
                class="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white hover:bg-accent2 disabled:opacity-50">
          {{ busy ? locale.t('groupPick.opening', 'Открываем…') : submitLabel }}
        </button>
      </div>
    </div>
  </div>
</template>
