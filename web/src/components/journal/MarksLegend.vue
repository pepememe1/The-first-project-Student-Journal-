<script setup>
// MarksLegend — что означают буквы в колонке «Оценка».
//
// Зачем (13.10.2026, живой обход стенда). У преподавателя под журналом есть легенда, а у
// студента и родителя её не было: «Н» стояла в колонке «Оценка» без единого слова, и
// родитель не мог понять, это оценка или пропуск. Хуже того, у домашней работы «Н»
// значит «не сдано», а у занятия — «не был», и Вектор называл её то так, то так.
//
// Один компонент на оба журнала (студента и родителя): они обязаны говорить одно и то же,
// а две копии текста расходятся на первой же правке — как уже расходилась вёрстка занятий
// (см. SubjectLessons.vue).
import { useLocaleStore } from '@/stores/locale'

const locale = useLocaleStore()
</script>

<template>
  <div class="rounded-lg border border-border bg-card px-3 py-2.5 text-xs leading-relaxed text-text2">
    <p class="mb-1 font-semibold text-text">{{ locale.t('marksLegend.title', 'Что означают отметки') }}</p>
    <ul class="grid grid-cols-1 gap-x-6 gap-y-0.5 sm:grid-cols-2">
      <li><b class="text-text">2–5</b> — {{ locale.t('marksLegend.grade', 'оценка') }}</li>
      <li><b class="text-accent">✓</b> — {{ locale.t('marksLegend.present', 'был(а) на занятии') }}</li>
      <li><b class="text-red">Н</b> — {{ locale.t('marksLegend.absent', 'не был(а) на занятии; у домашней работы — не сдано') }}</li>
      <li><b class="text-text">Б</b> — {{ locale.t('marksLegend.sick', 'пропуск по болезни') }}</li>
      <li><b class="text-text">О</b> — {{ locale.t('marksLegend.late', 'опоздал(а)') }}</li>
      <li>{{ locale.t('marksLegend.hours', 'Одно занятие (пара) — 2 академических часа.') }}</li>
    </ul>
  </div>
</template>
