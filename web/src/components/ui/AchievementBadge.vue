<script setup>
// AchievementBadge — значок ачивки: сота (наш символ) в цвете редкости и знак внутри.
// Раньше здесь стояли эмодзи, и одна и та же ачивка выглядела по-разному на Windows,
// Android и в браузере. Знак берётся по имени из справочника (config/achievements.js).
import { computed } from 'vue'
import {
  BookMarked, CakeSlice, CassetteTape, CircleDot, Dices, DoorOpen, Egg, Eye, Flame,
  Guitar, Mic, Moon, Skull, Star, Trophy,
} from '@lucide/vue'
import { RARITY } from '@/config/achievements'

const props = defineProps({
  icon: { type: String, required: true },
  rarity: { type: String, default: 'common' },
  size: { type: Number, default: 40 },
})

const GLYPHS = {
  egg: Egg, trophy: Trophy, dice: Dices, eye: Eye, moon: Moon, cake: CakeSlice,
  guitar: Guitar, flame: Flame, door: DoorOpen, cassette: CassetteTape, book: BookMarked,
  star: Star, mic: Mic, ring: CircleDot, skull: Skull,
}
const glyph = computed(() => GLYPHS[props.icon] || Star)
const color = computed(() => RARITY[props.rarity]?.color || 'var(--gb-accent)')
</script>

<template>
  <svg :width="size" :height="size" viewBox="0 0 40 40" aria-hidden="true" focusable="false"
       class="shrink-0">
    <path d="M20 2.5 35.2 11.25v17.5L20 37.5 4.8 28.75v-17.5Z" :fill="color" fill-opacity="0.16"
          :stroke="color" stroke-width="1.6" stroke-linejoin="round" />
    <component :is="glyph" x="10" y="10" :size="20" :color="color" :stroke-width="2" />
  </svg>
</template>
