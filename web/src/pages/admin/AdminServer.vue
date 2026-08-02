<script setup>
// AdminServer — раздел «Сервер». Речь ВСЕГДА про боевую машину, а не про этот компьютер.
//
// ━━ ПОЧЕМУ РАНЬШЕ ПОКАЗЫВАЛСЯ СВОЙ ПК ━━
// Внутри программы страница говорит с ЛОКАЛЬНЫМ сервером (127.0.0.1), поэтому
// `/web/admin/server/*` честно отвечали про компьютер администратора: диск, память,
// база — всё настоящее, но не про ту машину. Правдоподобная ложь хуже пустого экрана.
// Теперь эти пути пересылаются на БОЕВОЙ сервер (`_PROXY_PREFIXES` в ui/local_api.py) —
// и на сайте, и в программе карточки состояния описывают один и тот же VPS.
//
// ━━ ДВА РЕЖИМА ━━
// На САЙТЕ — только просмотр. В ПРОГРАММЕ добавляется управление по SSH: список
// серверов, службы, резервные копии, строка команд, перенос на другую машину.
// Разделяет их не роль и не флаг, а НАЛИЧИЕ КОДА: маршруты `/desk/*` подключает только
// локальный сервер программы, на боевом их нет вовсе. Роль можно обойти, отсутствующий
// код — нельзя. Доступность проверяется по ТИПУ ОТВЕТА: на сайте неизвестный путь
// перехватывает заглушка SPA и отдаёт index.html с кодом 200.
import { ref, computed, onMounted } from 'vue'
import {
  Server, HardDrive, Cpu, Database, Plus, Trash2, RefreshCw, KeyRound,
  Terminal, ArrowRightLeft, Folder, FileText, ChevronUp, Archive, TriangleAlert } from '@lucide/vue'
import { adminApi, deskServerApi } from '@/api/endpoints'
import Card from '@/components/ui/Card.vue'
import Badge from '@/components/ui/Badge.vue'
import AppButton from '@/components/ui/AppButton.vue'
import UsageBar from '@/components/server/UsageBar.vue'
import RemoteConsole from '@/components/server/RemoteConsole.vue'
import MigrationWizard from '@/components/server/MigrationWizard.vue'
import ServerBackups from '@/components/server/ServerBackups.vue'
import ServiceControls from '@/components/server/ServiceControls.vue'
import { useLocaleStore } from '@/stores/locale'

const locale = useLocaleStore()

// ── Просмотр (везде; в программе идёт на боевой сервер через пересылку) ──────────
const info = ref(null)
const metrics = ref(null)
const backups = ref(null)
const tree = ref(null)
const loading = ref(true)
const error = ref('')

async function reload() {
  loading.value = true; error.value = ''
  // Части независимы: падение одного запроса не должно оставлять страницу пустой.
  const [i, m, b, t] = await Promise.allSettled([
    adminApi.serverInfo(), adminApi.serverMetrics(),
    adminApi.serverBackups(), adminApi.serverTree(''),
  ])
  info.value = i.status === 'fulfilled' ? i.value.data : null
  metrics.value = m.status === 'fulfilled' ? m.value.data : null
  backups.value = b.status === 'fulfilled' ? b.value.data : null
  tree.value = t.status === 'fulfilled' ? t.value.data : null
  if (!info.value && !metrics.value) {
    error.value = m.reason?.response?.data?.detail
      || locale.t('adminServer.stateLoadFailed', 'Не удалось получить состояние сервера. Нет связи с ним?')
  }
  loading.value = false
}

async function openDir(path) {
  try { tree.value = (await adminApi.serverTree(path)).data } catch { /* остаёмся где были */ }
}

// ── Управление (только в программе) ──────────────────────────────────────────────
const desk = ref(false)
const servers = ref([])
const defaultKey = ref('')
const suggestedHost = ref('')
const picked = ref('')
const remote = ref(null)
const remoteBusy = ref(false)
const remoteTree = ref(null)
const tab = ref('state')        // state | backups | console | migrate
const form = ref(null)
const formMsg = ref('')

