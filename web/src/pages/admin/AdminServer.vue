<script setup>
// AdminServer — вкладка «Сервер и сайт» (read-only). Порт идей десктопного
// server_control: адрес сайта, версия, тип БД и ШИФРОВАНИЕ ПДн (152-ФЗ), ГОСТ-бэкенд,
// кто онлайн, учебный период, аптайм. Управление хостингом — на ХОСТЕ (десктоп), из
// браузера мы только показываем состояние.
import { ref, computed, onMounted } from 'vue'
import { adminApi } from '@/api/endpoints'
import Card from '@/components/ui/Card.vue'
import Badge from '@/components/ui/Badge.vue'

const info = ref(null)
const loading = ref(true)
const error = ref('')

async function reload() {
  loading.value = true; error.value = ''
  try { info.value = (await adminApi.serverInfo()).data }
  catch (e) { error.value = e?.response?.data?.detail || 'Не удалось загрузить' }
  finally { loading.value = false }
}
onMounted(reload)

const uptime = computed(() => {
  let s = info.value?.uptime_sec || 0
  const d = Math.floor(s / 86400); s -= d * 86400
  const h = Math.floor(s / 3600); s -= h * 3600
  const m = Math.floor(s / 60)
  return [d && `${d} д`, h && `${h} ч`, `${m} мин`].filter(Boolean).join(' ')
})
function termLabel(t) { return t ? `${t.year} · ${t.semester === 1 ? 'осенний' : 'весенний'} семестр` : '—' }
</script>

<template>
  <div class="space-y-4">
    <p v-if="loading" class="text-sm text-text3">Загрузка…</p>
    <p v-else-if="error" class="text-sm text-red">{{ error }}</p>

    <template v-else-if="info">
      <!-- Адрес и статус -->
      <Card pad>
        <div class="flex flex-wrap items-center gap-x-6 gap-y-3">
          <div>
            <p class="text-tiny uppercase text-text3">Адрес сайта</p>
            <a :href="info.address" target="_blank" class="font-title text-lg font-bold text-accent hover:underline">{{ info.address || '—' }}</a>
          </div>
          <div>
            <p class="text-tiny uppercase text-text3">Статус</p>
            <Badge variant="green">● {{ info.status }}</Badge>
          </div>
          <div>
            <p class="text-tiny uppercase text-text3">Версия</p>
            <p class="font-medium text-text">{{ info.version }}</p>
          </div>
          <div>
            <p class="text-tiny uppercase text-text3">Аптайм</p>
            <p class="font-medium text-text">{{ uptime }}</p>
          </div>
          <div>
            <p class="text-tiny uppercase text-text3">Учебный период</p>
            <p class="font-medium text-text">{{ termLabel(info.term) }}</p>
          </div>
        </div>
      </Card>

      <div class="grid gap-4 md:grid-cols-2">
        <!-- База данных и шифрование ПДн (152-ФЗ) -->
        <Card title="База данных · защита ПДн (152-ФЗ)" pad>
          <dl class="space-y-2.5 text-sm">
            <div class="flex items-center justify-between gap-3">
              <dt class="text-text3">СУБД</dt><dd class="font-medium text-text">{{ info.db_kind }}</dd>
            </div>
            <div class="flex items-center justify-between gap-3">
              <dt class="text-text3">Шифрование файла БД (SQLCipher AES-256)</dt>
              <dd><Badge :variant="info.db_file_encrypted ? 'green' : 'red'">{{ info.db_file_encrypted ? 'включено' : 'выключено' }}</Badge></dd>
            </div>
            <div class="flex items-center justify-between gap-3">
              <dt class="text-text3">Шифрование полей ПДн («Кузнечик»)</dt>
              <dd><Badge :variant="info.pdn_field_encrypted ? 'green' : 'red'">{{ info.pdn_field_encrypted ? 'включено' : 'выключено' }}</Badge></dd>
            </div>
          </dl>
        </Card>

        <!-- Криптография ГОСТ -->
        <Card title="Криптография (ГОСТ)" pad>
          <dl class="space-y-2.5 text-sm">
            <div class="flex items-center justify-between gap-3">
              <dt class="text-text3">Алгоритм</dt><dd class="text-right font-medium text-text">{{ info.crypto_algorithm || '—' }}</dd>
            </div>
            <div class="flex items-center justify-between gap-3">
              <dt class="text-text3">Крипто-движок</dt><dd class="text-right font-medium text-text">{{ info.crypto_backend || '—' }}</dd>
            </div>
            <div class="flex items-center justify-between gap-3">
              <dt class="text-text3">Хеш пароля (ГОСТ-бэкенд)</dt><dd class="text-right font-medium text-text">{{ info.gost_hash_backend }}</dd>
            </div>
            <div class="flex items-center justify-between gap-3">
              <dt class="text-text3">Сертифицированное СКЗИ</dt>
              <dd><Badge :variant="info.crypto_certified ? 'green' : 'muted'">{{ info.crypto_certified ? 'да (ViPNet)' : 'нет (open-source ГОСТ)' }}</Badge></dd>
            </div>
          </dl>
        </Card>
      </div>

      <!-- Счётчики -->
      <div class="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Card pad><p class="text-tiny uppercase text-text3">Онлайн сейчас</p><p class="font-title text-2xl font-bold text-accent">{{ info.online_count }}</p></Card>
        <Card pad><p class="text-tiny uppercase text-text3">Студентов</p><p class="font-title text-2xl font-bold text-text">{{ info.counts?.students ?? '—' }}</p></Card>
        <Card pad><p class="text-tiny uppercase text-text3">Преподавателей</p><p class="font-title text-2xl font-bold text-text">{{ info.counts?.teachers ?? '—' }}</p></Card>
        <Card pad><p class="text-tiny uppercase text-text3">Групп</p><p class="font-title text-2xl font-bold text-text">{{ info.counts?.groups ?? '—' }}</p></Card>
      </div>

      <p class="px-1 text-xs text-text3">
        Хостингом (запуск, туннель, домен, тип БД) управляют на компьютере-сервере через
        десктоп-приложение. Здесь — только состояние.
      </p>
    </template>
  </div>
</template>
