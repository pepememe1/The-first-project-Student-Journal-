<script setup>
// NotificationsInbox — вкладка «Уведомления»: список писем и чтение одного письма.
// Вид намеренно почтовый (как Gmail): непрочитанные выделены жирным и точкой, клик по
// строке открывает само письмо, есть «прочитать все».
//
// Тексты писем приходят ГОТОВЫМИ с сервера и здесь не собираются. Тон зависит от роли
// (студенту дружелюбно, преподавателю официально), и если бы каждая платформа лепила
// текст сама, веб, десктоп и телефон разъехались бы в формулировках. Клиент решает
// только КАК показать, но не ЧТО написано.
import { ref, computed, watch, onMounted } from 'vue'
import { Bell, ArrowLeft, CheckCheck, Megaphone, X, Send, BookOpen } from '@lucide/vue'
import { meApi, teacherApi, adminApi, eventsApi } from '@/api/endpoints'
import { useAuthStore } from '@/stores/auth'
import AppButton from '@/components/ui/AppButton.vue'

const auth = useAuthStore()

const items = ref([])
const opened = ref(null)      // открытое письмо (null → показываем список)
const loading = ref(true)
const failed = ref(false)

// Подпись типа события. Старые письма (созданные до появления текста) приходят с
// пустыми title/body — для них заголовок берём отсюда, чтобы строка не была пустой.
const KIND_LABEL = {
  grade: 'Новая оценка',
  grade_changed: 'Оценка изменена',
  schedule_changed: 'Расписание изменилось',
  homework: 'Домашнее задание',
  event: 'Мероприятие',
  reminder: 'Напоминание',
}

// Фильтр по видам. Оценки — отдельно от «Система» (по просьбе: оценки идут в свою
// вкладку, всё, что пишет админ вручную — в «Система»). Домашка — отдельно, иначе
// теряется среди оценок. Мероприятия (олимпиады/конкурсы, заводят препод/админ) — тоже
// отдельно, это не рутинная системная почта.
const KIND_TAB = { grade: 'grades', grade_changed: 'grades', homework: 'homework', event: 'events' }

//⚠️ «ДЗ» — вкладка ПОЛУЧАТЕЛЯ задания, то есть студента (и родителя, который смотрит
//глазами ребёнка). Преподаватель домашних заданий не получает — он их ЗАДАЁТ, и у него
//этот раздел всегда был пустым: вкладка со счётчиком «0» выглядела как поломка. То, что
//он задал, теперь видно в «Отправленных».
const ALL_TABS = [
  { key: 'all', label: 'Все' },
  { key: 'grades', label: 'Оценки' },
  { key: 'homework', label: 'ДЗ', roles: ['student', 'parent'] },
  { key: 'events', label: 'Мероприятия' },
  { key: 'system', label: 'Система' },
  //«Отправленные» — не почта, а журнал своих рассылок: список приходит отдельным
  //запросом и в общий `items` не попадает (у писем разная природа — у полученных есть
  //«прочитано», у отправленных «сколько прочитали»).
  { key: 'sent', label: 'Отправленные', roles: ['teacher', 'admin'] },
]
const TABS = computed(() =>
  ALL_TABS.filter((t) => !t.roles || t.roles.includes(auth.role)))
const EMPTY_LABEL = {
  grades: 'Оценок пока нет',
  homework: 'Домашних заданий пока нет',
  events: 'Мероприятий пока нет',
  system: 'Системных уведомлений пока нет',
}
const tab = ref('all')

// ── «Отправленные»: свои рассылки (одна строка на рассылку, а не на получателя) ──────
const sentItems = ref([])
const sentLoading = ref(false)
const sentFailed = ref(false)

async function loadSent() {
  sentLoading.value = true
  sentFailed.value = false
  try {
    sentItems.value = (await eventsApi.sent(50)).data.items || []
  } catch {
    sentFailed.value = true
    sentItems.value = []
  } finally { sentLoading.value = false }
}
// Грузим ЛЕНИВО, при первом заходе на вкладку: у преподавателя рассылок может не быть
// вовсе, и тянуть их при каждом открытии уведомлений — лишний запрос на пустоту.
watch(tab, (t) => { if (t === 'sent' && !sentItems.value.length) loadSent() })