async function loadServers() {
  try {
    const { data } = await deskServerApi.list()
    servers.value = data.items || []
    defaultKey.value = data.default_key || ''
    suggestedHost.value = data.suggested_host || ''
    if (!picked.value && servers.value.length) picked.value = servers.value[0].id
    if (picked.value) await loadRemote()
  } catch { servers.value = [] }
}

async function loadRemote() {
  if (!picked.value) return
  remoteBusy.value = true
  remote.value = null
  remoteTree.value = null
  try {
    remote.value = (await deskServerApi.metrics(picked.value)).data
    if (remote.value?.ok) {
      remoteTree.value = (await deskServerApi.tree(picked.value, '/root/gb-deploy')).data
    }
  } catch (e) {
    remote.value = { ok: false, error: e?.response?.data?.detail || locale.t('adminServer.serverNoAnswer', 'Сервер не ответил') }
  } finally {
    remoteBusy.value = false
  }
}

function newServer() {
  formMsg.value = ''
  // Адрес подставляем тот, на который программа и так синхронизируется: это ровно та
  // машина, состояние которой человек и пришёл смотреть.
  form.value = { id: '', name: locale.t('adminServer.defaultServerName', 'Боевой сервер'), host: suggestedHost.value, user: 'root',
                 port: '22', key: defaultKey.value, password: '', has_password: false,
                 clear_password: false, role: 'prod' }
}

function editServer(s) {
  formMsg.value = ''
  // Пароль сюда не приезжает (сервер его не отдаёт) — поле пустое, и пустым оно значит
  // «не менять». Стереть можно только галочкой.
  form.value = { ...s, password: '', clear_password: false }
}

async function saveServer() {
  formMsg.value = ''
  try {
    const { data } = await deskServerApi.save(form.value)
    servers.value = data.items
    picked.value = data.item.id
    form.value = null
    await loadRemote()
  } catch (e) {
    formMsg.value = e?.response?.data?.detail || locale.t('adminServer.saveServerFailed', 'Не удалось сохранить сервер')
  }
}

async function removeServer(id) {
  const { data } = await deskServerApi.remove(id)
  servers.value = data.items
  form.value = null
  if (picked.value === id) { picked.value = servers.value[0]?.id || ''; await loadRemote() }
}

const keyBusy = ref(false)
const keyMsg = ref('')
async function installKey() {
  keyBusy.value = true; keyMsg.value = ''
  try {
    const { data } = await deskServerApi.installKey(picked.value)
    keyMsg.value = data.hint || (data.ok ? locale.t('adminServer.doneShort', 'Готово.') : locale.t('adminServer.failedShort', 'Не удалось.'))
  } catch (e) {
    keyMsg.value = e?.response?.data?.detail || locale.t('adminServer.installKeyFailed', 'Не удалось положить ключ')
  } finally { keyBusy.value = false }
}

onMounted(async () => {
  await reload()
  desk.value = await deskServerApi.available()
  if (desk.value) await loadServers()
})

// ── Форматирование ───────────────────────────────────────────────────────────────
function human(n) {
  if (n === null || n === undefined) return '—'
  const units = [
    locale.t('adminServer.unitB', 'Б'), locale.t('adminServer.unitKB', 'КБ'),
    locale.t('adminServer.unitMB', 'МБ'), locale.t('adminServer.unitGB', 'ГБ'),
    locale.t('adminServer.unitTB', 'ТБ'),
  ]
  let v = n, i = 0
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i += 1 }
  return `${v >= 10 || i === 0 ? Math.round(v) : v.toFixed(1)} ${units[i]}`
}
function humanUptime(sec) {
  let s = Math.floor(sec || 0)
  const d = Math.floor(s / 86400); s -= d * 86400
  const h = Math.floor(s / 3600); s -= h * 3600
  const m = Math.floor(s / 60)
  const parts = []
  if (d) parts.push(locale.t('adminServer.unitDays', { n: d }))
  if (h) parts.push(locale.t('adminServer.unitHours', { n: h }))
  parts.push(locale.t('adminServer.unitMinutes', { n: m }))
  return parts.filter(Boolean).join(' ') || '—'
}
function seasonLabel(semester) {
  return semester === 1 ? locale.t('adminServer.seasonFall', 'осенний') : locale.t('adminServer.seasonSpring', 'весенний')
}
function termLabel(t) {
  return t ? locale.t('adminServer.termLabel', { year: t.year, semester: seasonLabel(t.semester) }) : '—'
}
const localUptime = computed(() => humanUptime(metrics.value?.uptime || info.value?.uptime_sec))
const heaviest = computed(() => {
  const items = (tree.value?.items || []).filter((x) => x.size > 0)
  return [...items].sort((a, b) => b.size - a.size).slice(0, 8)
})
const heaviestTotal = computed(() => heaviest.value.reduce((s, x) => s + x.size, 0) || 1)
const pickedServer = computed(() => servers.value.find((s) => s.id === picked.value) || null)
</script>

