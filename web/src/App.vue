<script setup>
// App — корень: только <RouterView>. Регистрируем обработчик «сессия истекла»
// (его дёргает axios-клиент, когда refresh не удался) → уводим на экран входа.
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { setAuthExpiredHandler } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import AppUpdateBanner from '@/components/AppUpdateBanner.vue'

const router = useRouter()
const auth = useAuthStore()

onMounted(() => {
  setAuthExpiredHandler(() => {
    auth.clearSession()
    if (router.currentRoute.value.path !== '/login') router.push('/login')
  })
})
</script>

<template>
  <RouterView />
  <!-- Нативное авто-обновление приложения (баннер, только в APK) -->
  <AppUpdateBanner />
</template>
