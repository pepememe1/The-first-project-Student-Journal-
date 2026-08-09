<script setup>
// AdminData — «Данные и резервные копии»: выгрузка всех справочников и журнала в ZIP
// (она же резервная копия) и ВЫБОРОЧНАЯ загрузка обратно.
//
// Почему выгрузка и бэкап — одна кнопка, а не две разные. Это одно и то же действие:
// полный слепок данных. Отдельный «бэкап» означал бы второй формат, который надо отдельно
// проверять на восстановимость; здесь то, что скачано «на всякий случай», гарантированно
// принимается обратно этой же страницей.
//
// ⚠️ Пароли в архив НЕ попадают (сервер их вырезает) и при загрузке НЕ обнуляются —
// существующие хеши сохраняются. Это не деталь реализации, а причина, по которой
// восстановление справочника не выбивает вход всему колледжу.
import { ref, computed, onMounted } from 'vue'
import { Download, Upload, Database, ShieldAlert, Check } from '@lucide/vue'
import { adminApi } from '@/api/endpoints'
import Card from '@/components/ui/Card.vue'
import AppButton from '@/components/ui/AppButton.vue'
import { useToast } from '@/composables/useToast'
import { useConfirm } from '@/composables/useConfirm'
import { useLocaleStore } from '@/stores/locale'

const locale = useLocaleStore()
const toast = useToast()
const { confirm } = useConfirm()

// ── Выгрузка ────────────────────────────────────────────────────────────────────────
const datasets = ref([])          // [{name, label, count}]
const pickedExport = ref([])
const exporting = ref(false)

onMounted(async () => {
  try {
    datasets.value = (await adminApi.dataDatasets()).data.datasets || []
    // По умолчанию отмечаем ВСЁ: типичный сценарий — полная резервная копия.
    pickedExport.value = datasets.value.map((d) => d.name)
  } catch { toast.error(locale.t('adminData.datasetsLoadFailed', 'Не удалось получить список наборов данных')) }
})

const totalRows = computed(() =>
  datasets.value.filter((d) => pickedExport.value.includes(d.name))
    .reduce((a, d) => a + d.count, 0))

function toggleAllExport(on) {
  pickedExport.value = on ? datasets.value.map((d) => d.name) : []
}

async function doExport() {
  if (!pickedExport.value.length) return
  exporting.value = true
  try {
    const all = pickedExport.value.length === datasets.value.length
    const { data: blob } = await adminApi.dataExport(all ? '' : pickedExport.value.join(','))
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `gradebook-data-${new Date().toISOString().slice(0, 10)}.zip`
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    toast.error(e?.response?.data?.detail || locale.t('adminData.exportFailed', 'Не удалось выгрузить данные'))
  } finally { exporting.value = false }
}

// ── Загрузка ────────────────────────────────────────────────────────────────────────
// Два шага намеренно: сначала показываем, ЧТО в файле, и только потом пишем — и только
// отмеченное. Импорт «сразу при выборе файла» перезаписал бы боевые данные одним кликом.
const fileInput = ref(null)
const chosen = ref(null)          // File
const preview = ref(null)         // ответ /data/inspect
const pickedImport = ref([])
const inspecting = ref(false)
const importing = ref(false)

async function onFile(e) {
  const f = e.target.files?.[0]
  if (!f) return
  chosen.value = f
  preview.value = null
  pickedImport.value = []
  inspecting.value = true
  try {
    const { data } = await adminApi.dataInspect(f)
    preview.value = data
    // Отмечаем только непустые и неповреждённые наборы — вливать пустой набор нечем.
    pickedImport.value = (data.datasets || [])
      .filter((d) => d.count > 0 && !d.error).map((d) => d.name)
  } catch (err) {
    toast.error(err?.response?.data?.detail || locale.t('adminData.inspectFailed', 'Не удалось прочитать архив'))
    chosen.value = null
  } finally { inspecting.value = false }
}

function toggleImport(name) {
  const at = pickedImport.value.indexOf(name)
  if (at >= 0) pickedImport.value.splice(at, 1)
  else pickedImport.value.push(name)
}

function resetImport() {
  chosen.value = null
  preview.value = null
  pickedImport.value = []
  if (fileInput.value) fileInput.value.value = ''
}

async function doImport() {
  if (!chosen.value || !pickedImport.value.length) return
  const labels = (preview.value.datasets || [])
    .filter((d) => pickedImport.value.includes(d.name)).map((d) => d.label)
  // Подтверждение с ПЕРЕЧИСЛЕНИЕМ наборов: операция меняет боевые данные, и человек
  // должен увидеть словами, во что именно он сейчас вливает файл.
  const ok = await confirm({
    title: locale.t('adminData.importConfirmTitle', 'Загрузить данные в журнал?'),
    message: locale.t('adminData.importConfirmMessage', { labels: labels.join(', ') }),
    okText: locale.t('adminData.importConfirmOk', 'Загрузить'),
  })
  if (!ok) return
  importing.value = true
  try {
    const { data } = await adminApi.dataImport(chosen.value, pickedImport.value.join(','))
    const total = Object.values(data.written || {}).reduce((a, b) => a + b, 0)
    toast.success(locale.t('adminData.importedCount', { total }))
    ;(data.notes || []).forEach((n) => toast.error(n))
    resetImport()
  } catch (e) {
    toast.error(e?.response?.data?.detail || locale.t('adminData.importFailed', 'Не удалось загрузить данные'))
  } finally { importing.value = false }
}
</script>

