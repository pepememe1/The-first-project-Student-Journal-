<script setup>
// ScaleConversionDialog — «вы меняете систему оценивания»: что станет с уже поставленными
// оценками и выбор в спорных случаях (73 балла → «3» или «4»). Правила перевода живут
// на сервере (grading.convert_scale_value), здесь только показ и выбор человека.
// Спорные строки подсвечены; по умолчанию выбрано ближайшее значение (ничья — вниз).
import { ref, computed } from 'vue'
import { teacherApi } from '@/api/endpoints'
import { useLocaleStore } from '@/stores/locale'
import { SCALES } from '@/utils/grading'
import AppButton from '@/components/ui/AppButton.vue'
import StickyXScroll from '@/components/ui/StickyXScroll.vue'

const props = defineProps({ plan: { type: Object, required: true } })
const emit = defineEmits(['close', 'applied'])
const loc = useLocaleStore()

const PAGE = 50
const page = ref(0)
const saving = ref(false)
const error = ref('')
const choices = ref(Object.fromEntries((props.plan.disputed || []).map((d) => [d.id, d.default])))
const pages = computed(() => Math.max(1, Math.ceil((props.plan.disputed || []).length / PAGE)))
const shown = computed(() => (props.plan.disputed || []).slice(page.value * PAGE, (page.value + 1) * PAGE))
const label = (id) => SCALES[id]?.label || id

function setAll(how) {
  for (const d of props.plan.disputed || []) {
    choices.value[d.id] = how === 'lower' ? d.options[0]
      : how === 'higher' ? d.options[d.options.length - 1] : d.default
  }
}

async function apply() {
  saving.value = true
  error.value = ''
  try {
    const { data } = await teacherApi.setScale(props.plan.to, choices.value)
    emit('applied', data)
  } catch {
    error.value = loc.t('scaleConv.failed', 'Не удалось сменить шкалу. Оценки не изменены.')
  } finally { saving.value = false }
}

</script>

<template>
  <div v-dialog class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" @click.self="!saving && emit('close')">
    <div class="flex max-h-[90vh] w-full max-w-3xl flex-col rounded-2xl border border-border bg-card p-5 shadow-card">
      <h2 class="text-lg font-bold text-text">{{ loc.t('scaleConv.title', 'Вы меняете систему оценивания') }}</h2>
      <p class="mt-2 text-sm text-text2">
        {{ loc.t('scaleConv.summary', { from: label(plan.from), to: label(plan.to), auto: plan.auto }) }}
        {{ loc.t('scaleConv.untouched', 'Посещаемость и экзамены не меняются.') }}
      </p>
      <template v-if="plan.disputed?.length">
        <p class="mt-2 rounded-md border border-yellow-500/40 bg-yellow-500/10 px-3 py-2 text-sm text-text">
          {{ loc.t('scaleConv.disputedIntro', { n: plan.disputed.length }) }}
        </p>
        <div class="mt-3 flex flex-wrap gap-2">
          <AppButton size="sm" variant="ghost" @click="setAll('nearest')">{{ loc.t('scaleConv.allNearest', 'Всем — ближайшая') }}</AppButton>
          <AppButton size="sm" variant="ghost" @click="setAll('lower')">{{ loc.t('scaleConv.allLower', 'Всем — в меньшую сторону') }}</AppButton>
          <AppButton size="sm" variant="ghost" @click="setAll('higher')">{{ loc.t('scaleConv.allHigher', 'Всем — в большую сторону') }}</AppButton>
        </div>
        <div class="mt-3 min-h-0 flex-1 overflow-y-auto rounded-md border border-border">
          <StickyXScroll>
          <table class="w-full text-sm">
            <thead class="sticky top-0 bg-bg2 text-left text-text2">
              <tr>
                <th class="px-2 py-2">{{ loc.t('scaleConv.colStudent', 'Студент') }}</th>
                <th class="px-2 py-2">{{ loc.t('scaleConv.colWhere', 'Группа · предмет · занятие') }}</th>
                <th class="px-2 py-2 text-center">{{ loc.t('scaleConv.colWas', 'Было') }}</th>
                <th class="px-2 py-2 text-center">{{ loc.t('scaleConv.colBecomes', 'Станет') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="d in shown" :key="d.id" class="border-t border-border bg-yellow-500/5">
                <td class="px-2 py-1.5 text-text">{{ d.student }}</td>
                <td class="px-2 py-1.5 text-text2">{{ d.group }} · {{ d.subject }} · {{ d.lesson }} <span v-if="d.date">({{ d.date }})</span></td>
                <td class="px-2 py-1.5 text-center font-semibold text-text">{{ d.old }}</td>
                <td class="px-2 py-1.5 text-center">
                  <select v-model="choices[d.id]" :aria-label="`${d.student}: ${d.old}`"
                          class="rounded-sm border border-yellow-500/60 bg-card px-2 py-1 text-text">
                    <option v-for="o in d.options" :key="o" :value="o">{{ o }}</option>
                  </select>
                </td>
              </tr>
            </tbody>
          </table>
          </StickyXScroll>
        </div>
        <div v-if="pages > 1" class="mt-2 flex items-center justify-center gap-3 text-sm text-text2">
          <AppButton size="sm" variant="ghost" :disabled="page === 0" @click="page--">‹</AppButton>
          <span>{{ loc.t('scaleConv.page', { p: page + 1, n: pages }) }}</span>
          <AppButton size="sm" variant="ghost" :disabled="page >= pages - 1" @click="page++">›</AppButton>
        </div>
      </template>
      <p v-else class="mt-2 text-sm text-text2">{{ loc.t('scaleConv.noDisputed', 'Спорных оценок нет — все переведутся однозначно.') }}</p>
      <p v-if="error" class="mt-2 text-sm text-red-500" role="alert">{{ error }}</p>
      <div class="mt-4 flex justify-end gap-2">
        <AppButton variant="ghost" :disabled="saving" @click="emit('close')">{{ loc.t('scaleConv.cancel', 'Отмена') }}</AppButton>
        <AppButton :disabled="saving" @click="apply">{{ loc.t('scaleConv.apply', 'Перевести и сменить шкалу') }}</AppButton>
      </div>
    </div>
  </div>
</template>
