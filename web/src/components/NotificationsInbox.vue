<script setup>
// NotificationsInbox — вкладка «Уведомления»: список писем и чтение одного письма.
// Вид намеренно почтовый (как Gmail): непрочитанные выделены жирным и точкой, клик по
// строке открывает само письмо, есть «прочитать все».
//
// Тексты писем приходят ГОТОВЫМИ с сервера и здесь не собираются. Тон зависит от роли
// (студенту дружелюбно, преподавателю официально), и если бы каждая платформа лепила
// текст сама, веб, десктоп и телефон разъехались бы в формулировках. Клиент решает
// только КАК показать, но не ЧТО написано.
import { ref, computed, onMounted } from 'vue'
import { Bell, Mail, MailOpen, ArrowLeft, CheckCheck } from '@lucide/vue'
import { meApi } from '@/api/endpoints'
import AppButton from '@/components/ui/AppButton.vue'

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
  reminder: 'Напоминание',
}

// Фильтр по видам. «Система» — всё, что не ДЗ: оценки и расписание приходят от системы
// по факту действия преподавателя, а домашка — это задание лично тебе, и смешивать их
// в одном потоке неудобно (ДЗ теряется среди десятков оценок).
const HOMEWORK_KINDS = ['homework']
const TABS = [
  { key: 'all', label: 'Все' },
  { key: 'homework', label: 'ДЗ' },
  { key: 'system', label: 'Система' },
]
const tab = ref('all')

function inTab(item, key) {
  if (key === 'all') return true
  const isHw = HOMEWORK_KINDS.includes(item.kind)
  return key === 'homework' ? isHw : !isHw
}

const visible = computed(() => items.value.filter((i) => inTab(i, tab.value)))
// Счётчик у вкладки — только непрочитанные, иначе он теряет смысл уже на второй день.
function tabUnread(key) {
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
      </div>

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
        <p class="text-sm text-text3">
          {{ tab === 'homework' ? 'Домашних заданий пока нет'
             : tab === 'system' ? 'Системных уведомлений пока нет'
             : 'Уведомлений пока нет' }}
        </p>
      </div>

      <ul v-else class="divide-y divide-border">
        <li v-for="item in visible" :key="item.id">
          <button type="button"
                  class="flex w-full items-start gap-3 px-1 py-3 text-left transition-colors hover:bg-card2"
                  @click="open(item)">
            <component :is="item.read_at ? MailOpen : Mail"
                       class="mt-0.5 size-4 shrink-0"
                       :class="item.read_at ? 'text-text3' : 'text-accent'" />
            <span class="min-w-0 flex-1">
              <span class="block truncate text-sm"
                    :class="item.read_at ? 'text-text' : 'font-bold text-text'">
                {{ titleOf(item) }}
              </span>
              <span class="mt-0.5 block truncate text-tiny text-text3">{{ bodyOf(item) }}</span>
            </span>
            <span class="shrink-0 text-tiny text-text3">{{ fmtWhen(item.created_at) }}</span>
          </button>
        </li>
      </ul>
    </div>
  </div>
</template>
