<script setup>
// CuratorReportDialog (§12) — «+ → Отчёт для родителей»: выбор ГРУППЫ из списка и
// адресатов. Отчёт уходит обычным сообщением-кнопкой, поэтому его можно переслать
// дальше (доступ к отчёту даёт участие в беседе, где лежит кнопка).
//
// Почему список, а не ввод руками: группу набирали с опечаткой («К75/1» ↔ «К75\1»,
// латинская «K»), сервер отвечал 403/404, клиент ошибку глотал — со стороны «отчёты не
// создаются». Теперь и группа, и адресаты выбираются из готовых списков, а ошибка сервера
// показывается прямо в окне.
//
// Адресатов можно не выбирать вовсе: тогда отчёт ляжет в «Избранное», откуда его
// пересылают кому угодно — это же самый быстрый способ отдать его одному родителю.
import { ref, computed, onMounted, watch } from 'vue'
import { X, Check, Users, Star } from '@lucide/vue'
import { messengerApi } from '@/api/endpoints'
import { useAuthStore } from '@/stores/auth'
import Avatar from '@/components/ui/Avatar.vue'

const emit = defineEmits(['create', 'close'])
const props = defineProps({
  error: { type: String, default: '' },
  busy: { type: Boolean, default: false },
})

const groups = ref([])
const loading = ref(true)
const loadError = ref('')
const group = ref('')

const parents = ref([])
const convs = ref([])
const pickedUsers = ref([])
const pickedConvs = ref([])
const loadingTargets = ref(false)

const auth = useAuthStore()

onMounted(async () => {
  try {
    const all = (await messengerApi.myGroups()).data.groups || []
    //Отчёт по группе выпускает её КУРАТОР; администрации доступны любые группы (те же
    //границы проверяет сервер — _report_groups_for в routers/messenger.py).
    groups.value = auth.role === 'admin' ? all : all.filter(g => g.curated)
    group.value = groups.value[0]?.name || ''
  } catch (e) {
    loadError.value = e?.response?.data?.detail || 'Не удалось получить список групп'
  } finally { loading.value = false }
})

//Смена группы меняет и адресатов (родители — свои у каждой группы), поэтому выбор сбрасываем.
watch(group, async (g) => {
  pickedUsers.value = []
  pickedConvs.value = []
  parents.value = []
  convs.value = []
  if (!g) return
  loadingTargets.value = true
  try {
    const { data } = await messengerApi.reportRecipients(g)
    parents.value = data.parents || []
    convs.value = data.conversations || []
  } catch { /* адресатов может не быть — отчёт уйдёт в «Избранное» */ }
  finally { loadingTargets.value = false }
}, { immediate: true })

function toggleUser(id) {
  const i = pickedUsers.value.indexOf(id)
  if (i >= 0) pickedUsers.value.splice(i, 1); else pickedUsers.value.push(id)
}
function toggleConv(id) {
  const i = pickedConvs.value.indexOf(id)
  if (i >= 0) pickedConvs.value.splice(i, 1); else pickedConvs.value.push(id)
}
//Канал «Отчёты · Группа» — общий адресат сразу для всех родителей группы. Предлагаем его
//отдельной галочкой: если канала ещё нет, его создаст сервер (нужен активный родитель).
const useChannel = ref(false)
const hasReportsChannel = computed(() =>
  convs.value.some(c => c.conversation_id === `sys:curator_reports:${group.value}`))
const nothingPicked = computed(() =>
  !pickedUsers.value.length && !pickedConvs.value.length && !useChannel.value)
</script>