function tabOf(item) { return KIND_TAB[item.kind] || 'system' }
function inTab(item, key) {
  if (key === 'all') return tabOf(item) !== 'sent'
  return tabOf(item) === key
}

const visible = computed(() => items.value.filter((i) => inTab(i, tab.value)))
// Счётчик у вкладки — только непрочитанные, иначе он теряет смысл уже на второй день.
// У «Отправленных» его нет по смыслу: свои письма человек не «читает».
function tabUnread(key) {
  if (key === 'sent') return 0
  return items.value.filter((i) => !i.read_at && inTab(i, key)).length
}

const unread = computed(() => items.value.filter((i) => !i.read_at).length)

function titleOf(item) {
  return item.title || KIND_LABEL[item.kind] || 'Уведомление'
}

function bodyOf(item) {
  return item.body || 'Откройте журнал, чтобы посмотреть подробности.'
}

// Как в почте: сегодняшнее письмо показывает время, остальные — дату.
function fmtWhen(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const today = new Date()
  const sameDay = d.toDateString() === today.toDateString()
  return sameDay
    ? d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
    : d.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: '2-digit' })
}

async function load() {
  loading.value = true
  failed.value = false
  try {
    items.value = (await meApi.events({ limit: 100 })).data.items || []
  } catch {
    // Офлайн или сервер недоступен: показываем это честно, а не пустым списком —
    // «уведомлений нет» и «не смогли их получить» для человека совсем не одно и то же.
    failed.value = true
    items.value = []
  } finally {
    loading.value = false
  }
}

async function open(item) {
  opened.value = item
  if (item.read_at) return
  // Помечаем прочитанным оптимистично: письмо человек уже открыл, и если запрос
  // не дойдёт, худшее последствие — значок не сойдётся до следующей загрузки.
  item.read_at = new Date().toISOString()
  try { await meApi.markEventRead(item.id) } catch { /* значок поправится при перезагрузке */ }
}

async function markAll() {
  const now = new Date().toISOString()
  items.value.forEach((i) => { if (!i.read_at) i.read_at = now })
  try { await meApi.markAllEventsRead() } catch { await load() }
}

onMounted(load)

// ── Создать мероприятие/событие (олимпиада, конкурс и т.п.) — препод/админ ──────────────
// Автор выбирает аудиторию сам: у преподавателя — только его группы (по предметам, тот
// же скоуп, что и в журнале); у админа — ещё и «все группы» (широковещательно).
const canCreateEvent = computed(() => ['teacher', 'admin'].includes(auth.role))
const showCreate = ref(false)
const evTitle = ref('')
const evBody = ref('')
const evAll = ref(false)          // «Все группы» — только у админа
const evGroups = ref([])          // выбранные группы
const availableGroups = ref([])
const evSending = ref(false)
const evDone = ref('')

async function openCreate() {
  showCreate.value = true
  evDone.value = ''
  try {
    if (auth.role === 'admin') {
      const { data } = await adminApi.groups()
      availableGroups.value = (data.groups || []).map((g) => g.name)
    } else {
      const { data } = await teacherApi.overview()
      availableGroups.value = data.groups || []
    }
  } catch { availableGroups.value = [] }
}
function toggleGroup(g) {
  const i = evGroups.value.indexOf(g)
  if (i >= 0) evGroups.value.splice(i, 1)
  else evGroups.value.push(g)
}
async function submitEvent() {
  const title = evTitle.value.trim()
  const body = evBody.value.trim()
  if (!title || !body) return
  if (!evAll.value && !evGroups.value.length) return
  evSending.value = true
  try {
    const { data } = await eventsApi.create(title, body, evAll.value ? [] : evGroups.value)
    evDone.value = `Отправлено: ${data.sent} из ${data.recipients}`
    evTitle.value = ''; evBody.value = ''; evGroups.value = []; evAll.value = false
    //Своя рассылка должна появиться в «Отправленных» сразу, а не после перезахода.
    await loadSent()
  } catch (e) {
    evDone.value = e?.response?.data?.detail || 'Не удалось отправить.'
  } finally {
    evSending.value = false
  }
}
</script>