<template>
  <div class="flex flex-col gap-6">
    <!-- Выгрузка = резервная копия -->
    <Card :title="locale.t('adminData.backupCardTitle', 'Резервная копия и выгрузка')"
          :subtitle="locale.t('adminData.backupCardSubtitle', 'Архив ZIP: каждый набор данных отдельным файлом. Он же годится для восстановления.')">
      <div class="mb-2 flex items-center justify-between">
        <span class="text-sm font-medium text-text2">{{ locale.t('adminData.whatToExport', 'Что выгрузить') }}</span>
        <div class="flex gap-3 text-xs">
          <button class="text-accent hover:underline" @click="toggleAllExport(true)">{{ locale.t('adminData.selectAll', 'выбрать все') }}</button>
          <button class="text-text3 hover:underline" @click="toggleAllExport(false)">{{ locale.t('adminData.selectNone', 'снять') }}</button>
        </div>
      </div>

      <div class="grid gap-1 sm:grid-cols-2">
        <label v-for="d in datasets" :key="d.name"
               class="flex cursor-pointer items-center gap-2.5 rounded-sm px-2 py-1.5 text-sm hover:bg-bg2">
          <input type="checkbox" :value="d.name" v-model="pickedExport" class="accent-accent" />
          <span class="min-w-0 flex-1 truncate text-text">{{ d.label }}</span>
          <span class="shrink-0 text-xs text-text3">{{ d.count }}</span>
        </label>
      </div>

      <div class="mt-3 flex flex-wrap items-center gap-3">
        <AppButton :disabled="exporting || !pickedExport.length" @click="doExport">
          <Download class="mr-2 inline size-4" />
          {{ exporting ? locale.t('adminData.preparingArchive', 'Готовим архив…') : locale.t('adminData.downloadArchive', 'Скачать архив') }}
        </AppButton>
        <span class="text-xs text-text3">{{ locale.t('adminData.rowsInExport', { total: totalRows }) }}</span>
      </div>

      <div class="mt-3 flex items-start gap-2.5 rounded-md border border-border bg-card2 px-3 py-2.5 text-xs text-text2">
        <ShieldAlert class="mt-0.5 size-4 shrink-0 text-orange" />
        <p>{{ locale.t('adminData.exportWarning', 'Пароли в архив не входят — после восстановления их нужно задать заново. Личная переписка мессенджера не выгружается. Архив содержит персональные данные студентов: храните его так же, как саму базу.') }}</p>
      </div>
    </Card>

    <!-- Загрузка -->
    <Card :title="locale.t('adminData.importCardTitle', 'Загрузка данных из архива')"
          :subtitle="locale.t('adminData.importCardSubtitle', 'Выберите файл — покажем, что внутри, и вы отметите, что именно загрузить.')">
      <input ref="fileInput" type="file" accept=".zip,application/zip" class="hidden"
             @change="onFile" />

      <div v-if="!preview" class="flex flex-wrap items-center gap-3">
        <AppButton variant="ghost" :disabled="inspecting" @click="fileInput?.click()">
          <Upload class="mr-2 inline size-4" />
          {{ inspecting ? locale.t('adminData.readingArchive', 'Читаем архив…') : locale.t('adminData.chooseArchive', 'Выбрать архив') }}
        </AppButton>
        <span class="text-xs text-text3">{{ locale.t('adminData.acceptedFileHint', 'Принимается ZIP, полученный этой же страницей.') }}</span>
      </div>

      <template v-else>
        <div class="mb-3 flex items-center gap-2 text-sm text-text2">
          <Database class="size-4 text-accent" />
          <span class="min-w-0 truncate">{{ chosen?.name }}</span>
          <span v-if="preview.created_at" class="shrink-0 text-xs text-text3">
            {{ locale.t('adminData.snapshotDate', { date: preview.created_at.slice(0, 10) }) }}
          </span>
        </div>

        <div class="grid gap-1 sm:grid-cols-2">
          <label v-for="d in preview.datasets" :key="d.name"
                 class="flex items-center gap-2.5 rounded-sm px-2 py-1.5 text-sm"
                 :class="d.error || !d.count ? 'opacity-50' : 'cursor-pointer hover:bg-bg2'">
            <input type="checkbox" :checked="pickedImport.includes(d.name)"
                   :disabled="!!d.error || !d.count" @change="toggleImport(d.name)"
                   class="accent-accent" />
            <span class="min-w-0 flex-1 truncate text-text">{{ d.label }}</span>
            <span class="shrink-0 text-xs" :class="d.error ? 'text-red' : 'text-text3'">
              {{ d.error || d.count }}
            </span>
          </label>
        </div>

        <p v-if="preview.note" class="mt-3 text-xs text-text3">{{ preview.note }}</p>

        <div class="mt-4 flex flex-wrap gap-2">
          <AppButton :disabled="importing || !pickedImport.length" @click="doImport">
            <Check class="mr-2 inline size-4" />
            {{ importing ? locale.t('adminData.importing', 'Загружаем…') : locale.t('adminData.importPicked', { n: pickedImport.length }) }}
          </AppButton>
          <AppButton variant="ghost" @click="resetImport">{{ locale.t('common.cancel') }}</AppButton>
        </div>
      </template>
    </Card>
  </div>
</template>
