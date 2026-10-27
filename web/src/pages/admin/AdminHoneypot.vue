<script setup>
// AdminHoneypot — «Приманки»: кто стучался туда, куда не ходит никто законный (04.10.2026).
//
// 🔒 ТОЛЬКО АДМИНИСТРАТОР: маршрут под ветвью /admin (страж роутера), пункт меню только в
// NAV.admin, а сервер отвечает 403 всем, кроме роли admin (`require_admin`). Модератору
// раздел не показывается: здесь СЫРЫЕ адреса, а для разбора жалоб они ему не нужны.
//
// ⚠️ ТОЛЬКО ЧТЕНИЕ. Снять бан или стереть запись отсюда нельзя: след, который можно
// убрать кнопкой, перестаёт быть следом. Адреса живут 90 дней (политика хранения), факт
// срабатывания — в журнале безопасности навсегда, с отпечатком вместо адреса.
//
// ⚠️ Страна и провайдер — из ЛОКАЛЬНОЙ базы на сервере (ipgeo), название страны рисует
// браузер (`Intl.DisplayNames`) на языке интерфейса — своего справочника стран нет.
import { ref, computed, onMounted, watch } from 'vue'
import { RotateCw, Search, ShieldAlert, Radar, Copy, X, Cloud, Fingerprint } from '@lucide/vue'
import { adminApi } from '@/api/endpoints'
import { useLocaleStore } from '@/stores/locale'
import Card from '@/components/ui/Card.vue'
import StatCard from '@/components/ui/StatCard.vue'
import StickyXScroll from '@/components/ui/StickyXScroll.vue'
import { COLLEGE_UTC_OFFSET_MIN, formatCollege } from '@/utils/collegeTime'
import GbIcon from '@/components/ui/GbIcon.vue'

const locale = useLocaleStore()
const t = (k, f) => locale.t(k, f)

const days = ref(30)
const summary = ref(null)
const loading = ref(false)
const error = ref('')
const q = ref('')
const hits = ref([])
const hitsTotal = ref(0)
const hitsLoading = ref(false)

// Смещение пояса в минутах: «сегодня» на графике — сутки КОЛЛЕДЖА (Улан-Удэ, 480), а не
// UTC сервера и не устройства администратора — иначе график из командировки показывал бы
// другие сутки, чем вечерняя сводка на почту.
const tz = COLLEGE_UTC_OFFSET_MIN

async function loadSummary() {
  loading.value = true
  error.value = ''
  try {
    const { data } = await adminApi.honeypotSummary({ days: days.value, tz })
    summary.value = data
  } catch (e) {
    error.value = e?.response?.data?.detail || t('honeypot.failed', 'Не удалось загрузить раздел')
  } finally { loading.value = false }
}

async function loadHits() {
  hitsLoading.value = true
  try {
    const { data } = await adminApi.honeypotHits({ days: days.value, q: q.value.trim(), limit: 200 })
    hits.value = data.hits || []
    hitsTotal.value = data.total || 0
  } catch {
    hits.value = []
  } finally { hitsLoading.value = false }
}

function reload() { loadSummary(); loadHits() }
onMounted(reload)
watch(days, reload)

// ── оформление ─────────────────────────────────────────────────────────────────────
const regionNames = computed(() => {
  try { return new Intl.DisplayNames([locale.locale || 'ru'], { type: 'region' }) } catch { return null }
})
function countryName(cc) {
  if (!cc) return t('honeypot.unknownCountry', 'неизвестно')
  try { return regionNames.value?.of(cc) || cc } catch { return cc }
}
function flag(cc) {
  if (!cc || cc.length !== 2) return ''
  return String.fromCodePoint(...[...cc.toUpperCase()].map((c) => 0x1F1E6 + c.charCodeAt(0) - 65))
}
const CLOUD = ['GOOGLE', 'AMAZON', 'AWS', 'MICROSOFT', 'AZURE', 'DIGITALOCEAN', 'OVH', 'HETZNER',
  'LINODE', 'AKAMAI', 'VULTR', 'CHOOPA', 'ALIBABA', 'TENCENT', 'ORACLE', 'CONTABO', 'M247',
  'LEASEWEB', 'SCALEWAY', 'CLOUDFLARE']
const isCloud = (name) => CLOUD.some((m) => (name || '').toUpperCase().includes(m))

