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
  <!-- ⚠️ `grid-cols-1` и `min-w-0` — против переполнения экрана на телефоне. Текст
       карточки собирает СЕРВЕР (dropout_risk.py, insights) и перечисляет в нём реальные
       названия предметов — то есть длина здесь не под нашим контролем и в принципе
       неограничена. Без явной колонки сетка заводит неявную дорожку `auto`, которая
       растягивается под самый широкий неразрывный кусок и утаскивает за собой ВСЮ
       страницу; `break-words` дополнительно разрешает разорвать сам такой кусок, если
       он окажется одним длинным словом (ссылка, слитный перечень). -->
  <div v-if="cards.length" class="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
    <div v-for="(c, i) in cards" :key="i"
         class="min-w-0 break-words rounded-lg border p-3.5" :class="STYLES[c.severity] || STYLES.info">
      <p class="flex items-start gap-2 text-sm font-bold" :class="TITLE[c.severity] || TITLE.info">
        <span class="shrink-0">{{ c.icon }}</span>
        <!-- Заголовок отдельным span'ом: голый текст рядом с иконкой стал бы анонимным
             элементом flex, которому нельзя задать min-w-0, и он распирал бы карточку. -->
        <span class="min-w-0">{{ c.title }}</span>
      </p>
      <p class="mt-1 text-sm text-text">{{ c.detail }}</p>
      <p v-if="c.action" class="mt-1.5 text-xs font-medium text-text3">→ {{ c.action }}</p>
    </div>
  </div>
</template>
