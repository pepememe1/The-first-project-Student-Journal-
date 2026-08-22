<script setup>
// AchievementsDialog — список ачивок за пасхалки и выбор того, что показывать другим.
//
// ⚠️ ЗАКРЫТАЯ АЧИВКА НЕ РАСКРЫВАЕТСЯ НИЧЕМ: карточка полностью чёрная, вместо названия
// «???», описания нет. Иначе список превратился бы в инструкцию «как найти пасхалку»,
// и находить стало бы нечего — а вся затея ровно про то, чтобы наткнуться самому.
//
// ⚠️ ВИТРИНА — ПУБЛИЧНОЕ ПОЛЕ. Отмеченные галочкой ачивки видят другие люди, открывшие
// карточку профиля. Поэтому выбирает их сам человек, а не мы за него, и в режиме
// витрины показываются ТОЛЬКО открытые: отметить то, чего не получал, нельзя.
import { ref, computed, onMounted } from 'vue'
import { X, Trophy, Check, Lock } from '@lucide/vue'
import { useLocaleStore } from '@/stores/locale'
import { meApi } from '@/api/endpoints'
import { ACHIEVEMENTS, RARITY } from '@/config/achievements'

const emit = defineEmits(['close'])
const locale = useLocaleStore()

const unlocked = ref({})            // id → { unlocked_at, showcase }
const mode = ref('all')             // 'all' | 'showcase'
const picked = ref(new Set())
const saving = ref(false)
const error = ref('')

const isOpen = (id) => !!unlocked.value[id]
const openedCount = computed(() => Object.keys(unlocked.value).length)
const mine = computed(() => ACHIEVEMENTS.filter((a) => isOpen(a.id)))

async function load() {
  try {
    const { data } = await meApi.achievements()
    const box = {}
    for (const row of data.unlocked || []) box[row.id] = row
    unlocked.value = box
    picked.value = new Set((data.unlocked || []).filter((r) => r.showcase).map((r) => r.id))
  } catch {
    error.value = locale.t('achievements.loadFailed', 'Не удалось загрузить достижения')
  }
}
onMounted(load)

function toggle(id) {
  const next = new Set(picked.value)
  next.has(id) ? next.delete(id) : next.add(id)
  picked.value = next
}

async function save() {
  saving.value = true
  error.value = ''
  try {
    await meApi.setShowcase([...picked.value])
    mode.value = 'all'
    await load()
  } catch {
    // Сбой ПОКАЗЫВАЕМ, а не глотаем: человек уже отметил галочки и уверен, что сохранил.
    error.value = locale.t('achievements.saveFailed', 'Не удалось сохранить. Попробуйте ещё раз.')
  } finally {
    saving.value = false
  }
}

function fmt(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  return isNaN(d) ? '' : d.toLocaleDateString()
}
</script>

