"""
seed_demo.py — демо-данные для проверки веб-версии (идемпотентно).

Создаёт студента webtest / webtest1 с группой, предметом, парой практик и оценками,
чтобы на сайте сразу было что показать (средний балл, журнал, статистика). Пишет
НАПРЯМУЮ в серверную БД через модели — без HTTP и барьера устройства.

Запуск:  cd server && python seed_demo.py
Удалить: этого студента можно потом убрать (login=webtest) в десктоп-админке.
"""
from datetime import datetime, timezone

from app.db import SessionLocal, init_db
from app.models import User, Group, Subject, Lesson, Grade
from app.security import hash_password

NOW = datetime.now(timezone.utc).isoformat()
GROUP = "К74/1"
SUBJECT = "Разработка программных модулей"
SURNAME, NAME = "Тестов", "Тест"


def upsert(db, model, pk_field, pk_value, **fields):
    row = db.get(model, pk_value)
    if row is None:
        row = model(**{pk_field: pk_value})
        db.add(row)
    for k, v in fields.items():
        setattr(row, k, v)
    row.updated_at = NOW
    return row


def main():
    init_db()
    db = SessionLocal()
    try:
        upsert(db, Group, "id", "g:webtest", name=GROUP, subjects=[SUBJECT])
        upsert(db, Subject, "id", "s:webtest", name=SUBJECT)
        upsert(db, User, "id", "stud:webtest", role="student", login="webtest",
               password_hash=hash_password("webtest1"),
               surname=SURNAME, name=NAME, group_name=GROUP)

        lessons = [
            ("web-L1", "Практика", 1, "Переменные и типы", "05.09.2025", "5"),
            ("web-L2", "Практика", 2, "Условия и циклы", "12.09.2025", "4"),
            ("web-L3", "Практика", 3, "Функции", "19.09.2025", "5"),
            ("web-L4", "Лекция", 1, "Введение в модули", "26.09.2025", ""),
        ]
        for lid, ltype, num, topic, date, grade in lessons:
            upsert(db, Lesson, "id", lid, group_name=GROUP, subject=SUBJECT,
                   type=ltype, number=num, topic=topic, date=date)
            if grade:
                gid = f"{SURNAME}|{NAME}|{lid}"
                upsert(db, Grade, "id", gid, student_f=SURNAME, student_n=NAME,
                       lesson_id=lid, grade=grade)

        db.commit()
        print("Готово. Демо-студент создан:")
        print("  логин:  webtest")
        print("  пароль: webtest1")
        print(f"  группа: {GROUP}, предмет: {SUBJECT}, оценки: 5,4,5 (средний 4.67)")
    finally:
        db.close()


if __name__ == "__main__":
    main()