<template>
  <div class="flex flex-col gap-4">
    <!-- ─────────── УПРАВЛЕНИЕ: ТОЛЬКО В ПРОГРАММЕ, И СРАЗУ ─────────── -->
    <!-- Стоит первым намеренно: в программе этот раздел открывают, чтобы ЧТО-ТО
         сделать с сервером, а не почитать про него. -->
    <Card v-if="desk" :title="locale.t('adminServer.manageTitle', 'Управление боевым сервером')"
          :subtitle="locale.t('adminServer.manageSubtitle', 'Подключение по SSH: службы, резервные копии, команды, перенос')" pad>
      <div class="mb-4 flex flex-wrap items-center gap-2">
        <button v-for="s in servers" :key="s.id" type="button"
                class="flex items-center gap-2 rounded-lg border px-3 py-2 text-left transition-colors"
                :class="picked === s.id ? 'border-accent bg-accent-glow' : 'border-border hover:border-accent'"
                @click="picked = s.id; loadRemote()">
          <Server class="size-4 shrink-0 text-accent" />
          <span>
            <span class="block text-sm font-semibold text-text">{{ s.name }}</span>
            <span class="block text-tiny text-text3">
              {{ s.user }}@{{ s.host }}<template v-if="s.has_password">{{ locale.t('adminServer.byPasswordSuffix', ' · по паролю') }}</template>
            </span>
          </span>
        </button>
        <AppButton variant="ghost" @click="newServer">
          <Plus class="mr-1 inline size-4" />{{ locale.t('adminServer.addServerBtn', 'Добавить сервер') }}
        </AppButton>
        <AppButton v-if="pickedServer" variant="ghost" @click="editServer(pickedServer)">
          {{ locale.t('adminServer.editBtn', 'Изменить') }}
        </AppButton>
      </div>

      <!-- Форма сервера -->
      <div v-if="form" class="mb-4 rounded-lg border border-border bg-card2 p-3">
        <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <label class="block">
            <span class="mb-1 block text-xs text-text3">{{ locale.t('adminServer.nameLabel', 'Название') }}</span>
            <input v-model="form.name" :placeholder="locale.t('adminServer.defaultServerName', 'Боевой сервер')"
                   class="h-9 w-full rounded-sm border border-border2 bg-card px-2.5 text-sm text-text outline-none focus:border-accent" />
          </label>
          <label class="block">
            <span class="mb-1 block text-xs text-text3">{{ locale.t('adminServer.hostLabel', 'Адрес или домен') }}</span>
            <input v-model="form.host" placeholder="194.226.120.74"
                   class="h-9 w-full rounded-sm border border-border2 bg-card px-2.5 text-sm text-text outline-none focus:border-accent" />
          </label>
          <label class="block">
            <span class="mb-1 block text-xs text-text3">{{ locale.t('adminServer.userLabel', 'Пользователь') }}</span>
            <input v-model="form.user"
                   class="h-9 w-full rounded-sm border border-border2 bg-card px-2.5 text-sm text-text outline-none focus:border-accent" />
          </label>
          <label class="block">
            <span class="mb-1 block text-xs text-text3">{{ locale.t('adminServer.portLabel', 'Порт') }}</span>
            <input v-model="form.port"
                   class="h-9 w-full rounded-sm border border-border2 bg-card px-2.5 text-sm text-text outline-none focus:border-accent" />
          </label>
          <label class="block sm:col-span-2">
            <span class="mb-1 block text-xs text-text3">{{ locale.t('adminServer.keyFileLabel', 'Файл ключа SSH (если вход по ключу)') }}</span>
            <input v-model="form.key"
                   class="h-9 w-full rounded-sm border border-border2 bg-card px-2.5 font-mono text-xs text-text outline-none focus:border-accent" />
          </label>
          <label class="block sm:col-span-2">
            <span class="mb-1 block text-xs text-text3">
              {{ locale.t('adminServer.passwordLabel', 'Пароль') }}{{ form.has_password ? locale.t('adminServer.passwordSavedSuffix', ' (сохранён — оставьте пустым, чтобы не менять)') : '' }}
            </span>
            <input v-model="form.password" type="password" autocomplete="new-password"
                   :placeholder="form.has_password ? '••••••••' : locale.t('adminServer.passwordPlaceholderNew', 'если вход по паролю')"
                   class="h-9 w-full rounded-sm border border-border2 bg-card px-2.5 text-sm text-text outline-none focus:border-accent" />
          </label>
        </div>

        <label v-if="form.has_password" class="mt-2 flex items-center gap-2 text-xs text-text2">
          <input v-model="form.clear_password" type="checkbox" class="accent-[var(--gb-accent)]" />
          {{ locale.t('adminServer.clearPasswordLabel', 'Убрать сохранённый пароль (вход пойдёт по ключу)') }}
        </label>

        <div class="mt-3 flex items-start gap-2.5 rounded-lg border border-border bg-card px-3 py-2.5 text-tiny text-text3">
          <TriangleAlert class="mt-0.5 size-4 shrink-0 text-yellow" />
          <p>{{ locale.t('adminServer.keyPasswordHint', 'Ключ надёжнее пароля. Пароль нужен, когда на новой машине ключа ещё нет: зайдите по паролю, нажмите «Положить ключ на сервер» — и пароль можно убрать. Сохранённый пароль шифруется средствами Windows и на другом компьютере бесполезен; страница его никогда не показывает.') }}</p>
        </div>

        <p v-if="formMsg" class="mt-2 text-sm text-red">{{ formMsg }}</p>
        <div class="mt-3 flex flex-wrap gap-2">
          <AppButton @click="saveServer">{{ locale.t('common.save') }}</AppButton>
          <AppButton variant="ghost" @click="form = null">{{ locale.t('common.cancel') }}</AppButton>
          <AppButton v-if="form.id" variant="red" @click="removeServer(form.id)">
            <Trash2 class="mr-1 inline size-4" />{{ locale.t('adminServer.removeFromListBtn', 'Убрать из списка') }}
          </AppButton>
        </div>
      </div>

      <template v-if="pickedServer">
        <div class="mb-4 flex gap-1 overflow-x-auto border-b border-border">
          <button v-for="t in [
                    { id: 'state', label: locale.t('adminServer.tabState', 'Состояние и службы'), icon: HardDrive },
                    { id: 'backups', label: locale.t('adminServer.tabBackups', 'Резервные копии'), icon: Archive },
                    { id: 'console', label: locale.t('adminServer.tabConsole', 'Команды'), icon: Terminal },
                    { id: 'migrate', label: locale.t('adminServer.tabMigrate', 'Перенос'), icon: ArrowRightLeft }]"
                  :key="t.id" type="button"
                  class="-mb-px shrink-0 border-b-2 px-3 py-2 text-sm font-medium transition-colors"
                  :class="tab === t.id ? 'border-accent text-accent' : 'border-transparent text-text3 hover:text-text2'"
                  @click="tab = t.id">
            <component :is="t.icon" class="mr-1.5 inline size-4" />{{ t.label }}
          </button>
        </div>

        <!-- Состояние удалённой машины + управление службами -->
        <div v-if="tab === 'state'" class="flex flex-col gap-5">
          <div class="flex flex-wrap items-center gap-3">
            <AppButton variant="ghost" :disabled="remoteBusy" @click="loadRemote">
              <RefreshCw class="mr-1.5 inline size-4" />{{ remoteBusy ? locale.t('adminServer.pollingBtn', 'Опрашиваем…') : locale.t('adminServer.pollBtn', 'Опросить сервер') }}
            </AppButton>
            <AppButton variant="ghost" :disabled="keyBusy" @click="installKey">
              <KeyRound class="mr-1.5 inline size-4" />{{ keyBusy ? locale.t('adminServer.installingKeyBtn', 'Ставим ключ…') : locale.t('adminServer.installKeyBtn', 'Положить ключ на сервер') }}
            </AppButton>
            <p v-if="keyMsg" class="text-sm text-text3">{{ keyMsg }}</p>
          </div>

          <p v-if="remoteBusy && !remote" class="text-sm text-text3">{{ locale.t('adminServer.connectingSsh', 'Подключаемся по SSH…') }}</p>
          <div v-else-if="remote && !remote.ok"
               class="rounded-lg border border-red/50 bg-card2 p-3 text-sm text-text2">
            <p class="font-semibold text-red">{{ locale.t('adminServer.connectFailed', 'Не удалось подключиться') }}</p>
            <pre class="mt-1 whitespace-pre-wrap break-all font-mono text-tiny text-text3">{{ remote.error }}</pre>
            <p class="mt-2 text-xs">
              {{ locale.t('adminServer.connectFailedHintPre', 'Проверьте адрес и пользователя. Если вход по ключу — ваш открытый ключ должен лежать в') }}
              <code>~/.ssh/authorized_keys</code>
              {{ locale.t('adminServer.connectFailedHintPost', 'на сервере; если по паролю — укажите его в настройках сервера выше.') }}
            </p>
          </div>

          <template v-else-if="remote">
            <div class="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
              <span class="font-medium text-text">{{ remote.host }}</span>
              <span class="text-text3">{{ remote.system }}</span>
              <span class="text-text3">{{ locale.t('adminServer.uptimeWorkingPrefix', 'работает') }} {{ humanUptime(remote.uptime) }}</span>
              <span class="text-text3">
                <Cpu class="mr-1 inline size-4" />{{ locale.t('adminServer.coresLabel', { n: remote.cpu_count }) }}
                <template v-if="remote.load?.length">{{ locale.t('adminServer.loadLabel', { load: remote.load.join(' / ') }) }}</template>
              </span>
            </div>

            <div class="grid gap-5 md:grid-cols-2">
              <UsageBar v-if="remote.disk?.total" :label="locale.t('adminServer.diskLabel', 'Диск')"
                        :used="remote.disk.used" :total="remote.disk.total" />
              <UsageBar v-if="remote.memory?.total" :label="locale.t('adminServer.ramLabel', 'Оперативная память')"
                        :used="remote.memory.used" :total="remote.memory.total" />
              <UsageBar v-if="remote.memory?.swap_total" :label="locale.t('adminServer.swapLabel', 'Подкачка (swap)')"
                        :used="remote.memory.swap_used" :total="remote.memory.swap_total" />
              <div v-if="remote.database?.size">
                <p class="mb-1.5 text-sm font-medium text-text2">{{ locale.t('adminServer.dbLabel', 'База данных') }}</p>
                <p class="text-sm text-text3">
                  <Database class="mr-1 inline size-4" />{{ human(remote.database.size) }}
                </p>
                <p class="mt-1 text-tiny text-text3">
                  {{ locale.t('adminServer.latestBackupLabel', { name: remote.latest_backup || locale.t('adminServer.notFound', 'не найдена') }) }}
                </p>
              </div>
            </div>

            <ServiceControls :server-id="picked" :services="remote.services || {}"
                             @changed="loadRemote" />

            <div v-if="remoteTree?.items?.length">
              <p class="mb-2 text-sm font-medium text-text2">{{ locale.t('adminServer.deployDirLabel', 'Каталог развёртывания') }}</p>
              <ul class="flex flex-col gap-1.5">
                <li v-for="it in remoteTree.items.slice(0, 10)" :key="it.name"
                    class="flex items-center justify-between gap-3 text-sm">
                  <span class="flex min-w-0 items-center gap-1.5 text-text2">
                    <Folder v-if="it.dir" class="size-3.5 shrink-0 text-text3" />
                    <FileText v-else class="size-3.5 shrink-0 text-text3" />
                    <span class="truncate">{{ it.name }}</span>
                  </span>
                  <span class="shrink-0 text-xs text-text3">{{ human(it.size) }}</span>
                </li>
              </ul>
            </div>
          </template>
        </div>

        <!-- Резервные копии боевой машины -->
        <ServerBackups v-else-if="tab === 'backups'" :key="picked + ':b'" :server-id="picked" />

        <!-- Команды. :key — чтобы при смене сервера журнал не смешивался. -->
        <RemoteConsole v-else-if="tab === 'console'" :key="picked" :server-id="picked" />

        <!-- Перенос -->
        <MigrationWizard v-else :servers="servers" />
      </template>

      <!-- Показывается редко: список заводится сам (ensure_seeded в ui/server_admin.py).
           Остаётся для случая, когда адрес сервера в программе не задан вовсе. -->
      <div v-else class="rounded-lg border border-border bg-card2 p-4 text-sm text-text2">
        <p class="font-semibold text-text">{{ locale.t('adminServer.sshNotConfigured', 'Доступ по SSH ещё не настроен.') }}</p>
        <p class="mt-1">
          {{ locale.t('adminServer.sshHintPre', 'Состояние сервера ниже видно и так — оно приходит по обычному защищённому каналу. А чтобы ещё и') }}
          <b>{{ locale.t('adminServer.sshHintManageWord', 'управлять') }}</b>
          {{ locale.t('adminServer.sshHintPost', 'машиной (резервные копии, перезапуск служб, команды), нужен доступ по SSH: нажмите «Добавить сервер»') }}
          <template v-if="suggestedHost">— {{ locale.t('adminServer.sshHintAddressPre', 'адрес') }} <code>{{ suggestedHost }}</code> {{ locale.t('adminServer.sshHintAddressPost', 'уже подставлен') }}</template>.
        </p>
      </div>
    </Card>

    <!-- ─────────── ПРОСМОТР (одинаково на сайте и в программе) ─────────── -->
    <p v-if="loading" class="text-sm text-text3">{{ locale.t('common.loading') }}</p>
    <p v-else-if="error" class="text-sm text-red">{{ error }}</p>

    <template v-else>
      <Card v-if="info" pad>
        <div class="flex flex-wrap items-center gap-x-6 gap-y-3">
          <div>
            <p class="text-tiny uppercase text-text3">{{ locale.t('adminServer.siteAddressLabel', 'Адрес сайта') }}</p>
            <a :href="info.address" target="_blank" rel="noopener"
               class="font-title text-lg font-bold text-accent hover:underline">{{ info.address || '—' }}</a>
          </div>
          <div>
            <p class="text-tiny uppercase text-text3">{{ locale.t('adminServer.statusLabel', 'Статус') }}</p>
            <Badge variant="green">● {{ info.status }}</Badge>
          </div>
          <div>
            <p class="text-tiny uppercase text-text3">{{ locale.t('adminServer.versionLabel', 'Версия') }}</p>
            <p class="font-medium text-text">{{ info.version }}</p>
          </div>
          <div>
            <p class="text-tiny uppercase text-text3">{{ locale.t('adminServer.uptimeLabel', 'Работает без перезапуска') }}</p>
            <p class="font-medium text-text">{{ localUptime }}</p>
          </div>
          <div>
            <p class="text-tiny uppercase text-text3">{{ locale.t('adminServer.termHeading', 'Учебный период') }}</p>
            <p class="font-medium text-text">{{ termLabel(info.term) }}</p>
          </div>
          <div class="ml-auto">
            <AppButton variant="ghost" @click="reload">
              <RefreshCw class="mr-1.5 inline size-4" />{{ locale.t('common.refresh') }}
            </AppButton>
          </div>
        </div>
      </Card>

      <Card v-if="metrics" :title="locale.t('adminServer.machineCardTitle', 'Машина, на которой работает сервер')"
            :subtitle="`${metrics.host} · ${metrics.system} · Python ${metrics.python}`" pad>
        <div class="grid gap-5 md:grid-cols-2">
          <UsageBar v-if="metrics.disk?.total" :label="locale.t('adminServer.diskLabel', 'Диск')"
                    :used="metrics.disk.used" :total="metrics.disk.total" />
          <UsageBar v-if="metrics.memory?.total" :label="locale.t('adminServer.ramLabel', 'Оперативная память')"
                    :used="metrics.memory.used" :total="metrics.memory.total" />
          <UsageBar v-if="metrics.memory?.swap_total" :label="locale.t('adminServer.swapLabel', 'Подкачка (swap)')"
                    :used="metrics.memory.swap_used" :total="metrics.memory.swap_total" />
          <div>
            <p class="mb-1.5 text-sm font-medium text-text2">{{ locale.t('adminServer.processorLabel', 'Процессор') }}</p>
            <p class="text-sm text-text3">
              <Cpu class="mr-1 inline size-4" />{{ locale.t('adminServer.coresLabel', { n: metrics.cpu_count }) }}
              <template v-if="metrics.load?.length">{{ locale.t('adminServer.loadLabel', { load: metrics.load.join(' / ') }) }}</template>
            </p>
            <p v-if="metrics.cpu_count === 1" class="mt-1 text-tiny text-text3">
              {{ locale.t('adminServer.singleCoreHint', 'Одно ядро: тяжёлые задачи (распознавание речи, фоновые планировщики) этой машине не по силам.') }}
            </p>
          </div>
        </div>
      </Card>

      <div class="grid gap-4 md:grid-cols-2">
        <Card :title="locale.t('adminServer.dbCardTitle', 'База данных · защита ПДн (152-ФЗ)')" pad>
          <dl class="flex flex-col gap-2.5 text-sm">
            <div class="flex items-center justify-between gap-3">
              <dt class="text-text3">{{ locale.t('adminServer.dbmsLabel', 'СУБД') }}</dt>
              <dd class="font-medium text-text">{{ info?.db_kind || metrics?.database?.engine || '—' }}</dd>
            </div>
            <div v-if="metrics?.database?.size" class="flex items-center justify-between gap-3">
              <dt class="text-text3">{{ locale.t('adminServer.dbSizeLabel', 'Размер файла базы') }}</dt>
              <dd class="font-medium text-text">{{ human(metrics.database.size) }}</dd>
            </div>
            <div class="flex items-center justify-between gap-3">
              <dt class="text-text3">{{ locale.t('adminServer.dbEncryptionLabel', 'Шифрование файла БД (SQLCipher AES-256)') }}</dt>
              <dd><Badge :variant="(info?.db_file_encrypted ?? metrics?.database?.encrypted) ? 'green' : 'red'">
                {{ (info?.db_file_encrypted ?? metrics?.database?.encrypted) ? locale.t('adminServer.enabledBadge', 'включено') : locale.t('adminServer.disabledBadge', 'выключено') }}
              </Badge></dd>
            </div>
            <div v-if="info" class="flex items-center justify-between gap-3">
              <dt class="text-text3">{{ locale.t('adminServer.pdnEncryptionLabel', 'Шифрование полей ПДн («Кузнечик»)') }}</dt>
              <dd><Badge :variant="info.pdn_field_encrypted ? 'green' : 'red'">
                {{ info.pdn_field_encrypted ? locale.t('adminServer.enabledBadge', 'включено') : locale.t('adminServer.disabledBadge', 'выключено') }}</Badge></dd>
            </div>
          </dl>
        </Card>

        <Card v-if="info" :title="locale.t('adminServer.cryptoCardTitle', 'Криптография (ГОСТ)')" pad>
          <dl class="flex flex-col gap-2.5 text-sm">
            <div class="flex items-center justify-between gap-3">
              <dt class="text-text3">{{ locale.t('adminServer.algorithmLabel', 'Алгоритм') }}</dt>
              <dd class="text-right font-medium text-text">{{ info.crypto_algorithm || '—' }}</dd>
            </div>
            <div class="flex items-center justify-between gap-3">
              <dt class="text-text3">{{ locale.t('adminServer.cryptoEngineLabel', 'Крипто-движок') }}</dt>
              <dd class="text-right font-medium text-text">{{ info.crypto_backend || '—' }}</dd>
            </div>
            <div class="flex items-center justify-between gap-3">
              <dt class="text-text3">{{ locale.t('adminServer.passwordHashLabel', 'Хеш пароля (ГОСТ-бэкенд)') }}</dt>
              <dd class="text-right font-medium text-text">{{ info.gost_hash_backend }}</dd>
            </div>
            <div class="flex items-center justify-between gap-3">
              <dt class="text-text3">{{ locale.t('adminServer.certifiedCryptoLabel', 'Сертифицированное СКЗИ') }}</dt>
              <dd><Badge :variant="info.crypto_certified ? 'green' : 'muted'">
                {{ info.crypto_certified ? locale.t('adminServer.certifiedYes', 'да (ViPNet)') : locale.t('adminServer.certifiedNo', 'нет (open-source ГОСТ)') }}</Badge></dd>
            </div>
          </dl>
        </Card>
      </div>

      <Card v-if="tree" :title="locale.t('adminServer.spaceUsageCardTitle', 'Что занимает место')" :subtitle="tree.path" pad>
        <div v-if="tree.parent" class="mb-3">
          <AppButton variant="ghost" @click="openDir(tree.parent)">
            <ChevronUp class="mr-1 inline size-4" />{{ locale.t('adminServer.upBtn', 'Наверх') }}
          </AppButton>
        </div>
        <div v-if="!heaviest.length" class="text-sm text-text3">{{ locale.t('adminServer.emptyDirText', 'Каталог пуст.') }}</div>
        <ul v-else class="flex flex-col gap-2">
          <li v-for="it in heaviest" :key="it.name">
            <button type="button" class="w-full text-left" :disabled="!it.dir"
                    @click="it.dir && openDir(tree.path + '/' + it.name)">
              <div class="mb-1 flex items-baseline justify-between gap-3">
                <span class="flex min-w-0 items-center gap-1.5 text-sm"
                      :class="it.dir ? 'text-accent hover:underline' : 'text-text2'">
                  <Folder v-if="it.dir" class="size-3.5 shrink-0" />
                  <FileText v-else class="size-3.5 shrink-0" />
                  <span class="truncate">{{ it.name }}</span>
                </span>
                <span class="shrink-0 text-xs text-text3">{{ human(it.size) }}</span>
              </div>
              <div class="h-1.5 w-full overflow-hidden rounded-full bg-card2">
                <div class="h-full rounded-full bg-accent"
                     :style="{ width: Math.max(2, Math.round(it.size / heaviestTotal * 100)) + '%' }" />
              </div>
            </button>
          </li>
        </ul>
      </Card>

      <Card v-if="backups && !desk" :title="locale.t('adminServer.backupsCardTitle', 'Резервные копии')" :subtitle="backups.dir" pad>
        <p v-if="!backups.exists" class="text-sm text-red">
          {{ locale.t('adminServer.noBackupsDirWarning', 'Каталог резервных копий не найден. Это значит, что копий нет вовсе — восстановить данные при сбое будет нечем.') }}
        </p>
        <template v-else>
          <div class="mb-3 flex flex-wrap items-center gap-x-6 gap-y-2">
            <div>
              <p class="text-tiny uppercase text-text3">{{ locale.t('adminServer.latestLabel', 'Самая свежая') }}</p>
              <p class="font-medium text-text">{{ backups.latest || locale.t('adminServer.noBackupsYet', 'копий нет') }}</p>
            </div>
            <div>
              <p class="text-tiny uppercase text-text3">{{ locale.t('adminServer.totalSizeLabel', 'Всего занимают') }}</p>
              <p class="font-medium text-text">{{ human(backups.total_size) }}</p>
            </div>
          </div>
          <ul class="max-h-56 overflow-y-auto text-sm">
            <li v-for="b in backups.items" :key="b.name"
                class="flex items-center justify-between gap-3 border-b border-border py-1.5 last:border-0">
              <span class="flex min-w-0 items-center gap-1.5">
                <Archive class="size-3.5 shrink-0 text-text3" />
                <span class="truncate text-text2">{{ b.name }}</span>
              </span>
              <span class="shrink-0 text-xs text-text3">{{ b.mtime }} · {{ human(b.size) }}</span>
            </li>
          </ul>
        </template>
      </Card>

      <p v-if="!desk" class="px-1 text-xs text-text3">
        {{ locale.t('adminServer.desktopOnlyNotice', 'Создание копий, перезапуск служб и команды доступны только в программе на компьютере. В браузере этих возможностей нет намеренно: доступ к боевому серверу не должен зависеть от того, что кто-то забыл выйти из веб-админки.') }}
      </p>
    </template>
  </div>
</template>
