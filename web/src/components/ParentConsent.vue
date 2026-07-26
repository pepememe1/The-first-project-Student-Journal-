<script setup>
// ParentConsent — согласие студента на доступ родителя к его журналу.
//
// Ключевой экран всей роли «родитель»: сотрудник колледжа только создаёт заявку, а доступ
// открывает САМ студент. Так это работает независимо от возраста, и для совершеннолетних
// (а это половина колледжа) не нарушает 152-ФЗ.
//
// Отзыв доступен и после подтверждения: согласие на обработку своих данных человек вправе
// отозвать в любой момент, поэтому кнопка «Отозвать» стоит рядом с активным доступом, а
// не прячется в поддержке.
import { ref, computed, onMounted } from 'vue'
import { consentApi } from '@/api/endpoints'
import Card from '@/components/ui/Card.vue'
import AppButton from '@/components/ui/AppButton.vue'
import Badge from '@/components/ui/Badge.vue'
import { useToast } from '@/composables/useToast'
import { useConfirm } from '@/composables/useConfirm'

const toast = useToast()
const { confirm } = useConfirm()
const links = ref([])
const busy = ref('')

const pending = computed(() => links.value.filter((l) => l.status === 'pending'))
const active = computed(() => links.value.filter((l) => l.status === 'active'))

async function load() {
  try { links.value = (await consentApi.links()).data.links || [] } catch { links.value = [] }
}

async function decide(link, approve) {
  if (!approve && link.status === 'active') {
    const ok = await confirm({
      title: 'Отозвать доступ?',
      message: `${link.parent.full_name} перестанет видеть ваш журнал. Вернуть доступ можно будет только новой заявкой от колледжа.`,
      okText: 'Отозвать', danger: true,
    })
    if (!ok) return
  }
  busy.value = link.id
  try {
    await consentApi.decide(link.id, approve)
    toast.success(approve ? 'Доступ открыт' : 'Доступ закрыт')
    await load()
  } catch (e) { toast.error(e?.response?.data?.detail || 'Не удалось сохранить') }
  finally { busy.value = '' }
}

onMounted(load)
defineExpose({ load })
</script>

<template>
  <Card v-if="pending.length || active.length" title="Доступ родителей к журналу" pad>
    <div class="space-y-3">
      <div v-for="l in pending" :key="l.id"
           class="rounded-sm border border-accent/40 bg-accent/5 px-3 py-2.5">
        <p class="text-sm text-text">
          <span class="font-semibold">{{ l.parent.full_name || l.parent.login }}</span>
          запрашивает доступ к вашему журналу.
        </p>
        <p class="mt-0.5 text-xs text-text3">
          Он сможет видеть ваши оценки, средний балл и посещаемость. Решение за вами —
          отказ ни на что в учёбе не влияет.
        </p>
        <div class="mt-2 flex gap-2">
          <AppButton variant="green" size="sm" :disabled="busy === l.id" @click="decide(l, true)">
            Разрешить
          </AppButton>
          <AppButton variant="ghost" size="sm" :disabled="busy === l.id" @click="decide(l, false)">
            Отказать
          </AppButton>
        </div>
      </div>

      <div v-for="l in active" :key="l.id"
           class="flex flex-wrap items-center gap-2 rounded-sm border border-border2 px-3 py-2">
        <span class="text-sm text-text">{{ l.parent.full_name || l.parent.login }}</span>
        <Badge variant="green">доступ открыт</Badge>
        <button type="button" class="ml-auto text-xs text-text3 hover:text-red"
                :disabled="busy === l.id" @click="decide(l, false)">
          Отозвать
        </button>
      </div>
    </div>
  </Card>
</template>
