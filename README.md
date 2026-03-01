🎓 GradeBookAI (Альфа 1.1)
Современное десктопное приложение для автоматизации работы преподавателей и удобного отслеживания успеваемости студентами. Приложение поддерживает разделение на роли и интеграцию с искусственным интеллектом для анализа данных.
🚀 Возможности (Features)
👨‍🏫 Кабинет преподавателя:
 * Удобный табличный интерфейс: Добавление студентов, лекций, практических занятий и назначение экзаменов в пару кликов.
 * Гибкая система учета: Поддержка классических оценок (2, 3, 4, 5) и отметок посещаемости: Н (отсутствовал), О (опоздал), Б (болел по уважительной причине), ✓ (присутствовал).
 * Редактирование на лету: Изменение дат и тем занятий прямо через контекстное меню таблицы (ПКМ).
 * Локальное хранение данных: Автоматическая генерация и сохранение баз данных в формате JSON для каждой группы и предмета (data_{группа}_{предмет}.json).
👨‍🎓 Кабинет студента:
 * Персонализированный дашборд: Просмотр списка своих оценок по всем профильным предметам (Компьютерные сети, ООП, Базы данных и др.).
 * 🤖 Умный ИИ-помощник: Встроенный чат с ИИ (на базе OpenRouter API), который анализирует успеваемость конкретного студента.
 * Точный расчет балла: Внутренняя логика программы автоматически конвертирует пропуски (Н) в оценки «2», а каждые 2 опоздания (О) приравнивает к 1 пропуску для объективного расчета среднего балла.
🌟 Плюсы и особенности (Advantages)
 * Защита от ИИ-галлюцинаций: Нейросеть работает с минимальной "температурой" (temperature: 0.1) и опирается только на жестко заданные данные из системы, что исключает выдумывание оценок.
 * Кроссплатформенный GUI: Современный графический интерфейс написан на мощном фреймворке PySide6 (привязка Qt для Python).
 * Автономность (Portable): Система не требует установки сторонних серверов (MySQL/PostgreSQL), работая с легковесными локальными файлами.
 * Масштабируемая архитектура: Код разделен на логические модули (core.py для логики и хранения, GUI.py для интерфейса), что позволяет легко дорабатывать проект командой.
🛠 Технический стек (Tech Stack)
 * Язык: Python 3
 * Интерфейс: PySide6 (QtWidgets)
 * Хранение данных: JSON (встроенные библиотеки)
 * Нейросеть: Модель stepfun/step-3.5-flash (через OpenRouter API)

🎓 GradeBookAI (Alpha 1.1)
A modern desktop application designed to automate teachers' workflows and provide students with a convenient way to track their academic progress. The app supports role-based access and features artificial intelligence integration for data analysis.
🚀 Features
👨‍🏫 Teacher's Dashboard:
 * User-friendly Tabular Interface: Add students, lectures, practical classes, and assign exams in just a few clicks.
 * Flexible Grading System: Supports standard grades (2, 3, 4, 5) as well as attendance marks: Н (absent), О (late), Б (sick leave), ✓ (present).
 * On-the-fly Editing: Modify dates and lesson topics directly via the table's context menu (Right-Click).
 * Local Data Storage: Automatic generation and saving of JSON databases for each group and subject (data_{group}_{subject}.json).
👨‍🎓 Student's Dashboard:
 * Personalized Dashboard: View grades across all core subjects (Computer Networks, OOP, Database Design, etc.).
 * 🤖 Smart AI Assistant: Built-in AI chat (powered by OpenRouter API) that analyzes the specific student's academic performance.
 * Accurate GPA Calculation: The internal logic automatically converts absences (Н) into "2" (fail), and counts every 2 late arrivals (О) as 1 absence to ensure an objective average score calculation.
🌟 Advantages & Peculiarities
 * AI Hallucination Protection: The neural network operates at a minimum temperature (temperature: 0.1) and relies strictly on hardcoded system data, completely eliminating the risk of made-up grades.
 * Cross-platform GUI: The modern graphical user interface is built on the powerful PySide6 framework (Qt binding for Python).
 * Autonomous (Portable): The system does not require third-party servers (like MySQL/PostgreSQL) and runs smoothly using lightweight local files.
 * Scalable Architecture: The code is divided into logical modules (core.py for logic and storage, GUI.py for the interface), making team collaboration and future development easy.
🛠 Tech Stack
 * Language: Python 3
 * Interface: PySide6 (QtWidgets)
 * Data Storage: JSON (built-in libraries)
 * AI Engine: stepfun/step-3.5-flash model (via OpenRouter API)
