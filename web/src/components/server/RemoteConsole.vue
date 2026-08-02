<script setup>
// RemoteConsole — строка команд к выбранному серверу.
//
// ⚠️ ЭТО НЕ ЭМУЛЯТОР ТЕРМИНАЛА, и попытки сделать его таковым надо пресекать. Каждая
// команда — отдельный сеанс ssh, поэтому `cd` не запоминается, `sudo` не спросит пароль
// (BatchMode), а интерактивные программы (top, nano, htop) просто повиснут до предела
// ожидания. Настоящий терминал требует постоянного PTY-соединения — это отдельная
// задача, и притворяться, что он тут есть, хуже, чем честно сказать обратное.
//
// Что здесь ценно вместо этого: журнал выполненного с кодами возврата, готовые команды
// под наши задачи и подтверждение на опасных.
import { ref, computed, nextTick } from 'vue'
import { Play, Terminal, TriangleAlert } from '@lucide/vue'
import { deskServerApi } from '@/api/endpoints'
import AppButton from '@/components/ui/AppButton.vue'
import { useLocaleStore } from '@/stores/locale'

const locale = useLocaleStore()
const props = defineProps({
  serverId: { type: String, required: true },
})

// Готовые команды: ровно те, за которыми на сервер и ходят. Список короткий намеренно —
// длинный превращается в свалку, из которой всё равно копируют одну и ту же строку.
// Сама команда (cmd) — данные для ssh, не текст интерфейса, не переводится.
const PRESETS = computed(() => [
  { label: locale.t('remoteConsole.preset.status', 'Состояние службы'), cmd: 'systemctl status gradebook --no-pager -l | head -20' },
  { label: locale.t('remoteConsole.preset.errors', 'Последние ошибки'), cmd: 'journalctl -u gradebook -p err -n 40 --no-pager' },
  { label: locale.t('remoteConsole.preset.log', 'Журнал сервера'), cmd: 'journalctl -u gradebook -n 60 --no-pager' },
  { label: locale.t('remoteConsole.preset.restartServer', 'Перезапустить сервер'), cmd: 'systemctl restart gradebook && sleep 3 && systemctl is-active gradebook' },
  { label: locale.t('remoteConsole.preset.restartCaddy', 'Перезапустить Caddy'), cmd: 'systemctl restart caddy && systemctl is-active caddy' },
  { label: locale.t('remoteConsole.preset.diskSpace', 'Место на диске'), cmd: 'df -h' },
  { label: locale.t('remoteConsole.preset.spaceUsage', 'Что занимает место'), cmd: 'du -sh /root/gb-deploy/* 2>/dev/null | sort -rh | head -15' },
  { label: locale.t('remoteConsole.preset.cert', 'Сертификат сайта'), cmd: 'journalctl -u caddy -n 30 --no-pager | grep -i cert' },
])

const command = ref('')
const busy = ref(false)
// Каждая запись: { command, ok, code, out, err, seconds }
const history = ref([])
const pending = ref(null)     // команда, ждущая подтверждения (сервер ответил 409)
const logBox = ref(null)

async function send(confirm = false) {
  const cmd = command.value.trim()
  if (!cmd || busy.value) return
  busy.value = true
  try {
    // long: часть команд (перезапуск, установка) не укладывается в короткий предел.
    const long = /systemctl|apt|pip|tar|scp|rsync|du\s/.test(cmd)
    const { data } = await deskServerApi.exec(props.serverId, cmd, { confirm, long })
    history.value.push({ command: cmd, ...data })
    command.value = ''
    pending.value = null
  } catch (e) {
    if (e?.response?.status === 409) {
      // Сервер требует осознанного подтверждения — см. is_dangerous в server_admin.py.
      pending.value = cmd
    } else {
      history.value.push({
        command: cmd, ok: false, code: -1, out: '',
        err: e?.response?.data?.detail || locale.t('remoteConsole.execFailed', 'Не удалось выполнить команду'),
      })
    }
  } finally {
    busy.value = false
    await nextTick()
    if (logBox.value) logBox.value.scrollTop = logBox.value.scrollHeight
  }
}