<template>
  <div class="fixed inset-0 z-50 grid place-items-center p-3 sm:p-4" style="background: var(--gb-overlay)"
       @click.self="emit('close')">
    <div class="flex max-h-[90vh] w-full max-w-3xl flex-col overflow-hidden rounded-xl border border-border2 bg-card shadow-card">

      <div class="flex items-center justify-between gap-3 border-b border-border px-5 py-3.5">
        <h2 class="flex items-center gap-2 font-title text-lg font-bold text-text">
          <Trophy class="size-5 text-accent" />
          {{ mode === 'all'
             ? locale.t('achievements.title', 'Достижения')
             : locale.t('achievements.showcaseTitle', 'Отображаемые в профиле') }}
        </h2>
        <button type="button" @click="emit('close')" :aria-label="locale.t('common.close', 'Закрыть')"
                class="grid size-8 shrink-0 place-items-center rounded-lg text-text3 hover:bg-bg2 hover:text-text">
          <X class="size-5" />
        </button>
      </div>

      <p class="border-b border-border px-5 py-2 text-xs text-text3">
        <template v-if="mode === 'all'">
          {{ locale.t('achievements.progress', 'Открыто') }}: {{ openedCount }} / {{ ACHIEVEMENTS.length }}
        </template>
        <template v-else>
          {{ locale.t('achievements.showcaseHint', 'Отмеченные увидят другие в вашем профиле') }}
        </template>
      </p>

      <div class="min-h-0 flex-1 overflow-y-auto p-4">
        <!-- ВСЕ: закрытые — чёрные, без названия и описания -->
        <div v-if="mode === 'all'" class="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
          <div v-for="a in ACHIEVEMENTS" :key="a.id"
               class="flex items-start gap-3 rounded-lg border p-3"
               :class="isOpen(a.id)
                 ? 'border-border2 bg-card2'
                 : 'border-border2 bg-[#05070a] text-text3'">
            <span class="grid size-10 shrink-0 place-items-center rounded-lg text-xl"
                  :class="isOpen(a.id) ? 'bg-accent-glow' : 'bg-black/60'">
              <template v-if="isOpen(a.id)">{{ a.icon }}</template>
              <Lock v-else class="size-4 text-text3/50" />
            </span>
            <div class="min-w-0">
              <p class="truncate text-sm font-semibold"
                 :class="isOpen(a.id) ? 'text-text' : 'text-text3/60'">
                {{ isOpen(a.id) ? a.title : '???' }}
              </p>
              <p v-if="isOpen(a.id)" class="mt-0.5 text-xs leading-snug text-text2">{{ a.desc }}</p>
              <p v-if="isOpen(a.id)" class="mt-1 text-[11px]" :style="{ color: RARITY[a.rarity].color }">
                {{ locale.t(`achievements.rarity.${a.rarity}`, RARITY[a.rarity].label) }}
                <span v-if="unlocked[a.id]?.unlocked_at" class="text-text3">
                  · {{ fmt(unlocked[a.id].unlocked_at) }}</span>
              </p>
            </div>
          </div>
        </div>

        <!-- ВИТРИНА: только открытые, галочками -->
        <div v-else>
          <div v-if="!mine.length" class="py-10 text-center text-sm text-text3">
            {{ locale.t('achievements.noneYet', 'Пока нечего показывать — ни одной ачивки не открыто') }}
          </div>
          <div v-else class="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
            <button v-for="a in mine" :key="a.id" type="button" @click="toggle(a.id)"
                    :aria-pressed="picked.has(a.id)"
                    class="flex items-center gap-3 rounded-lg border p-3 text-left transition-colors"
                    :class="picked.has(a.id) ? 'border-accent bg-accent-glow' : 'border-border2 bg-card2 hover:border-border'">
              <span class="grid size-9 shrink-0 place-items-center rounded-lg bg-card text-lg">{{ a.icon }}</span>
              <span class="min-w-0 flex-1">
                <span class="block truncate text-sm font-semibold text-text">{{ a.title }}</span>
                <span class="block text-[11px]" :style="{ color: RARITY[a.rarity].color }">
                  {{ locale.t(`achievements.rarity.${a.rarity}`, RARITY[a.rarity].label) }}</span>
              </span>
              <span class="grid size-5 shrink-0 place-items-center rounded border"
                    :class="picked.has(a.id) ? 'border-accent bg-accent text-white' : 'border-border2'">
                <Check v-if="picked.has(a.id)" class="size-3.5" />
              </span>
            </button>
          </div>
        </div>

        <p v-if="error" class="mt-3 text-sm text-red">{{ error }}</p>
      </div>

      <div class="flex flex-wrap items-center justify-between gap-2 border-t border-border px-5 py-3">
        <template v-if="mode === 'all'">
          <button type="button" @click="mode = 'showcase'"
                  class="rounded-lg border border-border2 px-3.5 py-2 text-sm font-medium text-text2 hover:border-accent hover:text-text">
            {{ locale.t('achievements.showcaseTitle', 'Отображаемые в профиле') }}
          </button>
          <button type="button" @click="emit('close')"
                  class="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white hover:brightness-110">
            {{ locale.t('common.close', 'Закрыть') }}
          </button>
        </template>
        <template v-else>
          <button type="button" @click="mode = 'all'"
                  class="rounded-lg border border-border2 px-3.5 py-2 text-sm font-medium text-text2 hover:border-accent hover:text-text">
            {{ locale.t('common.back', 'Назад') }}
          </button>
          <button type="button" @click="save" :disabled="saving"
                  class="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-60">
            {{ saving ? locale.t('common.saving', 'Сохраняем…') : locale.t('common.save', 'Сохранить') }}
          </button>
        </template>
      </div>
    </div>
  </div>
</template>
