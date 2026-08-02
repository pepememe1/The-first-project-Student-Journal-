// roles.js — ЕДИНЫЙ источник отображаемых названий ролей (Студент/Преподаватель/
// Администратор/Родитель), переведённых через web/src/i18n/dictionaries.js.
//
// До этого набор жил НЕЗАВИСИМО в 6+ файлах (HeaderBar.vue, Profile.vue,
// ProfilePanel.vue, ConversationInfo.vue, ChatThread.vue, AdminMessenger.vue,
// ChatList.vue) — каждый со своей картой `role → русское слово» или if/else
// цепочкой. Тот же класс бага, что уже однажды чинили для статусов пользователя
// (см. config/status.js) — один смысл должен иметь одно имя во всех местах.
import { useLocaleStore } from '@/stores/locale'

/** Отображаемое название роли на текущем языке интерфейса. Неизвестная роль —
 * возвращаем как есть (лучше сырой код роли, чем пустота). */
export function roleLabel(role) {
  if (!role) return ''
  return useLocaleStore().t(`role.${role}`, role)
}
