<script setup>
// QuizResult — итоги прохождения викторины.
//
// Показывается ПОСЛЕ отправки. Разбор с правильными ответами приходит с сервера, и это
// безопасно ровно потому, что пересдать нельзя: результат считается один раз, повторная
// отправка возвращает сохранённый (см. `submit_quiz` про оракул). Развяжи ту
// идемпотентность — и этот экран мгновенно станет способом узнать ключ и пройти заново.
import { computed } from 'vue'
import { Check, X } from '@lucide/vue'
import { useLocaleStore } from '@/stores/locale'
import { useAuthStore } from '@/stores/auth'

const props = defineProps({ result: { type: Object, required: true } })
const locale = useLocaleStore()
const auth = useAuthStore()

const who = computed(() => auth.user?.full_name || auth.user?.name || auth.user?.login || '')

const percent = computed(() => {
  const total = Number(props.result.total_count || 0)
  if (!total) return 0
  return Math.round((Number(props.result.correct_count || 0) / total) * 100)
})

// Цвет кольца плавно течёт от красного к зелёному. Считаем по тону HSL (0° — красный,
// 130° — зелёный): промежуточные проценты дают жёлтый и салатовый сами собой, без
// таблицы порогов, а «плавно перетекать» из требования выполняется буквально.
const ringColor = computed(() => `hsl(${Math.round((percent.value / 100) * 130)} 72% 45%)`)

// conic-gradient — тот же приём, что у кольца среднего балла на вкладке «ИИ Помощник»:
// графических библиотек в проекте нет и заводить их ради одного кольца незачем.
const ringStyle = computed(() => ({
  background: `conic-gradient(${ringColor.value} ${percent.value * 3.6}deg, var(--gb-bg2) 0deg)`,
}))

const review = computed(() => props.result.review || [])
const maxScore = computed(() => Number(props.result.max_score || 0))
</script>

<template>
  <div class="flex flex-col items-center gap-5 py-6">
    <h3 v-if="who" class="text-center text-lg font-semibold text-text">{{ who }}</h3>

    <!-- Кольцо: доля верных ответов цветом и числом сразу. Число обязательно — по одному
         цвету процент не прочитать, да и при дальтонизме кольцо перестаёт что-либо
         значить (то же правило, что у статусных цветов в остальном продукте). -->
    <div class="relative grid size-40 place-items-center rounded-full" :style="ringStyle">
      <span class="gb-ring-shine pointer-events-none absolute inset-0 rounded-full" />
      <div class="grid size-32 place-items-center rounded-full bg-card">
        <span class="text-4xl font-bold tabular-nums" :style="{ color: ringColor }">{{ percent }}%</span>
      </div>
    </div>

    <div class="flex flex-wrap justify-center gap-x-8 gap-y-2 text-center">
      <div>
        <div class="text-xl font-bold tabular-nums text-text">
          {{ result.correct_count }} / {{ result.total_count }}
        </div>
        <div class="text-tiny text-text3">{{ locale.t('quizResult.correct', 'верных заданий') }}</div>
      </div>
      <div>
        <div class="text-xl font-bold tabular-nums text-text">
          {{ result.score }}<span v-if="maxScore" class="text-text3"> / {{ maxScore }}</span>
        </div>
        <div class="text-tiny text-text3">{{ locale.t('quizResult.score', 'баллов') }}</div>
      </div>
    </div>

    <!-- Разбор: что спрашивали, что выбрал человек, что было верно. Ради него экран и
         существует — один процент не учит ничему. -->
    <div v-if="review.length" class="flex w-full max-w-2xl flex-col gap-2">
      <div v-for="(q, qi) in review" :key="q.id"
           class="rounded-xl border border-border2 bg-card p-3">
        <div class="mb-2 flex items-start gap-2">
          <component :is="q.correct ? Check : X" class="mt-0.5 size-4 shrink-0"
                     :class="q.correct ? 'text-accent' : 'text-red'" />
          <span class="min-w-0 flex-1 text-sm font-semibold text-text">
            {{ qi + 1 }}. {{ q.text }}
          </span>
          <span class="shrink-0 text-tiny tabular-nums text-text3">{{ q.earned }} / {{ q.points }}</span>
        </div>
        <div class="flex flex-col gap-1 pl-6">
          <div v-for="o in q.options" :key="o.id"
               class="flex min-w-0 items-center gap-2 rounded-lg px-2 py-1 text-sm"
               :class="o.is_correct ? 'bg-accent/10 text-text'
                       : o.chosen ? 'bg-red/10 text-text' : 'text-text3'">
            <span class="min-w-0 flex-1 break-words">{{ o.text }}</span>
            <!-- Две отметки РАЗНЫЕ по смыслу: «верный» — про задание, «ваш» — про
                 человека. Одной галочкой их не различить, а именно это и разбирают. -->
            <span v-if="o.is_correct" class="shrink-0 text-tiny font-semibold text-accent">
              {{ locale.t('quizResult.right', 'верный') }}
            </span>
            <span v-if="o.chosen" class="shrink-0 text-tiny font-semibold"
                  :class="o.is_correct ? 'text-accent' : 'text-red'">
              {{ locale.t('quizResult.yours', 'ваш') }}
            </span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* Белый отблеск, медленно обходящий кольцо. Держится на маске, поэтому светится ровно
   ободок, а не заливка. Движение медленное намеренно: быстрый блик на экране с
   результатом отвлекает от самого результата. */
.gb-ring-shine {
  background: conic-gradient(transparent 0deg, rgba(255, 255, 255, .55) 30deg, transparent 70deg);
  -webkit-mask: radial-gradient(circle, transparent 62%, #000 63%);
  mask: radial-gradient(circle, transparent 62%, #000 63%);
  animation: gb-ring-shine 3.2s linear infinite;
}
@keyframes gb-ring-shine {
  to { transform: rotate(1turn); }
}
@media (prefers-reduced-motion: reduce) {
  .gb-ring-shine { animation: none; opacity: .25; }
}
</style>
