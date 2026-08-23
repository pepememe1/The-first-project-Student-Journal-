<script setup>
// ProfileEggs — две пасхалки страницы «Профиль»: штамп Papers Please и точка
// сохранения Undertale.
//
// ⚠️ ШТАМПА Papers Please здесь БОЛЬШЕ НЕТ — он переехал в `StampEgg.vue` внутрь самой
// карточки профиля. Причина: он должен появляться на ЛЮБОМ профиле, включая чужой в
// модальном окне, а этот компонент стоит только на своей странице. Заодно там же
// починена реактивность (см. его докстринг). Двух копий штампа быть не должно: это
// читалось бы как две разные пасхалки.
//
// ━━ ТОЧКА СОХРАНЕНИЯ ━━
// Подменяет слово «Сохранить» звездой (сама подмена — в Profile.vue, здесь только
// сценарий). Реплики листаются кликом по окну, как у дерева Делтарун. После
// «Сохранить» жёлтое окно висит, пока по нему не кликнут: гасить его по таймеру нельзя,
// человек в этот момент читает.
//
// ⚠️ Настоящее сохранение профиля НЕ подменяется и не откладывается: кнопка в жёлтом
// окне зовёт тот же `saveAll()`, что и обычная. Пасхалка, из-за которой правки не
// сохранились, перестаёт быть шуткой.
import { ref, computed, onBeforeUnmount } from 'vue'
import { useEasterStore } from '@/stores/easterEggs'
import { mumble } from '@/utils/mumble'

const props = defineProps({
  // Имя и «уровень» в файле сохранения — берём настоящие, иначе окно выглядит чужим.
  name: { type: String, default: '' },
  level: { type: [Number, String], default: 0 },
})
const emit = defineEmits(['save'])

const easter = useEasterStore()

// ── Undertale ──────────────────────────────────────────────────────────────
const LINES = [
  '* (Осознание того, что ваш профиль теперь выглядит лучше, наполняет вас РЕШИМОСТЬЮ.)',
  '* (Здоровье полностью восстановлено.)',
]
const box = ref('')        // '' | 'lines' | 'file' | 'saved'
const dlg = ref('')
const clock = ref('')
let busy = false
let timers = []

async function type(text) {
  busy = true
  dlg.value = ''
  for (let i = 1; i <= text.length; i++) {
    dlg.value = text.slice(0, i)
    if (i % 2 === 0 && text[i - 1] !== ' ') mumble()
    await new Promise((r) => setTimeout(r, 26))
  }
  busy = false
}

let step = 0
/** Зовёт Profile.vue по клику на звезду вместо «Сохранить». */
async function start() {
  if (box.value) return
  step = 0
  box.value = 'lines'
  await type(LINES[0])
}
async function advance() {
  if (busy) return
  if (box.value === 'saved') { close(); return }
  if (box.value !== 'lines') return
  step += 1
  if (step < LINES.length) { await type(LINES[step]); return }
  box.value = 'file'
}
function close() {
  box.value = ''
  easter.closeInPage('undertale_save')
}
function cancel() { close() }
function doSave() {
  try { new Audio('/easter/snd/savepoint.mp3').play().catch(() => {}) } catch { /* без звука */ }
  //Улан-Удэ, UTC+8: часы в файле сохранения местные, а не браузерные — человек сверяет
  //их с настенными, а не с настройками своей системы.
  const t = new Date(Date.now() + (8 * 60 + new Date().getTimezoneOffset()) * 60000)
  clock.value = `${String(t.getHours()).padStart(2, '0')}:${String(t.getMinutes()).padStart(2, '0')}`
  box.value = 'saved'
  emit('save')
  timers.push(setTimeout(() => easter.claim('undertale_save'), 1200))
}

const lvLabel = computed(() => `LV ${props.level || 0}`)
const whoLabel = computed(() => (props.name || 'ИГРОК').toUpperCase())

onBeforeUnmount(() => {
  timers.forEach(clearTimeout)
  // Та же уборка, что и в журнале: звезду рисует только страница профиля.
  if (easter.inPage.undertale_save) easter.closeInPage('undertale_save')
})
defineExpose({ start })
</script>

<template>
  <div class="pointer-events-none absolute inset-0 z-30 overflow-hidden">
    <Teleport to="body">
    <!-- 🔥 TELEPORT ОБЯЗАТЕЛЕН, А НЕ УКРАШЕНИЕ (23.08.2026).
       Слой пасхалок лежит внутри страницы, у которой есть `position: relative` и
       `overflow: hidden`. Для потомка это значит две вещи разом: `fixed` считается от
       КОНТЕЙНЕРА, а не от окна, и всё, что вылезло за его край, обрезается.
       Наружу это выходило так: окно Undertale прилипало к низу ДЛИННОЙ СТРАНИЦЫ (то
       есть его не было видно, пока не домотаешь до подвала), а голос Disco Elysium не
       появлялся вовсе — подтверждение при уходе честно говорило «на экране пасхалка»,
       а на экране было пусто.
       ⚠️ Любой новый плавающий слой пасхалки — только через <Teleport to="body">. -->
    <div v-if="box" class="gb-utbox pointer-events-auto fixed inset-x-4 bottom-4 z-[92] mx-auto max-w-3xl
                           cursor-pointer border-[3px] border-white bg-black px-5 py-4"
         role="dialog" @click="advance">
      <template v-if="box === 'lines'">
        <span class="gb-px text-[12px] leading-relaxed text-white">{{ dlg }}</span>
        <span class="gb-hint">▼ клик</span>
      </template>

      <template v-else-if="box === 'file'">
        <div class="gb-px grid grid-cols-[1fr_auto_1fr] gap-2 text-[11px] leading-[1.8] text-white">
          <span>{{ whoLabel }}</span><span>{{ lvLabel }}</span><span class="text-right">0:00</span>
        </div>
        <div class="gb-px mb-3.5 mt-1.5 text-[11px]" style="color:#c9c9c9">Профиль</div>
        <div class="flex items-center gap-6">
          <button type="button" class="gb-px flex items-center gap-2 border-0 bg-transparent text-[11px] text-white"
                  @click.stop="doSave"><span style="color:#ff2d2d;font-size:13px">❤</span>Сохранить</button>
          <button type="button" class="gb-px border-0 bg-transparent text-[11px] text-white"
                  @click.stop="cancel">Отмена</button>
        </div>
      </template>

      <template v-else>
        <div class="gb-px grid grid-cols-[1fr_auto_1fr] gap-2 text-[11px] leading-[1.8]" style="color:#ffef4a">
          <span>{{ whoLabel }}</span><span>{{ lvLabel }}</span><span class="text-right">{{ clock }}</span>
        </div>
        <div class="gb-px mt-1 text-[11px]" style="color:#ffef4a">Профиль</div>
        <div class="gb-px mt-4 text-center text-[11px]" style="color:#ffef4a">Файл сохранён.</div>
        <span class="gb-hint">▼ клик</span>
      </template>
    </div>
    </Teleport>
  </div>
</template>

<style scoped>
.gb-px { font-family: 'Press Start 2P', monospace; letter-spacing: .02em }
.gb-hint {
  position: absolute; right: 12px; bottom: 8px;
  font-family: 'Press Start 2P', monospace; font-size: 8px; color: #8a8a8a;
  animation: gb-blink 1s steps(2) infinite;
}
@keyframes gb-blink { 50% { opacity: .15 } }
@media (prefers-reduced-motion: reduce) { .gb-hint { animation: none } }
</style>