// Тип инструмента — цветом и словом (цвет без подписи не различают все).
const KIND = {
  scanner: { cls: 'border-red/50 text-red', key: 'honeypot.kindScanner', def: 'сканер' },
  script: { cls: 'border-orange/50 text-orange', key: 'honeypot.kindScript', def: 'скрипт' },
  bot: { cls: 'border-border2 text-text3', key: 'honeypot.kindBot', def: 'робот' },
  browser: { cls: 'border-border2 text-text3', key: 'honeypot.kindBrowser', def: 'браузер' },
  empty: { cls: 'border-red/50 text-red', key: 'honeypot.kindEmpty', def: 'без подписи' },
  other: { cls: 'border-border2 text-text3', key: 'honeypot.kindOther', def: 'другое' },
  ours: { cls: 'border-border2 text-text3', key: 'honeypot.kindOurs', def: 'наше приложение' },
}
const kindOf = (k) => KIND[k] || KIND.other

function when(ts) {
  if (!ts) return '—'
  const d = new Date(ts * 1000)
  return isNaN(d) ? '—' : formatCollege(d, undefined, { dateStyle: 'short', timeStyle: 'medium' })
}
function hoursLeft(sec) {
  if (!sec) return ''
  const h = Math.floor(sec / 3600)
  const m = Math.floor((sec % 3600) / 60)
  return h ? `${h} ${t('honeypot.h', 'ч')} ${m} ${t('honeypot.min', 'мин')}` : `${m} ${t('honeypot.min', 'мин')}`
}

const totals = computed(() => summary.value?.totals || {})
const legacy = computed(() => Math.max(0, (totals.value.audit_hits || 0) - (totals.value.hits || 0)))
const series = computed(() => summary.value?.series || [])
const peak = computed(() => Math.max(1, ...series.value.map((s) => s.hits)))
// Подписи дат — не под каждым столбиком: на 30 днях они налезали бы друг на друга.
const labelEvery = computed(() => Math.max(1, Math.ceil(series.value.length / 8)))
const topMax = (list) => Math.max(1, ...(list || []).map((x) => x.n))

async function copy(text) {
  try { await navigator.clipboard.writeText(text) } catch { /* буфер недоступен — не беда */ }
}

// ── карточка источника ─────────────────────────────────────────────────────────────
const open = ref(null)       // { source, hits, same_tool_sources }
const openLoading = ref(false)
const openHit = ref(null)
async function openSource(fp) {
  openLoading.value = true
  open.value = { pending: true }
  try {
    const { data } = await adminApi.honeypotSource(fp)
    open.value = data.found ? data : null
  } catch { open.value = null } finally { openLoading.value = false }
}
</script>

