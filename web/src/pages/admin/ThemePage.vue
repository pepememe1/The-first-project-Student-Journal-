<script setup>
// ThemePage — «Оформление» (порт ui/theme_ui.ThemeCustomizer). Полностью рабочая:
// 16 пресетов + кастомный цвет + светлый/тёмный режим + расписание тёмной темы.
// Выбор применяется мгновенно и роумится через /me/prefs (см. theme-store).
import { computed } from 'vue'
import { Check } from '@lucide/vue'
import { useThemeStore } from '@/stores/theme'
import { PRESETS, swatchColors } from '@/theme/palette'
import Card from '@/components/ui/Card.vue'
import AppButton from '@/components/ui/AppButton.vue'
import { useLocaleStore } from '@/stores/locale'

const theme = useThemeStore()
const locale = useLocaleStore()

const currentId = computed(() => theme.spec.id)
const customAccent = computed({
  get: () => (theme.spec.id === 'custom' ? theme.spec.accent || '#147C8B' : '#147C8B'),
  set: (v) => theme.setCustom(v),
})
const schedule = computed(() => theme.spec.schedule || { enabled: false, start: '18:00', end: '08:00' })

function swatch(id) {
  const [accent, accent2, surface] = swatchColors({ ...theme.spec, id })
  return { accent, accent2, surface }
}
// Трёхцветный круг как в десктопе (_Swatch): акцент — верхняя половина, вторичный —
// нижний-левый сектор, поверхность режима — нижний-правый.
function swatchStyle(id) {
  const s = swatch(id)
  return {
    background: `conic-gradient(${s.accent} 0deg 90deg, ${s.surface} 90deg 180deg, `
              + `${s.accent2} 180deg 270deg, ${s.accent} 270deg 360deg)`,
  }
}
</script>

<template>
  <div class="space-y-6">
    <Card :title="locale.t('themePage.palette', 'Палитра')" :subtitle="locale.t('themePage.paletteHint', 'Фирменная тема ВСГУТУ или один из готовых наборов')">
      <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4">
        <button
          v-for="p in PRESETS"
          :key="p.id"
          class="group relative flex items-center gap-3 rounded-md border p-3 text-left transition-colors"
          :class="currentId === p.id ? 'border-accent bg-accent-glow' : 'border-border hover:border-accent'"
          @click="theme.setPreset(p.id)"
        >
          <span class="relative size-8 shrink-0 rounded-full border border-black/10" :style="swatchStyle(p.id)">
            <span v-if="currentId === p.id"
                  class="absolute -right-1 -top-1 grid size-4 place-items-center rounded-full bg-accent text-white ring-2 ring-card">
              <Check class="size-2.5" />
            </span>
          </span>
          <span class="truncate text-sm font-medium text-text">{{ locale.t(`theme.preset.${p.id}`, p.name) }}</span>
        </button>
      </div>
    </Card>

    <div class="grid gap-6 lg:grid-cols-2">
      <Card :title="locale.t('themePage.customColor', 'Свой цвет')" :subtitle="locale.t('themePage.customColorHint', 'Кастомный акцент палитры')">
        <div class="flex items-center gap-4">
          <input
            v-model="customAccent"
            type="color"
            class="size-14 cursor-pointer rounded-md border border-border bg-card2"
          />
          <div>
            <p class="text-sm font-medium text-text">{{ customAccent }}</p>
            <p class="text-xs text-text3">{{ locale.t('themePage.customColorApplies', 'Применяется сразу ко всему интерфейсу') }}</p>
          </div>
        </div>
      </Card>

      <Card :title="locale.t('themePage.mode', 'Режим')" :subtitle="locale.t('themePage.modeHint', 'Светлая или тёмная тема')">
        <div class="flex gap-2">
          <AppButton :variant="theme.isDark ? 'ghost' : 'green'" @click="theme.setMode('light')">{{ locale.t('themePage.light', 'Светлая') }}</AppButton>
          <AppButton :variant="theme.isDark ? 'green' : 'ghost'" @click="theme.setMode('dark')">{{ locale.t('themePage.dark', 'Тёмная') }}</AppButton>
        </div>

        <div class="mt-5 border-t border-border pt-4">
          <label class="flex items-center gap-3">
            <input
              type="checkbox"
              :checked="schedule.enabled"
              class="size-4 accent-[var(--gb-accent)]"
              @change="theme.setSchedule($event.target.checked, schedule.start, schedule.end)"
            />
            <span class="text-sm text-text">{{ locale.t('themePage.darkSchedule', 'Тёмная тема по расписанию') }}</span>
          </label>
          <div v-if="schedule.enabled" class="mt-3 flex items-center gap-2 text-sm text-text3">
            <span>{{ locale.t('themePage.from', 'с') }}</span>
            <input
              type="time"
              :value="schedule.start"
              class="h-9 rounded-sm border border-border2 bg-card2 px-2 text-text"
              @change="theme.setSchedule(true, $event.target.value, schedule.end)"
            />
            <span>{{ locale.t('themePage.to', 'до') }}</span>
            <input
              type="time"
              :value="schedule.end"
              class="h-9 rounded-sm border border-border2 bg-card2 px-2 text-text"
              @change="theme.setSchedule(true, schedule.start, $event.target.value)"
            />
          </div>
        </div>
      </Card>
    </div>
  </div>
</template>
