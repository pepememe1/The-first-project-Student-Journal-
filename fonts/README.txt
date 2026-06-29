ФИРМЕННЫЕ ШРИФТЫ GradeBookAI (как на сайте Synapse)
====================================================

Дизайн рассчитан на два шрифта:
  • Syne     — заголовки (веса 400, 700, 800)
  • DM Sans  — основной текст (веса 300, 400, 500)

Они НЕ зашиты в репозиторий (лицензия OFL — распространяются отдельно) и не
качаются из интернета на боевом ПК (offline-first). Программа подхватывает их
АВТОМАТИЧЕСКИ, если положить сюда .ttf-файлы (см. fonts.py → load_fonts).
Пока файлов нет — интерфейс использует системный Segoe UI (всё работает, просто
не фирменный шрифт).

КАК ДОБАВИТЬ (один раз):
  1) Скачать с Google Fonts (бесплатно, лицензия OFL):
       Syne    → https://fonts.google.com/specimen/Syne
       DM Sans → https://fonts.google.com/specimen/DM+Sans
     (кнопка «Get font» → «Download all» → распаковать .zip)
  2) Скопировать сюда (в папку fonts/) .ttf-файлы, например:
       Syne-Regular.ttf, Syne-Bold.ttf, Syne-ExtraBold.ttf
       DMSans-Regular.ttf, DMSans-Medium.ttf, DMSans-Light.ttf
     Подойдут и статические, и variable (.ttf) версии.
  3) Перезапустить программу — при старте в консоли будет:
       [Fonts] Основной шрифт: DM Sans

Семейства в коде заданы в ui/styles.py (FONT_TITLE = Syne, FONT_BODY = DM Sans),
поэтому после добавления .ttf ничего больше менять не нужно.
