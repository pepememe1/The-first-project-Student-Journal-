<script setup>
// SharedGroupsChannels — правая колонка карточки чужого профиля: трофеи и общее.
//
// Общий компонент для ДВУХ мест, которые обязаны выглядеть одинаково: PeerProfileModal
// (профиль участника группы или канала) и ConversationInfo (профиль собеседника в ЛС).
//
// ⚠️ ВКЛАДКАМИ, А НЕ СПИСКОМ ПОДРЯД (правка Влада). Раньше «Общие группы», «Общие
// каналы» и трофеи шли друг под другом, и колонка захламлялась: у активного человека
// там десяток строк ещё до того, как дойдёшь до трофеев. Теперь как в Discord —
// выбрана ОДНА категория, счётчик стоит прямо в её заголовке, а содержимое ниже
// принадлежит только ей.
//
// ⚠️ Вкладки идут В РЯД, а не столбиком (23.08.2026, по образцу Discord). Столбик из
// трёх строк съедал верх колонки и читался как оглавление, хотя это переключатель:
// в ряд сразу видно, что выбор один из трёх, и содержимому остаётся вся высота.
//
// ⚠️ Трофеи чужого профиля — это ВИТРИНА, то есть только то, что человек сам отметил
// галочкой. Полный список наружу не уходит: он показывает, чего у человека НЕТ, а это
// уже про его поведение в продукте, а не про него.
import { ref, computed, onMounted, watch } from 'vue'
import { Radio, Users, Trophy } from '@lucide/vue'
import { useRouter } from 'vue-router'
import { useLocaleStore } from '@/stores/locale'
import { useAuthStore } from '@/stores/auth'
import { useMessengerStore } from '@/stores/messenger'
import { messengerApi } from '@/api/endpoints'
import { BY_ID, RARITY } from '@/config/achievements'

const props = defineProps({
  userId: { type: String, default: '' },
})
const emit = defineEmits(['navigate'])   // родителю: «переход состоялся, пора закрыться»
const locale = useLocaleStore()
const auth = useAuthStore()
const messenger = useMessengerStore()
const router = useRouter()

const tab = ref('trophies')
const groups = ref([])
const channels = ref([])
const trophyIds = ref([])

// Незнакомый id (ачивку убрали из справочника) молча пропускаем, а не рисуем пустую
// карточку: сервер хранит только идентификаторы, и рассинхрон возможен при откате.
const trophies = computed(() => trophyIds.value.map((id) => BY_ID[id]).filter(Boolean))

async function load() {
  groups.value = []; channels.value = []; trophyIds.value = []
  if (!props.userId) return
  try {
    const { data } = await messengerApi.shared(props.userId)
    groups.value = data.groups || []
    channels.value = data.channels || []
  } catch { /* нет доступа или сервера — колонка просто останется пустой */ }
  try {
    const { data } = await messengerApi.profile(props.userId)
    trophyIds.value = data.achievements || []
  } catch { /* то же самое: трофеи не критичны для карточки */ }
}
onMounted(load)
watch(() => props.userId, load)

async function openConversation(conv) {
  await messenger.selectChat({ conversation_id: conv.id, title: conv.title })
  router.push(`/${auth.role}/messages`)
  emit('navigate')
}

// ⚠️ Ярлыки КОРОТКИЕ, и это не косметика. Полные («Общие группы», «Общие каналы») в ряд
// из трёх не помещались никогда: у всех троих обрезалось начало, и на экране стояло
// «Троф… Общ… Общи…» — то есть переключатель не сообщал ВООБЩЕ НИЧЕГО. Слово «общие»
// при этом не несёт смысла: других групп и каналов в чужом профиле не показывают.
// Полное название осталось в подсказке и в заголовке списка под вкладками.
const TABS = computed(() => [
  { id: 'trophies', icon: Trophy, label: locale.t('peerProfile.trophies', 'Трофеи'),
    full: locale.t('peerProfile.trophies', 'Трофеи'), n: trophies.value.length },
  { id: 'groups',   icon: Users,  label: locale.t('peerProfile.tabGroups', 'Группы'),
    full: locale.t('peerProfile.sharedGroups', 'Общие группы'), n: groups.value.length },
  { id: 'channels', icon: Radio,  label: locale.t('peerProfile.tabChannels', 'Каналы'),
    full: locale.t('peerProfile.sharedChannels', 'Общие каналы'), n: channels.value.length },
])
</script>

