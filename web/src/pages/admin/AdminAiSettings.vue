<script setup>
// AdminAiSettings — «Настройки ИИ» (порт ui/admin_dashboard._build_api). Админ выбирает
// провайдера «Вектора» (Оффлайн/GigaChat/Ollama) и вводит ключ GigaChat. Хранится в той
// же строке config, что и на десктопе → синхронизируется в обе стороны (ключ, заданный
// на ПК, приезжает на веб и наоборот).
import { ref, onMounted } from 'vue'
import { Bot, Eye, EyeOff, Check, CircleAlert, CircleCheck } from '@lucide/vue'
import { adminApi } from '@/api/endpoints'
import Card from '@/components/ui/Card.vue'
import AppButton from '@/components/ui/AppButton.vue'

const cfg = ref({
  vector_llm: 'offline',
  gigachat_credentials: '',
  gigachat_scope: 'GIGACHAT_API_B2B',
  gigachat_model: 'GigaChat',
  local_model: 'qwen2.5:3b',
  tts_enabled: true,
  stt_mode: 'auto',
  stt_installed: false,     //только чтение: что реально стоит на хосте
})
const showKey = ref(false)
const loading = ref(false)
const saved = ref(false)
const testMsg = ref('')
const testOk = ref(null)

const PROVIDERS = [
  { id: 'offline', name: 'Оффлайн-шаблоны', hint: 'Без внешней LLM — ответы строго по фактам. Работает всегда.' },
  { id: 'gigachat', name: 'GigaChat (Сбер, РФ)', hint: 'Тёплая переформулировка ответов. Нужен ключ авторизации. Сервер в РФ — GigaChat работает.' },
  { id: 'local', name: 'Ollama (локально)', hint: 'Своя модель на сервере, если поднят Ollama. Данные никуда не уходят.' },
]
const SCOPES = ['GIGACHAT_API_PERS', 'GIGACHAT_API_B2B', 'GIGACHAT_API_CORP']

// Голосовой ввод: чем распознавать речь. Три режима — см. `_STT_MODES` на сервере.
const STT_MODES = [
  { id: 'auto', name: 'Автоматически (рекомендуется)',
    hint: 'Whisper — там, где он установлен; на остальных машинах распознаёт браузер. ' +
          'Никого не заставляет ничего скачивать.' },
  { id: 'server', name: 'OpenAI Whisper на сервере — для всех',
    hint: 'Звук распознаёт только наш сервер, наружу не уходит. Требует машину с ' +
          'видеокартой: на нынешнем хостинге движок не поместится.' },
  { id: 'browser', name: 'Обычный голосовой ввод (браузер)',
    hint: 'Распознаёт браузер (Chrome/Edge) силами Google. Нагрузки на сервер нет, ' +
          'но звук уходит третьей стороне.' },
]
const inputCls =
  'h-11 w-full rounded-sm border border-border2 bg-card2 px-3.5 text-text outline-none transition-colors focus:border-accent focus:bg-card'

onMounted(async () => {
  try { cfg.value = { ...cfg.value, ...(await adminApi.aiConfig()).data } } catch { /* нет связи — дефолты */ }
})

async function save() {
  loading.value = true; saved.value = false
  try { await adminApi.aiConfigSave(cfg.value); saved.value = true; setTimeout(() => (saved.value = false), 2500) }
  finally { loading.value = false }
}

async function test() {
  loading.value = true; testMsg.value = ''; testOk.value = null
  try {
    const { data } = await adminApi.aiConfigTest(cfg.value)
    testOk.value = data.ok
    testMsg.value = data.message
  } catch (e) {
    testOk.value = false
    testMsg.value = e.response?.data?.detail || 'Не удалось проверить.'
  } finally { loading.value = false }
}
</script>