<template>
  <div class="fixed inset-0 z-50 grid place-items-center p-4" style="background: var(--gb-overlay)"
       @click.self="emit('close')">
    <div class="flex max-h-[85vh] w-full max-w-md flex-col rounded-xl border border-border2 bg-card shadow-card">
      <div class="flex items-center justify-between border-b border-border p-4">
        <h3 class="font-title text-lg font-bold text-text">Отчёт для родителей</h3>
        <button type="button" @click="emit('close')" class="grid size-8 place-items-center rounded-md text-text3 hover:bg-bg2 hover:text-text"><X class="size-5" /></button>
      </div>

      <div class="min-h-0 flex-1 overflow-y-auto p-4">
        <p v-if="loading" class="text-sm text-text3">Загружаем группы…</p>
        <p v-else-if="!groups.length" class="text-sm text-text3">
          Вы не курируете ни одной группы — отчёт по группе выпускает её куратор.
        </p>
        <template v-else>
          <label class="mb-1 block text-xs font-semibold text-text3">Группа</label>
          <select v-model="group"
                  class="mb-4 w-full rounded-lg border border-border2 bg-card2 px-3 py-2 text-sm text-text outline-none focus:border-accent">
            <option v-for="g in groups" :key="g.name" :value="g.name">{{ g.name }}</option>
          </select>

          <p class="mb-1 text-xs font-semibold text-text3">Кому отправить</p>
          <p class="mb-2 text-xs text-text3">
            Никого не выбрали — отчёт ляжет в «Избранное», оттуда его можно переслать.
          </p>
          <p v-if="loadingTargets" class="text-sm text-text3">Загружаем адресатов…</p>
          <template v-else>
            <div v-if="parents.length" class="mb-2 overflow-hidden rounded-lg border border-border">
              <button v-for="p in parents" :key="p.id" type="button" @click="toggleUser(p.id)"
                      class="flex w-full items-center gap-2 border-b border-border/50 px-3 py-2 text-left text-sm hover:bg-bg2">
                <Avatar :src="p.avatar" :name="p.full_name" :size="28" />
                <span class="min-w-0 flex-1 truncate text-text">{{ p.full_name }}<span class="text-text3"> · родитель</span></span>
                <span class="grid size-5 shrink-0 place-items-center rounded-full border"
                      :class="pickedUsers.includes(p.id) ? 'border-accent bg-accent text-white' : 'border-border2'">
                  <Check v-if="pickedUsers.includes(p.id)" class="size-3.5" />
                </span>
              </button>
            </div>
            <p v-else class="mb-2 text-xs text-text3">
              У группы нет родителей с подтверждённым доступом — отчёт можно отправить в беседу
              или оставить себе.
            </p>

            <label v-if="parents.length && !hasReportsChannel"
                   class="mb-2 flex items-center gap-2 text-sm text-text2">
              <input type="checkbox" v-model="useChannel" class="accent-[var(--gb-accent)]" />
              Опубликовать в канал «Отчёты · {{ group }}» (видят все родители группы)
            </label>

            <div v-if="convs.length" class="overflow-hidden rounded-lg border border-border">
              <button v-for="c in convs" :key="c.conversation_id" type="button" @click="toggleConv(c.conversation_id)"
                      class="flex w-full items-center gap-2 border-b border-border/50 px-3 py-2 text-left text-sm hover:bg-bg2">
                <Users class="size-4 shrink-0 text-text3" />
                <span class="min-w-0 flex-1 truncate text-text">{{ c.title || 'Беседа' }}</span>
                <span class="grid size-5 shrink-0 place-items-center rounded-full border"
                      :class="pickedConvs.includes(c.conversation_id) ? 'border-accent bg-accent text-white' : 'border-border2'">
                  <Check v-if="pickedConvs.includes(c.conversation_id)" class="size-3.5" />
                </span>
              </button>
            </div>
          </template>
        </template>
        <p v-if="loadError || error"
           class="mt-3 rounded-lg border border-red/40 bg-red/10 p-2 text-xs text-red">{{ loadError || error }}</p>
      </div>

      <div class="flex items-center justify-between gap-2 border-t border-border p-3">
        <span class="inline-flex items-center gap-1 text-xs text-text3">
          <Star v-if="nothingPicked" class="size-3.5" />
          {{ nothingPicked ? 'В «Избранное»' : `Адресатов: ${pickedUsers.length + pickedConvs.length}` }}
        </span>
        <span class="flex gap-2">
          <button type="button" @click="emit('close')" class="rounded-lg border border-border2 px-4 py-2 text-sm text-text2 hover:bg-bg2">Отмена</button>
          <button type="button" :disabled="!group || busy"
                  @click="emit('create', { group, userIds: [...pickedUsers], convIds: [...pickedConvs], channel: useChannel })"
                  class="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white hover:bg-accent2 disabled:opacity-50">
            {{ busy ? 'Создаём…' : 'Создать отчёт' }}
          </button>
        </span>
      </div>
    </div>
  </div>
</template>
