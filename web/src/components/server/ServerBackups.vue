<script setup>
// ServerBackups — резервные копии БОЕВОЙ машины: создать, посмотреть, увезти к себе.
//
// ⚠️ НЕ ПУТАТЬ с «Данные и копии» (AdminData.vue). Там выгрузка справочников в архив —
// её можно спокойно переслать почтой, хешей паролей в ней нет. Здесь снимок БАЗЫ ЦЕЛИКОМ
// вместе с `.env`, то есть с ключом шифрования: без ключа зашифрованная база бесполезна,
// а вместе с ним архив равен самой базе. Отсюда и предупреждение в интерфейсе.
//
// Кнопка «скачать» существует ради простой мысли: копия, лежащая только на сервере,
// спасает от испорченных данных, но не от потери самого сервера.
import { ref, onMounted } from 'vue'
import { Archive, Download, Plus, TriangleAlert, Check } from '@lucide/vue'
import { deskServerApi } from '@/api/endpoints'
import AppButton from '@/components/ui/AppButton.vue'

const props = defineProps({
  serverId: { type: String, required: true },
})

const data = ref(null)
const busy = ref('')          // '' | 'create' | имя файла (скачивание)
const message = ref('')
const failed = ref(false)

async function reload() {
  try {
    data.value = (await deskServerApi.backups(props.serverId)).data
  } catch (e) {
    data.value = { items: [], error: e?.response?.data?.detail || 'Не удалось получить список' }
  }
}
onMounted(reload)

async function create() {
  busy.value = 'create'
  message.value = ''
  failed.value = false
  try {
    const { data: r } = await deskServerApi.makeBackup(props.serverId)
    failed.value = !r.ok
    message.value = r.ok ? `Копия создана: ${r.name}. ${r.hint}` : (r.hint || 'Не удалось создать копию')
    await reload()
  } catch (e) {
    failed.value = true
    message.value = e?.response?.data?.detail || 'Не удалось создать копию'
  } finally {
    busy.value = ''
  }
}

async function download(name) {
  busy.value = name
  message.value = ''
  failed.value = false
  try {
    const { data: r } = await deskServerApi.downloadBackup(props.serverId, name)
    failed.value = !r.ok
    message.value = r.ok
      ? `Скачано на этот компьютер: ${r.path}`
      : (r.log || 'Не удалось скачать')
  } catch (e) {
    failed.value = true
    message.value = e?.response?.data?.detail || 'Не удалось скачать'
  } finally {
    busy.value = ''
  }
}

function human(n) {
  if (n === null || n === undefined) return '—'
  const units = ['Б', 'КБ', 'МБ', 'ГБ', 'ТБ']
  let v = n, i = 0
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i += 1 }
  return `${v >= 10 || i === 0 ? Math.round(v) : v.toFixed(1)} ${units[i]}`
}
</script>

<template>
  <div class="flex flex-col gap-3">
    <div class="flex flex-wrap items-center gap-3">
      <AppButton :disabled="busy === 'create'" @click="create">
        <Plus class="mr-1.5 inline size-4" />{{ busy === 'create' ? 'Создаём…' : 'Создать копию' }}
      </AppButton>
      <p v-if="data?.latest" class="text-sm text-text3">
        Самая свежая: <span class="font-medium text-text2">{{ data.latest }}</span>
      </p>
      <p v-if="data?.free" class="text-sm text-text3">
        Свободно на сервере: {{ human(data.free) }}
      </p>
    </div>

    <p v-if="message" class="flex items-start gap-2 text-sm"
       :class="failed ? 'text-red' : 'text-text2'">
      <TriangleAlert v-if="failed" class="mt-0.5 size-4 shrink-0" />
      <Check v-else class="mt-0.5 size-4 shrink-0 text-accent" />
      <span class="break-all">{{ message }}</span>
    </p>

    <div class="flex items-start gap-2.5 rounded-lg border border-yellow/50 bg-card2 p-3 text-xs text-text2">
      <TriangleAlert class="mt-0.5 size-4 shrink-0 text-yellow" />
      <p>В архиве лежит база вместе с ключом её шифрования. Он равносилен самой базе —
         не выкладывайте его в облако и не пересылайте почтой.</p>
    </div>

    <p v-if="data?.error" class="text-sm text-red">{{ data.error }}</p>
    <p v-else-if="!data?.items?.length" class="text-sm text-text3">
      Копий пока нет. Нажмите «Создать копию».
    </p>
    <ul v-else class="max-h-64 overflow-y-auto text-sm">
      <li v-for="b in data.items" :key="b.name"
          class="flex items-center justify-between gap-3 border-b border-border py-1.5 last:border-0">
        <span class="flex min-w-0 items-center gap-1.5">
          <Archive class="size-3.5 shrink-0 text-text3" />
          <span class="truncate text-text2">{{ b.name }}</span>
        </span>
        <span class="flex shrink-0 items-center gap-3">
          <span class="text-xs text-text3">{{ b.mtime }} · {{ human(b.size) }}</span>
          <button type="button" :disabled="busy === b.name"
                  class="text-accent transition-colors hover:underline disabled:opacity-50"
                  :aria-label="`Скачать ${b.name}`" @click="download(b.name)">
            <Download class="size-4" />
          </button>
        </span>
      </li>
    </ul>
  </div>
</template>
