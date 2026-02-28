Student Journal (GradeBook) — Alpha 1.1
Техническое описание (Версия 1.1)
В этом разделе описана внутренняя логика приложения и ключевые обновления системы.
Архитектура и хранение данных
Проект сохраняет модульную структуру: ядро (core.py) и графическая оболочка (GUI.py).
 * Динамическая база данных: Система автоматически генерирует локальные JSON-файлы для каждой пары «Группа — Предмет» (например, data_к74_1_Компьютерные_сети.json), что исключает конфликты данных.
 * UUID Идентификация: Каждое занятие получает уникальный идентификатор uuid4. Это гарантирует стабильную связь между оценками и уроками даже при изменении дат или тем.
Математическая модель и валидация
 * Расчет среднего балла: Логика вычислений сфокусирована на занятиях типа «Практика».
 * Учет пропусков: Введена система автоматического штрафа: отметка «Н» (неявка) приравнивается к баллу 2.0 при расчете успеваемости.
 * Целостность: Реализован механизм автоматического сопоставления списка студентов с актуальным количеством уроков в базе данных.
Система доступа и роли
Реализована полноценная авторизация через внешний конфигурационный файл logins.txt.
 * Роль «Учитель»: Позволяет добавлять студентов, создавать занятия («Лекция», «Практика»), выставлять оценки и сохранять изменения в БД.
 * Роль «Ученик»: Предоставляет доступ к персональному дашборду для просмотра среднего балла и статистики по предметам.
Модуль AI Assistant (Alpha)
В интерфейс студента интегрирован прототип ИИ-помощника.
 * Анализ запросов: Метод process_ai_query обрабатывает текстовые запросы пользователя.
 * Сквозной поиск: Помощник умеет собирать данные о количестве оценок по всем доступным предметам одновременно, не требуя ручного переключения вкладок.
Реализация интерфейса
Графическая часть построена на PySide6 (Qt for Python).
 * Управление состояниями: Использование QStackedWidget обеспечивает бесшовную навигацию между окном входа и рабочими панелями.
 * Динамические таблицы: Поддержка контекстных меню для редактирования данных и автоматическое перестроение заголовков при смене группы.
Technical Overview (Alpha 1.1)
Architecture & Persistence
 * Dynamic JSON Mapping: Data is separated into subject-specific JSON files to ensure isolation and scalability.
 * UUID Tagging: All lesson objects are tracked via unique identifiers, preventing data corruption during record updates.
Core Logic
 * Weighted Grade Calculation: The engine specifically targets "Practice" sessions for GPA calculation.
 * Attendance Impact: "Absent" (H) marks are programmatically weighted as a 2.0 grade to reflect academic standing accurately.
Authentication & Roles
 * RBAC System: Access levels are defined via logins.txt.
 * Teacher Mode: Full CRUD operations on student records and session management.
 * Student Mode: Read-only access to personal metrics and subject analytics.
AI & UX Features
 * Heuristic Query Engine: A built-in assistant that provides cross-subject statistics based on natural language keywords.
 * Adaptive UI: Powered by PySide6, utilizing QStackedWidget for efficient screen transitions and the Fusion style for cross-platform consistency.
