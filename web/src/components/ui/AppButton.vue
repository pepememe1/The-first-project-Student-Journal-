<script setup>
// AppButton — «дорогие» кнопки (порт BTN из styles.py). Варианты: green/ghost/red/blue/back.
import { computed } from 'vue'

const props = defineProps({
  variant: { type: String, default: 'green' }, // green | ghost | red | blue | back
  size: { type: String, default: 'md' }, // md | sm
  type: { type: String, default: 'button' },
  disabled: { type: Boolean, default: false },
})

const VARIANTS = {
  green: 'bg-accent text-white border border-transparent hover:bg-accent2',
  ghost: 'bg-card text-text border border-border2 hover:bg-accent-glow hover:text-accent hover:border-accent',
  red: 'bg-transparent text-red border border-red hover:bg-red hover:text-white',
  blue: 'bg-transparent text-blue border border-blue hover:bg-blue hover:text-white',
  back: 'bg-transparent text-text3 border border-border2 hover:text-accent hover:bg-accent-glow hover:border-accent',
}

const sizeCls = computed(() => (props.size === 'sm' ? 'h-9 px-3.5 text-xs' : 'h-11 px-5 text-sm'))
// transition (а не transition-colors) — чтобы вместе с цветом плавно ехал и transform
// «вдавливания». active:scale-[0.97] — отклик на нажатие (apple-design §1); дублирует
// глобальное правило button:active из style.css, но стоит здесь явно как эталон контрола.
const cls = computed(
  () =>
    `inline-flex items-center justify-center gap-2 rounded-sm font-semibold transition active:scale-[0.97] ` +
    `disabled:opacity-50 disabled:pointer-events-none ${sizeCls.value} ${VARIANTS[props.variant] || VARIANTS.green}`,
)
</script>

<template>
  <button :type="type" :disabled="disabled" :class="cls">
    <slot />
  </button>
</template>
