<script setup>
// GroupTag — учебная группа студента ТЕГОМ рядом с именем (05.10.2026, просьба Ярослава:
// «сделай справа подпись у студентов их группу, по типу тега»).
//
// Зачем отдельный компонент, а не строка в каждом списке. Группа у студента — то, по чему
// его отличают: однофамильцев в колледже хватает, а «Иванов Пётр» из К74/1 и из К64/2 —
// разные люди. До этого группа показывалась где как: в каталоге строкой «Группа К74/1»
// под именем, в участниках беседы — там же, но только если у человека нет статуса (статус
// её вытеснял), в личном чате и в ленте — нигде. Один компонент — один вид и одно правило
// «показывать ли»: пустая группа не рисует ничего.
//
// ⚠️ Тег НЕ сжимается (`shrink-0`): в строке со сжимаемым именем обрезаться должно длинное
// ФИО, а не короткое «К74/1» — иначе от тега остаётся «К7…», и он перестаёт что-либо
// сообщать.
import { useLocaleStore } from '@/stores/locale'

defineProps({
  group: { type: String, default: '' },
  // На цветной шапке чата (её красит собеседник) тег рисуется светлым по тёмному.
  onTint: { type: Boolean, default: false },
})
const locale = useLocaleStore()
</script>

<template>
  <span v-if="group"
        class="inline-flex shrink-0 items-center whitespace-nowrap rounded-full border px-1.5 py-px align-middle text-[10.5px] font-semibold leading-tight tracking-normal"
        :class="onTint ? 'border-white/40 bg-white/15 text-white' : 'border-border2 bg-bg2 text-text2'"
        :title="`${locale.t('messenger.groupLabel', 'Группа')} ${group}`">{{ group }}</span>
</template>