<template>
  <div class="max-w-2xl space-y-6">
    <Card title="ИИ-помощник «Вектор»" subtitle="Как Вектор озвучивает ответы. Цифры он всегда берёт из реальных данных — LLM лишь переформулирует.">
      <div class="space-y-2.5">
        <label v-for="p in PROVIDERS" :key="p.id"
               class="flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-colors"
               :class="cfg.vector_llm === p.id ? 'border-accent bg-accent-glow' : 'border-border hover:border-accent'">
          <input type="radio" :value="p.id" v-model="cfg.vector_llm" class="mt-1 accent-[var(--gb-accent)]" />
          <span>
            <span class="flex items-center gap-2 font-semibold text-text"><Bot class="size-4 text-accent" />{{ p.name }}</span>
            <span class="mt-0.5 block text-xs text-text3">{{ p.hint }}</span>
          </span>
        </label>
      </div>
    </Card>

    <!-- Озвучка (TTS): глобальный рубильник. Выключение прячет озвучку у всех
         пользователей. Персональный выбор (вкл/голос) каждый делает в своём профиле. -->
    <Card title="Озвучка ответов (голос Вектора)"
          subtitle="Синтез речи на сервере. Выключите, если сервер перегружен — пользователи не увидят озвучку.">
      <label class="flex cursor-pointer items-center justify-between gap-3">
        <span class="text-sm text-text">Разрешить озвучку на сервере</span>
        <input type="checkbox" v-model="cfg.tts_enabled" class="size-5 accent-[var(--gb-accent)]" />
      </label>
    </Card>

    <!-- Голосовой ввод (STT): чем распознавать речь у всех пользователей. -->
    <Card title="Голосовой ввод (распознавание речи)"
          subtitle="Чем превращать речь в текст. Настройка общая: действует и на сайте, и в программе, и в телефоне.">
      <div class="space-y-2.5">
        <label v-for="m in STT_MODES" :key="m.id"
               class="flex cursor-pointer items-start gap-3 rounded-md border p-3 transition-colors"
               :class="cfg.stt_mode === m.id ? 'border-accent bg-accent-glow' : 'border-border hover:border-accent'">
          <input type="radio" :value="m.id" v-model="cfg.stt_mode" class="mt-1 accent-[var(--gb-accent)]" />
          <span>
            <span class="block text-sm font-semibold text-text">{{ m.name }}</span>
            <span class="mt-0.5 block text-xs text-text3">{{ m.hint }}</span>
          </span>
        </label>
      </div>

      <!-- Честное состояние хоста. Без этой строки админ включил бы «Whisper для всех»
           на машине, где движка нет, и голосовой ввод пропал бы у всего колледжа. -->
      <div class="mt-3 rounded-md border px-3 py-2.5 text-xs"
           :class="cfg.stt_installed ? 'border-accent/40 text-text2' : 'border-orange/40 text-text2'">
        <template v-if="cfg.stt_installed">
          ✅ Whisper установлен на этом сервере — режим «для всех» будет работать.
        </template>
        <template v-else>
          ⚠️ Whisper на этом сервере <b>не установлен</b>. Режим «для всех» станет доступен,
          когда журнал переедет на машину колледжа с видеокартой — до тех пор он честно
          покажет пользователям, что распознавание недоступно, а не подменит его тихо
          браузерным.
        </template>
      </div>
    </Card>

    <!-- GigaChat: ключ + скоуп -->
    <Card v-if="cfg.vector_llm === 'gigachat'" title="GigaChat" subtitle="Ключ авторизации и scope из личного кабинета GigaChat (Сбер).">
      <div class="space-y-4">
        <div>
          <label class="mb-1.5 block text-xs font-medium text-text3">КЛЮЧ АВТОРИЗАЦИИ (Credentials)</label>
          <div class="relative">
            <input v-model="cfg.gigachat_credentials" :type="showKey ? 'text' : 'password'"
                   :class="inputCls + ' pr-11'" placeholder="вставьте ключ авторизации GigaChat" autocomplete="off" />
            <button type="button" class="absolute right-2 top-1/2 grid size-8 -translate-y-1/2 place-items-center rounded-sm text-text2 hover:text-accent"
                    @click="showKey = !showKey"><EyeOff v-if="showKey" class="size-4" /><Eye v-else class="size-4" /></button>
          </div>
        </div>
        <div>
          <label class="mb-1.5 block text-xs font-medium text-text3">SCOPE</label>
          <select v-model="cfg.gigachat_scope" :class="inputCls">
            <option v-for="s in SCOPES" :key="s" :value="s">{{ s }}</option>
          </select>
        </div>
      </div>
    </Card>

    <!-- Ollama: модель -->
    <Card v-if="cfg.vector_llm === 'local'" title="Ollama" subtitle="Имя локальной модели (должен быть запущен Ollama на сервере).">
      <label class="mb-1.5 block text-xs font-medium text-text3">МОДЕЛЬ</label>
      <input v-model="cfg.local_model" :class="inputCls" placeholder="напр. qwen2.5:3b" />
    </Card>

    <div class="flex flex-wrap items-center gap-3">
      <AppButton variant="green" :disabled="loading" @click="save">
        <Check class="mr-2 inline size-4" />{{ loading ? 'Сохраняю…' : 'Сохранить' }}
      </AppButton>
      <AppButton v-if="cfg.vector_llm !== 'offline'" variant="ghost" :disabled="loading" @click="test">
        Проверить связь
      </AppButton>
      <span v-if="saved" class="text-sm font-medium text-green">Сохранено — синхронизируется на все ПК.</span>
    </div>

    <p v-if="testMsg" class="flex items-start gap-2 rounded-lg border px-3 py-2.5 text-sm"
       :class="testOk ? 'border-green/40 bg-green/10 text-text' : 'border-red/40 bg-red/10 text-red'">
      <component :is="testOk ? CircleCheck : CircleAlert" class="mt-0.5 size-4 shrink-0" :class="testOk ? 'text-green' : 'text-red'" />
      <span>{{ testOk ? 'Связь есть. Пример ответа: ' : '' }}{{ testMsg }}</span>
    </p>
  </div>
</template>
