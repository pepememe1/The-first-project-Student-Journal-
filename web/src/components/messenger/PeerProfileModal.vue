<script setup>
// PeerProfileModal — открывается кликом по аватарке/имени человека где угодно в
// мессенджере (участник группы/канала), как в Discord. Сама карточка — PeerProfileCard
// (общий компонент, см. её докстринг); правая колонка «Общие каналы»/«Общие группы» —
// SharedGroupsChannels (общий и с ConversationInfo.vue, см. её докстринг — 3.6.1).
import { computed, onMounted } from 'vue'
import { X } from '@lucide/vue'
import { useEasterStore, leaveAsk } from '@/stores/easterEggs'
import { useConfirm } from '@/composables/useConfirm'
import { useLocaleStore } from '@/stores/locale'
import PeerProfileCard from '@/components/messenger/PeerProfileCard.vue'
import SharedGroupsChannels from '@/components/messenger/SharedGroupsChannels.vue'

const props = defineProps({
  userId: { type: String, default: '' },
  peerData: { type: Object, default: null },
})
const emit = defineEmits(['close'])
const locale = useLocaleStore()

const targetId = computed(() => props.userId || props.peerData?.id || '')

// ━━ ПАСХАЛКА ПРИ ОТКРЫТИИ ЧУЖОГО ПРОФИЛЯ ━━
// Штамп Papers Please бросается ЗДЕСЬ, а не в карточке: карточка показывается и в своём
// профиле тоже, а бросок должен быть привязан к СОБЫТИЮ «открыл человека», иначе он
// случался бы при каждой перерисовке.
//
// ⚠️ Закрытие окна роутер не видит — это не переход по адресу. Поэтому спрашиваем тут
// сами, тем же текстом, что и при уходе со страницы: иначе штамп исчезал бы молча
// вместе с окном, и человек даже не понял бы, что что-то было.
const easter = useEasterStore()
onMounted(() => { easter.roll('papers_please_stamp') })

async function requestClose() {
  if (easter.pending) {
    const { confirm } = useConfirm()
    const ask = leaveAsk(easter.pending)
    const ok = await confirm({
      title: ask.title, message: ask.message, okText: ask.ok, cancelText: ask.cancel,
    })
    if (!ok) return
    easter.dismissPending()
  }
  emit('close')
}

</script>

<template>
  <!-- ⚠️ РАЗМЕР ТОТ ЖЕ, ЧТО У ПРОФИЛЯ ИЗ ЛИЧНОГО ЧАТА (`ConversationInfo`, max-w-3xl /
       max-h-85vh). Это прямое требование: один и тот же человек не должен выглядеть
       по-разному в зависимости от того, открыли его из группы или из переписки.
       Промежуточный вариант «во весь экран» был ошибкой в другую сторону: карточка
       растягивалась на весь монитор, а правая колонка оставалась узкой — две половины
       одного окна выглядели как два разных окна. -->
  <div class="fixed inset-0 z-50 grid place-items-center p-4" style="background: var(--gb-overlay)"
       @click.self="requestClose">
    <div class="flex max-h-[85vh] w-full max-w-3xl overflow-hidden rounded-xl border border-border2
                bg-card shadow-card">
      <div class="min-h-0 flex-1 overflow-y-auto">
        <PeerProfileCard :user-id="userId" :peer-data="peerData" @messaged="emit('close')" />
      </div>
      <SharedGroupsChannels :user-id="targetId" class="hidden sm:block" @navigate="emit('close')" />
    </div>
    <button type="button" @click="requestClose" :aria-label="locale.t('common.close')"
            class="fixed right-4 top-4 grid size-9 place-items-center rounded-full bg-card text-text3 shadow-card hover:text-text sm:right-6 sm:top-6">
      <X class="size-5" />
    </button>
  </div>
</template>