<template>
  <div class="flex w-72 shrink-0 flex-col overflow-hidden border-l border-border2 bg-card lg:w-80">
    <!-- Категории В РЯД. Счётчик прямо во вкладке: видно, есть ли там что-то, не
         переключаясь туда. Подчёркивание активной, а не заливка — переключатель не
         должен спорить по весу с содержимым под ним. -->
    <div class="flex shrink-0 items-stretch gap-1 overflow-x-auto border-b border-border px-2 pt-2">
      <button v-for="t in TABS" :key="t.id" type="button" @click="tab = t.id"
              :aria-current="tab === t.id" :title="t.full"
              class="flex flex-1 items-center justify-center gap-1 whitespace-nowrap border-b-2
                     px-1.5 pb-2 pt-1 text-[12px] transition-colors"
              :class="tab === t.id
                ? 'border-accent font-semibold text-text'
                : 'border-transparent text-text2 hover:text-text'">
        <component :is="t.icon" class="size-3.5 shrink-0" />
        <!-- ⚠️ Без truncate и без min-w-0: именно они и обрезали ярлык до многоточия.
             Ширины теперь хватает, а если вдруг перестанет — пусть лучше вкладки
             станут прокручиваться (overflow-x на родителе), чем превратятся в «Общ…». -->
        <span class="shrink-0">{{ t.label }}</span>
        <span class="shrink-0 rounded px-1 text-[11px] tabular-nums"
              :class="tab === t.id ? 'bg-accent-glow text-accent' : 'text-text3'">{{ t.n }}</span>
      </button>
    </div>

    <div class="min-h-0 flex-1 overflow-y-auto p-3">
      <!-- Полное название выбранной категории: короткий ярлык во вкладке экономит
           место, а смысл («общие» — то есть общие С ВАМИ) остаётся здесь. -->
      <p class="mb-2 text-[11px] uppercase tracking-wide text-text3">
        {{ TABS.find((t) => t.id === tab)?.full }}
      </p>
      <template v-if="tab === 'trophies'">
        <ul v-if="trophies.length" class="space-y-1.5">
          <li v-for="a in trophies" :key="a.id"
              class="flex items-start gap-2 rounded-lg border border-border2 bg-card2 p-2">
            <span class="grid size-7 shrink-0 place-items-center rounded-md bg-accent-glow text-base">{{ a.icon }}</span>
            <span class="min-w-0">
              <span class="block truncate text-[12.5px] font-semibold text-text">{{ a.title }}</span>
              <span class="block text-[10.5px]" :style="{ color: RARITY[a.rarity].color }">
                {{ locale.t(`achievements.rarity.${a.rarity}`, RARITY[a.rarity].label) }}</span>
            </span>
          </li>
        </ul>
        <p v-else class="text-xs text-text3">
          {{ locale.t('peerProfile.noTrophies', 'Ничего не выставлено') }}
        </p>
      </template>

      <template v-else>
        <ul v-if="(tab === 'groups' ? groups : channels).length" class="space-y-0.5">
          <li v-for="c in (tab === 'groups' ? groups : channels)" :key="c.id">
            <button type="button" @click="openConversation(c)"
                    class="block w-full truncate rounded-md px-2 py-1.5 text-left text-sm text-text2 hover:bg-bg2 hover:text-text">
              {{ c.title }}
            </button>
          </li>
        </ul>
        <p v-else class="text-xs text-text3">{{ locale.t('peerProfile.noneYet', 'Пока нет') }}</p>
      </template>
    </div>
  </div>
</template>