function usePreset(cmd) {
  command.value = cmd
}
</script>

<template>
  <div class="flex flex-col gap-3">
    <div class="flex flex-wrap gap-1.5">
      <button v-for="p in PRESETS" :key="p.label" type="button" @click="usePreset(p.cmd)"
              class="rounded-full border border-border px-2.5 py-1 text-xs text-text2 transition-colors hover:border-accent hover:text-accent">
        {{ p.label }}
      </button>
    </div>

    <div ref="logBox"
         class="max-h-80 min-h-24 overflow-y-auto rounded-lg border border-border bg-card2 p-3 font-mono text-xs">
      <p v-if="!history.length" class="text-text3">
        {{ locale.t('remoteConsole.explain', 'Команда выполняется отдельным сеансом ssh: «cd» не запоминается между командами, а интерактивные программы (top, nano) работать не будут.') }}
      </p>
      <div v-for="(h, i) in history" :key="i" class="mb-3 last:mb-0">
        <p class="flex items-center gap-2 text-accent">
          <Terminal class="size-3.5 shrink-0" />
          <span class="break-all">{{ h.command }}</span>
        </p>
        <pre v-if="h.out" class="mt-1 whitespace-pre-wrap break-all text-text2">{{ h.out }}</pre>
        <pre v-if="h.err" class="mt-1 whitespace-pre-wrap break-all text-red">{{ h.err }}</pre>
        <p class="mt-1 text-tiny" :class="h.ok ? 'text-text3' : 'text-red'">
          {{ locale.t('remoteConsole.code', { code: h.code }) }}<template v-if="h.seconds"> · {{ locale.t('remoteConsole.seconds', { n: h.seconds }) }}</template>
        </p>
      </div>
    </div>

    <!-- Подтверждение опасной команды. Не запрет: администратор вправе на всё, что мог
         бы сделать в терминале. Это защита от опечатки в пути, а не от намерения. -->
    <div v-if="pending"
         class="flex flex-col gap-2 rounded-lg border border-red/50 bg-card2 p-3">
      <p class="flex items-start gap-2 text-sm text-text2">
        <TriangleAlert class="mt-0.5 size-4 shrink-0 text-red" />
        <span>{{ locale.t('remoteConsole.dangerWarning', 'Команда может необратимо повредить сервер или данные. Проверьте путь ещё раз — восстановить будет нечем, кроме резервной копии.') }}</span>
      </p>
      <pre class="overflow-x-auto rounded-sm bg-card px-2 py-1.5 font-mono text-xs text-red">{{ pending }}</pre>
      <div class="flex gap-2">
        <AppButton variant="red" :disabled="busy" @click="send(true)">{{ locale.t('remoteConsole.runAnyway', 'Всё равно выполнить') }}</AppButton>
        <AppButton variant="ghost" @click="pending = null">{{ locale.t('common.cancel', 'Отмена') }}</AppButton>
      </div>
    </div>

    <form class="flex gap-2" @submit.prevent="send(false)">
      <input v-model="command" :disabled="busy" spellcheck="false"
             :placeholder="locale.t('remoteConsole.inputPlaceholder', 'Команда, например: systemctl status gradebook')"
             class="h-10 min-w-0 flex-1 rounded-sm border border-border2 bg-card2 px-3 font-mono text-sm text-text outline-none focus:border-accent" />
      <AppButton type="submit" :disabled="busy || !command.trim()">
        <Play class="mr-1.5 inline size-4" />{{ busy ? locale.t('remoteConsole.running', 'Выполняем…') : locale.t('remoteConsole.run', 'Выполнить') }}
      </AppButton>
    </form>
  </div>
</template>
