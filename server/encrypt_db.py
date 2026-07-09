"""
encrypt_db.py — Разовая миграция серверной SQLite-БД в ЗАШИФРОВАННУЮ (SQLCipher, AES-256).

Файл БД целиком шифруется на диске (ПДн at rest, 152-ФЗ). Схема/данные не меняются —
меняется только формат файла; приложение читает его прозрачно, задав GRADEBOOK_DB_KEY.

Порядок на СЕРВЕРЕ (Linux, драйвер sqlcipher3 установлен):
  1. Остановить сервис:            systemctl stop gradebook
  2. Сделать бэкап:                cp gradebook_server.db gradebook_server.db.bak
  3. Сгенерировать ключ (32 байта): openssl rand -hex 32   # 64 hex
  4. Мигрировать:                  GRADEBOOK_DB_KEY=<key> ../venv/bin/python encrypt_db.py
  5. Заменить файл:                mv gradebook_server.db.enc gradebook_server.db
  6. Прописать ключ в .env:         echo "GRADEBOOK_DB_KEY=<key>" >> .env  (chmod 600)
  7. Запустить сервис:             systemctl start gradebook

Откат: вернуть gradebook_server.db.bak и убрать GRADEBOOK_DB_KEY из .env.
"""
import os
import sys


def main():
    key = os.environ.get("GRADEBOOK_DB_KEY", "").strip()
    if len(key) != 64 or any(c not in "0123456789abcdefABCDEF" for c in key):
        sys.exit("GRADEBOOK_DB_KEY должен быть 64 hex (32 байта). Сгенерируйте: openssl rand -hex 32")

    # Путь к БД — из GRADEBOOK_DB_URL (или дефолт), как в config.
    from app.config import DATABASE_URL  # noqa: E402
    if not DATABASE_URL.startswith("sqlite"):
        sys.exit("Шифрование файла применимо только к SQLite (у вас: %s)." % DATABASE_URL)
    path = DATABASE_URL.split("sqlite:///", 1)[-1]
    if not os.path.exists(path):
        sys.exit("Не найден файл БД: %s (запускайте из каталога server/)." % path)

    try:
        import sqlcipher3
    except ImportError:
        sys.exit("Нет драйвера sqlcipher3. Установите: pip install sqlcipher3-binary")

    enc = path + ".enc"
    if os.path.exists(enc):
        os.remove(enc)

    # Открываем ПЛЕЙНТЕКСТ-БД (без ключа), чекпойнтим WAL и экспортируем в зашифрованную.
    conn = sqlcipher3.connect(path)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")  # свести всё в основной файл
    except Exception:
        pass
    conn.execute("ATTACH DATABASE '%s' AS encrypted KEY \"x'%s'\"" % (enc, key))
    conn.execute("SELECT sqlcipher_export('encrypted')")
    conn.execute("DETACH DATABASE encrypted")
    conn.close()

    # Быстрая проверка: зашифрованная БД открывается ключом и читается.
    chk = sqlcipher3.connect(enc)
    chk.execute("PRAGMA key = \"x'%s'\"" % key)
    n = chk.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
    chk.close()
    print("Готово: %s (таблиц: %d). Теперь замените основной файл этим .enc и задайте "
          "GRADEBOOK_DB_KEY в .env." % (enc, n))


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
