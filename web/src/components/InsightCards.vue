<script setup>
// InsightCards — проактивные карточки Вектора (порт vector/insights.py + widget):
// сервер отдаёт готовые факты-карточки {severity, icon, title, detail, action},
// здесь только отрисовка severity-цветом. info — акцент, warn — оранж, alert — красный.
defineProps({ cards: { type: Array, default: () => [] } })

const STYLES = {
  info: 'border-accent/25 bg-accent-glow/60',
  warn: 'border-orange/30 bg-orange/10',
  alert: 'border-red/30 bg-red/10',
}
const TITLE = { info: 'text-accent', warn: 'text-orange', alert: 'text-red' }
</script>

<template>
  <div v-if="cards.length" class="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
    <div v-for="(c, i) in cards" :key="i"
         class="rounded-lg border p-3.5" :class="STYLES[c.severity] || STYLES.info">
      <p class="flex items-center gap-2 text-sm font-bold" :class="TITLE[c.severity] || TITLE.info">
        <span>{{ c.icon }}</span>{{ c.title }}
      </p>
      <p class="mt-1 text-sm text-text">{{ c.detail }}</p>
      <p v-if="c.action" class="mt-1.5 text-xs font-medium text-text3">→ {{ c.action }}</p>
    </div>
  </div>
</template>
