import { createApp } from 'vue'
import { createPinia } from 'pinia'
import './style.css'
import App from './App.vue'
import { router } from './router'
import { useThemeStore } from './stores/theme'

const app = createApp(App)
app.use(createPinia())

// Тему применяем ДО монтирования (и до router), чтобы не мигал светлый кадр.
const theme = useThemeStore()
theme.apply()
theme.startScheduleWatcher()

app.use(router)
app.mount('#app')