<template>
  <div class="flex flex-col gap-3">
    <Card :title="t('nav.honeypot', 'Приманки')"
          :subtitle="t('honeypot.subtitle', 'Кто стучался туда, куда не ходит никто законный: адрес, страна, провайдер, инструмент. Подробности хранятся 90 дней, только чтение.')">
      <div class="mb-1 flex flex-wrap items-center gap-2">
        <select v-model.number="days" class="rounded-lg border border-border bg-card px-2 py-1.5 text-sm"
                :aria-label="t('honeypot.period', 'Период')">
          <option :value="1">{{ t('honeypot.day1', 'Сутки') }}</option>
          <option :value="7">{{ t('honeypot.day7', '7 дней') }}</option>
          <option :value="30">{{ t('honeypot.day30', '30 дней') }}</option>
          <option :value="90">{{ t('honeypot.day90', '90 дней') }}</option>
        </select>
        <button type="button" @click="reload" :disabled="loading"
                class="flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-50">
          <RotateCw :size="14" :class="loading ? 'animate-spin' : ''" />
          {{ t('common.refresh', 'Обновить') }}
        </button>
      </div>
      <p v-if="error" class="mt-2 flex items-center gap-2 rounded-lg border border-red/40 px-3 py-2 text-sm text-red">
        <ShieldAlert :size="15" />{{ error }}
      </p>
      <p v-if="summary && !summary.geo?.available" class="mt-2 rounded-lg border border-border px-3 py-2 text-xs text-text3">
        {{ t('honeypot.noGeo', 'База стран и провайдеров не загружена — страны не определяются. На сервере: python -m app.ipgeo --update') }}
      </p>
      <p v-if="legacy" class="mt-2 text-xs text-text3">
        {{ t('honeypot.legacy', 'Ещё срабатываний без подробностей (до включения раздела записывался только отпечаток)') }}: {{ legacy }}
      </p>
    </Card>

    <template v-if="summary">
      <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
        <StatCard :label="t('honeypot.hits', 'Срабатываний')" :value="totals.hits" :icon="Radar" accent />
        <StatCard :label="t('honeypot.sources', 'Источников')" :value="totals.sources" />
        <StatCard :label="t('honeypot.countries', 'Стран')" :value="totals.countries" />
        <StatCard :label="t('honeypot.bannedNow', 'В бане сейчас')" :value="totals.banned_now" />
        <StatCard :label="t('honeypot.honeytoken', 'Вход учёткой-приманкой')" :value="totals.honeytoken"
                  :hint="totals.honeytoken ? t('honeypot.honeytokenHint', 'Логин есть только в дампе базы — проверьте утечку') : ''" />
        <StatCard :label="t('honeypot.trusted', 'С доверенных адресов')" :value="totals.trusted"
                  :hint="t('honeypot.trustedHint', 'записаны, но не забанены')" />
      </div>

      <!-- График одного ряда: легенда не нужна, ряд назван заголовком. Подсказка у каждого
           столбика; таблица срабатываний ниже — его текстовая версия. -->
      <Card :title="t('honeypot.byDay', 'Срабатывания по дням')">
        <div class="flex h-36 items-end gap-[2px]" role="img"
             :aria-label="t('honeypot.byDay', 'Срабатывания по дням')">
          <div v-for="(s, i) in series" :key="s.date" class="group relative flex h-full flex-1 flex-col justify-end">
            <div class="w-full rounded-t-[4px] bg-accent transition-opacity group-hover:opacity-80"
                 :style="{ height: s.hits ? Math.max(4, (s.hits / peak) * 100) + '%' : '2px', opacity: s.hits ? 1 : 0.25 }"
                 :title="`${s.date}: ${s.hits}`"></div>
            <span v-if="i % labelEvery === labelEvery - 1 || i === series.length - 1"
                  class="absolute -bottom-5 left-1/2 -translate-x-1/2 whitespace-nowrap text-[10px] text-text3">
              {{ s.date.slice(8, 10) }}.{{ s.date.slice(5, 7) }}
            </span>
          </div>
        </div>
        <div class="h-5"></div>
      </Card>

      <div class="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <Card :title="t('honeypot.whereFrom', 'Откуда')">
          <p v-if="!summary.top_providers.length && !summary.top_countries.length" class="text-sm text-text3">—</p>
          <div v-for="p in summary.top_providers" :key="p.asn" class="py-1.5">
            <div class="flex items-center justify-between gap-2 text-sm">
              <span class="min-w-0 truncate">
                {{ flag(p.country) }} {{ countryName(p.country) }} ·
                <span class="text-text3">{{ p.name }} (AS{{ p.asn }})</span>
                <span v-if="isCloud(p.name)" class="ml-1 inline-flex items-center gap-0.5 rounded border border-border px-1 text-[10px] font-semibold text-accent">
                  <Cloud :size="10" />{{ t('honeypot.cloud', 'облако') }}
                </span>
              </span>
              <b class="tabular-nums">{{ p.n }}</b>
            </div>
            <div class="mt-1 h-1.5 overflow-hidden rounded-full bg-card2">
              <div class="h-full rounded-full bg-accent" :style="{ width: (p.n / topMax(summary.top_providers)) * 100 + '%' }"></div>
            </div>
          </div>
          <p v-if="summary.top_providers.some((p) => isCloud(p.name))" class="mt-2 text-xs text-text3">
            {{ t('honeypot.cloudHint', '«Облако» — арендованный сервер: так выглядит массовый обход интернета, а не охота именно на нас.') }}
          </p>
        </Card>

        <Card :title="t('honeypot.tools', 'Чем стучались')">
          <p v-if="!summary.top_tools.length" class="text-sm text-text3">—</p>
          <div v-for="x in summary.top_tools" :key="x.tool + x.kind" class="flex items-center justify-between gap-2 py-1.5 text-sm">
            <span class="min-w-0 truncate">
              <b>{{ x.tool }}</b>
              <span class="ml-1 rounded border px-1 text-[10px] font-semibold" :class="kindOf(x.kind).cls">
                {{ t(kindOf(x.kind).key, kindOf(x.kind).def) }}
              </span>
            </span>
            <b class="tabular-nums">{{ x.n }}</b>
          </div>
          <h4 class="mb-1 mt-3 text-xs font-semibold uppercase tracking-wide text-text3">{{ t('honeypot.paths', 'Что искали') }}</h4>
          <div v-for="x in summary.top_paths" :key="x.path" class="flex items-center justify-between gap-2 py-1 text-sm">
            <code class="min-w-0 truncate rounded bg-card2 px-1.5 py-0.5 text-xs">{{ x.path }}</code>
            <b class="tabular-nums">{{ x.n }}</b>
          </div>
        </Card>
      </div>

      <!-- Источники: один источник = один отпечаток адреса. Карточка открывает все его
           срабатывания со всеми заголовками. -->
      <Card :title="t('honeypot.sourcesTitle', 'Источники')"
            :subtitle="t('honeypot.sourcesHint', 'Нажмите на источник — откроются все его срабатывания с заголовками и признаками автоматики')">
        <p v-if="!summary.sources.length" class="py-6 text-center text-sm text-text3">
          {{ t('honeypot.empty', 'За период никто не стучался в приманки') }}
        </p>
        <div class="grid grid-cols-1 gap-2 md:grid-cols-2">
          <button v-for="s in summary.sources" :key="s.fingerprint" type="button" @click="openSource(s.fingerprint)"
                  class="rounded-xl border border-border bg-card p-3 text-left transition-colors hover:border-accent">
            <div class="flex items-start justify-between gap-2">
              <div class="min-w-0">
                <p class="truncate font-mono text-sm font-semibold">{{ s.ip }}</p>
                <p class="truncate text-xs text-text3">
                  {{ flag(s.country) }} {{ countryName(s.country) }}<span v-if="s.as_name"> · {{ s.as_name }}</span>
                </p>
              </div>
              <span class="shrink-0 rounded-full bg-card2 px-2 py-0.5 text-xs font-bold tabular-nums">×{{ s.hits }}</span>
            </div>
            <div class="mt-2 flex flex-wrap items-center gap-1.5 text-[11px]">
              <span class="rounded border px-1 font-semibold" :class="kindOf(s.tool_kind).cls">{{ s.tool }}</span>
              <span v-if="s.browser || s.os_name" class="text-text3">{{ [s.browser, s.os_name].filter(Boolean).join(' · ') }}</span>
              <span v-if="s.trusted" class="rounded border border-border px-1 text-text3">{{ t('honeypot.trustedBadge', 'доверенный — не банится') }}</span>
              <span v-else-if="s.ban_left" class="rounded border border-red/40 px-1 text-red">{{ t('honeypot.banLeft', 'в бане ещё') }} {{ hoursLeft(s.ban_left) }}</span>
              <span v-if="s.after_ban?.n" class="text-text3">{{ t('honeypot.afterBan', 'после бана') }}: {{ s.after_ban.n }}</span>
            </div>
            <p class="mt-1.5 truncate font-mono text-[11px] text-text3">{{ s.paths.join('  ') }}</p>
            <p class="mt-1 text-[11px] text-text3">{{ when(s.last) }}</p>
          </button>
        </div>
      </Card>

      <Card :title="t('honeypot.hitsTitle', 'Все срабатывания')">
        <label class="mb-3 flex items-center gap-2 rounded-lg border border-border px-2.5 py-1.5">
          <Search :size="14" class="shrink-0 text-text3" />
          <input v-model="q" type="search" @keyup.enter="loadHits" class="w-full bg-transparent text-sm outline-none"
                 :placeholder="t('honeypot.search', 'Адрес, путь, страна, инструмент, отпечаток…')" />
        </label>
        <p v-if="!hitsLoading && !hits.length" class="py-6 text-center text-sm text-text3">{{ t('honeypot.noHits', 'Ничего не найдено') }}</p>
        <StickyXScroll v-else>
          <table class="w-full text-left text-xs">
            <thead class="text-text3">
              <tr class="border-b border-border">
                <th class="whitespace-nowrap py-1.5 pr-3 font-medium">{{ t('honeypot.when', 'Когда') }}</th>
                <th class="whitespace-nowrap py-1.5 pr-3 font-medium">{{ t('honeypot.address', 'Адрес') }}</th>
                <th class="whitespace-nowrap py-1.5 pr-3 font-medium">{{ t('honeypot.where', 'Где') }}</th>
                <th class="whitespace-nowrap py-1.5 pr-3 font-medium">{{ t('honeypot.tool', 'Инструмент') }}</th>
                <th class="py-1.5 font-medium">{{ t('honeypot.request', 'Запрос') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="h in hits" :key="h.id" @click="openHit = h"
                  class="cursor-pointer border-b border-border align-top hover:bg-card2">
                <td class="whitespace-nowrap py-1.5 pr-3 tabular-nums text-text3">{{ when(h.created_ts) }}</td>
                <td class="whitespace-nowrap py-1.5 pr-3 font-mono">{{ h.ip }}</td>
                <td class="whitespace-nowrap py-1.5 pr-3">{{ flag(h.country) }} {{ h.country || '—' }}</td>
                <td class="whitespace-nowrap py-1.5 pr-3">
                  <span :class="kindOf(h.tool_kind).cls" class="rounded border px-1">{{ h.tool }}</span>
                </td>
                <td class="py-1.5 font-mono text-text2">
                  <GbIcon v-if="h.kind === 'honeytoken'" name="honeypot" class="mr-1 inline-block size-4 align-[-3px] text-red" />{{ h.method }} {{ h.path }}<span v-if="h.query">?{{ h.query }}</span>
                </td>
              </tr>
            </tbody>
          </table>
        </StickyXScroll>
        <p v-if="hitsTotal > hits.length" class="mt-2 text-xs text-text3">
          {{ t('honeypot.shown', 'Показано') }} {{ hits.length }} / {{ hitsTotal }}
        </p>
      </Card>
    </template>

    <!-- Карточка источника -->
    <div v-dialog v-if="open" class="fixed inset-0 z-50 flex items-end justify-center bg-black/40 sm:items-center sm:p-4"
         @click.self="open = null">
      <div class="max-h-[92vh] w-full max-w-2xl overflow-y-auto rounded-t-2xl bg-card p-4 shadow-xl sm:rounded-2xl">
        <div class="mb-3 flex items-start justify-between gap-2">
          <h3 class="font-title text-lg font-bold">{{ t('honeypot.sourceTitle', 'Источник') }}</h3>
          <button type="button" class="rounded-lg p-1 text-text3 hover:bg-card2" :aria-label="t('common.close', 'Закрыть')" @click="open = null"><X :size="18" /></button>
        </div>
        <p v-if="openLoading" class="py-8 text-center text-sm text-text3">…</p>
        <template v-else-if="open.source">
          <div class="rounded-xl border border-border p-3 text-sm">
            <p class="flex items-center gap-2 font-mono text-base font-bold">
              {{ open.source.ip }}
              <button type="button" class="text-text3 hover:text-accent" :aria-label="t('honeypot.copy', 'Скопировать')" @click="copy(open.source.ip)"><Copy :size="14" /></button>
            </p>
            <p class="mt-1">{{ flag(open.source.country) }} {{ countryName(open.source.country) }}
              <span v-if="open.source.as_name" class="text-text3"> · {{ open.source.as_name }} (AS{{ open.source.asn }})</span></p>
            <p class="mt-1 text-text3">{{ open.source.tool }}<span v-if="open.source.browser"> · {{ open.source.browser }}</span><span v-if="open.source.os_name"> · {{ open.source.os_name }}</span></p>
            <p class="mt-1 flex items-center gap-1 font-mono text-xs text-text3"><Fingerprint :size="12" />{{ open.source.fingerprint }} · {{ open.source.client_fp }}</p>
            <p class="mt-1 text-xs text-text3">{{ t('honeypot.firstLast', 'Первое и последнее появление') }}: {{ when(open.source.first) }} — {{ when(open.source.last) }}</p>
            <ul v-if="open.source.automated?.length" class="mt-2 list-disc pl-5 text-xs text-text2">
              <li v-for="r in open.source.automated" :key="r">{{ r }}</li>
            </ul>
            <div v-if="open.source.after_ban?.n" class="mt-2 text-xs">
              <p class="font-semibold">{{ t('honeypot.afterBanTitle', 'Что пробовал уже после бана') }}: {{ open.source.after_ban.n }}</p>
              <p class="mt-1 break-all font-mono text-text3">{{ open.source.after_ban.paths.join('  ') }}</p>
            </div>
            <p v-if="open.same_tool_sources?.length" class="mt-2 text-xs text-text3">
              {{ t('honeypot.sameTool', 'Тот же инструмент приходил ещё с адресов') }}: {{ open.same_tool_sources.length }}
            </p>
          </div>
          <div v-for="h in open.hits" :key="h.id" class="mt-3 rounded-xl border border-border p-3 text-xs">
            <p class="flex flex-wrap items-center justify-between gap-1">
              <span class="font-mono font-semibold"><GbIcon v-if="h.kind === 'honeytoken'" name="honeypot" class="mr-1 inline-block size-4 align-[-3px] text-red" />{{ h.method }} {{ h.path }}<span v-if="h.query">?{{ h.query }}</span></span>
              <span class="text-text3">{{ when(h.created_ts) }}</span>
            </p>
            <p v-if="h.host" class="mt-1 text-text3">Host: {{ h.host }}</p>
            <p class="mt-1 break-all text-text3">{{ h.user_agent || '—' }}</p>
            <details class="mt-1.5">
              <summary class="cursor-pointer text-accent">{{ t('honeypot.headers', 'Заголовки запроса') }} ({{ Object.keys(h.headers || {}).length }})</summary>
              <table class="mt-1 w-full">
                <tr v-for="(v, k) in h.headers" :key="k" class="align-top">
                  <td class="whitespace-nowrap pr-2 font-mono text-text3">{{ k }}</td>
                  <td class="break-all font-mono">{{ v }}</td>
                </tr>
              </table>
            </details>
          </div>
        </template>
      </div>
    </div>

    <!-- Одно срабатывание из таблицы -->
    <div v-dialog v-if="openHit" class="fixed inset-0 z-50 flex items-end justify-center bg-black/40 sm:items-center sm:p-4"
         @click.self="openHit = null">
      <div class="max-h-[92vh] w-full max-w-xl overflow-y-auto rounded-t-2xl bg-card p-4 text-sm shadow-xl sm:rounded-2xl">
        <div class="mb-2 flex items-start justify-between gap-2">
          <h3 class="font-title text-lg font-bold">{{ t('honeypot.hitTitle', 'Срабатывание') }}</h3>
          <button type="button" class="rounded-lg p-1 text-text3 hover:bg-card2" :aria-label="t('common.close', 'Закрыть')" @click="openHit = null"><X :size="18" /></button>
        </div>
        <p class="font-mono font-semibold">{{ openHit.method }} {{ openHit.path }}<span v-if="openHit.query">?{{ openHit.query }}</span></p>
        <p class="mt-1 text-text3">{{ when(openHit.created_ts) }}</p>
        <p class="mt-2 font-mono">{{ openHit.ip }} · {{ flag(openHit.country) }} {{ countryName(openHit.country) }}
          <span v-if="openHit.as_name" class="text-text3">· {{ openHit.as_name }}</span></p>
        <p class="mt-1">{{ openHit.tool }}<span v-if="openHit.browser" class="text-text3"> · {{ openHit.browser }}</span><span v-if="openHit.os_name" class="text-text3"> · {{ openHit.os_name }}</span></p>
        <p class="mt-1 break-all text-xs text-text3">{{ openHit.user_agent || '—' }}</p>
        <ul v-if="openHit.automated?.length" class="mt-2 list-disc pl-5 text-xs text-text2">
          <li v-for="r in openHit.automated" :key="r">{{ r }}</li>
        </ul>
        <table class="mt-2 w-full text-xs">
          <tr v-for="(v, k) in openHit.headers" :key="k" class="align-top">
            <td class="whitespace-nowrap pr-2 font-mono text-text3">{{ k }}</td>
            <td class="break-all font-mono">{{ v }}</td>
          </tr>
        </table>
        <button type="button" class="mt-3 text-xs font-semibold text-accent" @click="openSource(openHit.fingerprint); openHit = null">
          {{ t('honeypot.openSource', 'Все срабатывания этого источника') }} →
        </button>
      </div>
    </div>
  </div>
</template>
