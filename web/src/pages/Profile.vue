<script setup>
// Profile — «Профиль»: сведения об аккаунте + уведомления. Персональные настройки
// (оформление, вход по биометрии, озвучка Вектора) переехали в отдельную вкладку
// «Настройки» (Settings.vue). Здесь позже будем добавлять больше «личных» фич.
import { computed } from 'vue'
import { useAuthStore } from '@/stores/auth'
import Card from '@/components/ui/Card.vue'
import NotificationsInbox from '@/components/NotificationsInbox.vue'

const auth = useAuthStore()
const ROLE = { student: 'Студент', teacher: 'Преподаватель', admin: 'Администратор' }
const initial = computed(() => (auth.user?.name || '?').trim().charAt(0).toUpperCase())
</script>

<template>
  <div class="space-y-6">
    <!-- Сведения об аккаунте. -->
    <Card>
      <div class="flex items-center gap-4">
        <div class="grid size-16 place-items-center rounded-full bg-accent text-2xl font-extrabold text-white">{{ initial }}</div>
        <div>
          <p class="font-title text-xl font-extrabold text-text">{{ auth.user?.name }}</p>
          <p class="text-sm text-text3">{{ ROLE[auth.role] }} · {{ auth.user?.login }}</p>
        </div>
      </div>
    </Card>

    <!-- Уведомления (оценки и изменения расписания). -->
    <Card title="Уведомления" subtitle="Оценки и изменения расписания">
      <NotificationsInbox />
    </Card>
  </div>
</template>
