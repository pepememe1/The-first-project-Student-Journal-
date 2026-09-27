<script setup>
// SyncProblemsPanel — «что не ушло на сервер, и что с этим делать» (аудит 22.09.2026,
// находка F-09).
//
// 🔥 Зачем. Конфликт по оценке раньше фиксировался и оставался невидимым навсегда:
// экран разбора жил в Qt и удалён вместе с ним, а значок показывал только число. Теперь
// правки журнала из программы уходят очередью (`desktop/desk_outbox.py`) вместе с
// версией, которую человек видел; если за это время запись изменили на сервере, сервер
// отвечает конфликтом, и решать ЧЕЛОВЕКУ — программа не выбирает сама, чья правка верна.
//
//   • конфликт: «Оставить моё» — дослать без сверки (сознательно заменить серверное);
//               «Оставить серверное» — отказаться от своей правки, копия вернётся к
//               серверному значению полной сверкой;
//   • отказ по существу (нет прав, семестр закрыт): «Понятно, убрать» — повтор не поможет,
//               кнопки «повторить» здесь нет намеренно (урок RejectedWritesBadge);
//   • правка, отложенная из-за ОШИБКИ СЕРВЕРА (500 несколько раз подряд, W-10): здесь
//               повтор как раз может помочь — ошибку могли уже исправить, — поэтому
//               «Повторить» есть, но только у неё.
//
// Источник — `/desk/sync/problems`, существует только внутри программы.
import { onMounted, ref } from 'vue'
import { X } from '@lucide/vue'

import { getAccess } from '@/api/tokens'
import { useLocaleStore } from '@/stores/locale'

const emit = defineEmits(['close', 'changed'])
const locale = useLocaleStore()

const items = ref([])
const loading = ref(true)
const failed = ref(false)
const busy = ref(0)

function headers() {
  const token = getAccess()
  return token ? { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' } : {}
}

async function load() {
  loading.value = true
  failed.value = false
  try {
    const r = await fetch('/desk/sync/problems', { headers: headers() })
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
    items.value = (await r.json()).items || []
  } catch {
    //Ошибка — это НЕ «разбирать нечего»: пустой список при сбое читался бы как «всё
    //дошло», ровно та ложь, от которой лечится F-15 в модерации.
    failed.value = true
  } finally {
    loading.value = false
  }
}

function kindLabel(item) {
  const kind = item?.detail?.kind || (item.tbl === 'lessons' ? 'lesson'
    : item.tbl === 'term_grades' ? 'term_grade' : 'grade')
  return locale.t(`syncProblems.kind.${kind}`, kind)
}

// Человек должен узнать СВОЮ работу: «Иванов Иван — 5», а не служебный ключ строки.
function mine(item) {
  const s = item.sent || {}
  const who = [s.surname, s.name].filter(Boolean).join(' ')
  const value = s.grade !== undefined ? (s.grade || '—') : (s.topic || '')
  return [who, value].filter(Boolean).join(' — ') || item.row_key || '—'
}

function theirs(item) {
  const srv = (item.detail && item.detail.server) || {}
  if (srv.deleted) return '—'
  if (srv.grade !== undefined) return srv.grade || '—'
  return srv.topic || '—'
}

// Отложена из-за ошибки сервера, а не отвергнута по существу: повтор имеет смысл.
function retriable(item) {
  return item.state === 'rejected' && Number(item.last_status || 0) >= 500
}

function message(item) {
  const d = item.detail || {}
  if (typeof d === 'string') return d
  return d.message || d.detail || ''
}

async function act(item, action) {
  busy.value = item.seq
  try {
    const r = await fetch(`/desk/sync/problems/${item.seq}`, {
      method: 'POST', headers: headers(), body: JSON.stringify({ action }),
    })
    if (r.ok) {
      items.value = items.value.filter((x) => x.seq !== item.seq)
      emit('changed')
    }
  } catch {
    failed.value = true
  } finally {
    busy.value = 0
  }
}

onMounted(load)
</script>

<template>
  <div class="mt-1.5 border-t border-yellow/30 pt-1.5">
    <div class="mb-1 flex items-center gap-1">
      <span class="min-w-0 flex-1 font-semibold text-text">{{ locale.t('syncProblems.title') }}</span>
      <button type="button" class="shrink-0 rounded p-0.5 hover:bg-yellow/15 focus-visible:bg-yellow/15"
              :aria-label="locale.t('syncProblems.close')" @click="emit('close')">
        <X class="size-3" />
      </button>
    </div>
    <p class="mb-1.5 opacity-80">{{ locale.t('syncProblems.hint') }}</p>
    <p v-if="loading" class="opacity-70">…</p>
    <p v-else-if="failed" class="text-red">{{ locale.t('syncProblems.loadFailed') }}</p>
    <p v-else-if="!items.length" class="opacity-80">{{ locale.t('syncProblems.empty') }}</p>
    <ul v-else class="space-y-2">
      <li v-for="item in items" :key="item.seq" class="rounded-sm bg-yellow/5 p-1.5">
        <div class="font-semibold text-text">{{ kindLabel(item) }}</div>
        <div class="opacity-80">
          {{ item.state === 'conflict' ? locale.t('syncProblems.conflict') : locale.t('syncProblems.rejected') }}
        </div>
        <div class="mt-0.5 break-words">{{ locale.t('syncProblems.mine') }}: {{ mine(item) }}</div>
        <div v-if="item.state === 'conflict'" class="break-words">
          {{ locale.t('syncProblems.server') }}: {{ theirs(item) }}
        </div>
        <div v-else-if="message(item)" class="break-words opacity-70">{{ message(item) }}</div>
        <div class="mt-1 flex flex-wrap gap-1">
          <template v-if="item.state === 'conflict'">
            <button type="button" :disabled="busy === item.seq"
                    class="rounded border border-border px-1.5 py-0.5 hover:bg-yellow/15 focus-visible:bg-yellow/15"
                    @click="act(item, 'keep_mine')">{{ locale.t('syncProblems.keepMine') }}</button>
            <button type="button" :disabled="busy === item.seq"
                    class="rounded border border-border px-1.5 py-0.5 hover:bg-yellow/15 focus-visible:bg-yellow/15"
                    @click="act(item, 'keep_server')">{{ locale.t('syncProblems.keepServer') }}</button>
          </template>
          <template v-else>
            <button v-if="retriable(item)" type="button" :disabled="busy === item.seq"
                    class="rounded border border-border px-1.5 py-0.5 hover:bg-yellow/15 focus-visible:bg-yellow/15"
                    @click="act(item, 'retry')">{{ locale.t('syncProblems.retry') }}</button>
            <button type="button" :disabled="busy === item.seq"
                    class="rounded border border-border px-1.5 py-0.5 hover:bg-yellow/15 focus-visible:bg-yellow/15"
                    @click="act(item, 'dismiss')">{{ locale.t('syncProblems.dismiss') }}</button>
          </template>
        </div>
      </li>
    </ul>
  </div>
</template>