<template>
  <div>
    <!-- ── Одно письмо ────────────────────────────────────────────────────────── -->
    <div v-if="opened">
      <button type="button"
              class="mb-4 inline-flex items-center gap-1.5 text-sm text-text3 transition-colors hover:text-accent"
              @click="opened = null">
        <ArrowLeft class="size-4" /> К списку
      </button>
      <h3 class="font-title text-lg font-extrabold text-text">{{ titleOf(opened) }}</h3>
      <p class="mt-1 text-tiny text-text3">
        {{ KIND_LABEL[opened.kind] || 'Уведомление' }}
        <span v-if="opened.subject"> · {{ opened.subject }}</span>
        <span v-if="opened.created_at"> · {{ fmtWhen(opened.created_at) }}</span>
      </p>
      <p class="mt-4 whitespace-pre-line leading-relaxed text-text">{{ bodyOf(opened) }}</p>
    </div>

    <!-- ── Список писем ──────────────────────────────────────────────────────── -->
    <div v-else>
      <div class="mb-3 flex flex-wrap items-center gap-1">
        <button v-for="t in TABS" :key="t.key" type="button"
                class="rounded-sm px-3 py-1.5 text-sm transition-colors"
                :class="tab === t.key ? 'bg-accent font-bold text-bg' : 'text-text3 hover:bg-card2 hover:text-text'"
                @click="tab = t.key">
          {{ t.label }}
          <span v-if="tabUnread(t.key)"
                class="ml-1 text-tiny"
                :class="tab === t.key ? 'text-bg opacity-80' : 'text-accent'">{{ tabUnread(t.key) }}</span>
        </button>
        <AppButton v-if="canCreateEvent" variant="ghost" class="ml-auto" @click="openCreate">
          <Megaphone class="mr-1.5 inline size-4" />Создать мероприятие
        </AppButton>
      </div>

      <!-- Форма создания мероприятия/события (препод/админ) -->
      <div v-if="showCreate" class="mb-4 rounded-lg border border-border2 bg-card2 p-3">
        <div class="mb-2 flex items-center justify-between">
          <p class="text-sm font-semibold text-text">Новое мероприятие</p>
          <button type="button" @click="showCreate = false" aria-label="Закрыть"
                  class="grid size-7 place-items-center rounded-md text-text3 hover:bg-bg2"><X class="size-4" /></button>
        </div>
        <input v-model="evTitle" placeholder="Заголовок (напр. «Олимпиада по математике»)" maxlength="150"
               class="mb-2 w-full rounded-md border border-border2 bg-card px-2.5 py-1.5 text-sm text-text outline-none focus:border-accent" />
        <textarea v-model="evBody" placeholder="Текст объявления" rows="3" maxlength="2000"
                  class="mb-2 w-full resize-none rounded-md border border-border2 bg-card px-2.5 py-1.5 text-sm text-text outline-none focus:border-accent" />
        <label v-if="auth.role === 'admin'" class="mb-2 flex items-center gap-2 text-sm text-text2">
          <input type="checkbox" v-model="evAll" class="accent-[var(--gb-accent)]" />Все группы
        </label>
        <div v-if="!evAll" class="mb-2 flex flex-wrap gap-1.5">
          <button v-for="g in availableGroups" :key="g" type="button" @click="toggleGroup(g)"
                  class="rounded-full border px-2.5 py-1 text-xs transition-colors"
                  :class="evGroups.includes(g) ? 'border-accent bg-accent-glow text-accent' : 'border-border2 text-text2 hover:bg-bg2'">
            {{ g }}
          </button>
          <p v-if="!availableGroups.length" class="text-xs text-text3">Нет доступных групп.</p>
        </div>
        <p v-if="evDone" class="mb-2 text-xs text-text3">{{ evDone }}</p>
        <AppButton :disabled="evSending || !evTitle.trim() || !evBody.trim() || (!evAll && !evGroups.length)"
                   @click="submitEvent">Отправить</AppButton>
      </div>

      <!-- ── «Отправленные»: свои рассылки ──────────────────────────────────────── -->
      <template v-if="tab === 'sent'">
        <p v-if="sentLoading" class="py-8 text-center text-sm text-text3">Загружаем…</p>
        <p v-else-if="sentFailed" class="py-8 text-center text-sm text-text3">
          Не удалось получить список отправленного. Проверьте связь.
        </p>
        <div v-else-if="!sentItems.length" class="py-10 text-center">
          <Send class="mx-auto mb-3 size-8 text-text3 opacity-50" />
          <p class="text-sm text-text3">Вы пока ничего не рассылали</p>
          <p class="mt-1 text-tiny text-text3">
            Здесь появятся мероприятия и домашние задания, о которых вы уведомили студентов.
          </p>
        </div>
        <ul v-else class="divide-y divide-border">
          <li v-for="s in sentItems" :key="s.batch_id || s.title + s.created_at"
              class="flex items-start gap-3 px-1 py-3">
            <span class="mt-1 shrink-0 text-text3">
              <BookOpen v-if="s.kind === 'homework'" class="size-4" />
              <Megaphone v-else class="size-4" />
            </span>
            <span class="min-w-0 flex-1">
              <span class="block truncate text-sm text-text">{{ s.title || KIND_LABEL[s.kind] }}</span>
              <span class="mt-0.5 block truncate text-tiny text-text3">{{ s.body }}</span>
              <!-- «Прочитали X из Y» — единственная причина, по которой автору вообще
                   интересен свой же список: понять, дошло ли. -->
              <span class="mt-1 block text-tiny"
                    :class="s.read >= s.recipients ? 'text-accent' : 'text-text3'">
                Прочитали {{ s.read }} из {{ s.recipients }}
              </span>
            </span>
            <span class="shrink-0 text-tiny text-text3">{{ fmtWhen(s.created_at) }}</span>
          </li>
        </ul>
      </template>

      <template v-else>
      <div v-if="unread" class="mb-3 flex items-center justify-between">
        <p class="text-sm text-text3">Непрочитанных: {{ unread }}</p>
        <AppButton variant="ghost" @click="markAll">
          <CheckCheck class="mr-1.5 inline size-4" />Прочитать все
        </AppButton>
      </div>

      <p v-if="loading" class="py-8 text-center text-sm text-text3">Загружаем…</p>

      <p v-else-if="failed" class="py-8 text-center text-sm text-text3">
        Не удалось получить уведомления. Проверьте связь и обновите страницу.
      </p>

      <div v-else-if="!visible.length" class="py-10 text-center">
        <Bell class="mx-auto mb-3 size-8 text-text3 opacity-50" />
        <p class="text-sm text-text3">{{ EMPTY_LABEL[tab] || 'Уведомлений пока нет' }}</p>
      </div>

      <ul v-else class="divide-y divide-border">
        <li v-for="item in visible" :key="item.id">
          <button type="button"
                  class="flex w-full items-start gap-3 px-1 py-3 text-left transition-colors hover:bg-card2"
                  @click="open(item)">
            <!-- Красная точка — непрочитано; выколотая (контурная) — прочитано. -->
            <span class="mt-1.5 size-2.5 shrink-0 rounded-full"
                  :class="item.read_at ? 'border-2 border-text3' : 'bg-red'"
                  :aria-label="item.read_at ? 'Прочитано' : 'Непрочитано'" />
            <span class="min-w-0 flex-1">
              <span class="block truncate text-sm text-text">{{ titleOf(item) }}</span>
              <span class="mt-0.5 block truncate text-tiny text-text3">{{ bodyOf(item) }}</span>
            </span>
            <span class="shrink-0 text-tiny text-text3">{{ fmtWhen(item.created_at) }}</span>
          </button>
        </li>
      </ul>
      </template>
    </div>
  </div>
</template>
