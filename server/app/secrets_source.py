# -*- coding: utf-8 -*-
"""secrets_source.py — ОДНА точка чтения секретов сервера.

━━ ЧТО БЫЛО НЕ ТАК ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Все секреты приходили одинаково: `os.environ.get(...)` в шести разных файлах, а
значения клались в окружение процесса из `server/.env` с правами 600. Дыры в этом
две, и обе тихие:

  • переменные окружения процесса видны в `/proc/<pid>/environ` и в выводе
    `systemctl show`. То есть ЛЮБОЙ, кто получил на машине права root — включая
    администратора вуза, которому мы отдадим сервер, и любой процесс, работающий
    от root, — читает ключ от базы с персональными данными, ничего не взламывая;
  • ключ SQLCipher лежит на ТОМ ЖЕ диске, что и зашифрованная им база. Снимок
    диска или его кража даёт и то и другое разом, и шифрование не даёт ничего.

━━ ЧТО ТЕПЕРЬ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Секрет ищется в трёх местах, в порядке убывания надёжности:

  1. КАТАЛОГ УЧЁТНЫХ ДАННЫХ systemd (`$CREDENTIALS_DIRECTORY/<имя>`). Файлы туда
     кладёт systemd, видны они ТОЛЬКО процессу службы, в окружении их нет, в
     `systemctl show` их нет, а при `SetCredentialEncrypted=` они лежат на диске
     зашифрованными ключом машины (TPM, если он есть);
  2. ФАЙЛ, указанный в `<ПЕРЕМЕННАЯ>_FILE`. Тот же приём, что у Docker и
     Kubernetes secrets, — понадобится, если вуз захочет контейнеры;
  3. ПЕРЕМЕННАЯ ОКРУЖЕНИЯ — как раньше. Оставлена намеренно: разработка,
     тесты и нынешний боевой сервер работают без единой правки, а переход
     делается на машине, а не в коде.

⚠️ Порядок именно такой и менять его нельзя. Если бы окружение перебивало
файлы, то забытая в окружении старая переменная тихо отменяла бы переход на
хранилище — и мы бы считали, что секреты убраны, когда они на месте.

⚠️ Значение НИКОГДА не логируется целиком. В сообщениях — только имя и, при
необходимости, длина: строка «ключ не подошёл: a1b2c3…» в журнале превращает
журнал в место хранения ключа.
"""

from __future__ import annotations

import os

#Имена секретов, которые обязаны читаться отсюда. Список нужен не для чтения
#(функция работает с любым именем), а для СТОРОЖА: он проверяет, что ни один из
#них не читается в обход, обычным os.environ.get. Забыть новый секрет легко —
#именно так и появляются «полузакрытые» переходы.
SECRET_NAMES = (
    "GRADEBOOK_DB_KEY",             # ключ SQLCipher от базы с ПДн — самый ценный
    "GRADEBOOK_JWT_SECRET",         # подпись токенов: знающий его выпишет себе админа
    "GRADEBOOK_DATA_KEY",           # «Кузнечик» для полей
    "GRADEBOOK_INDEX_KEY",          # слепой индекс (HMAC-Стрибог)
    "GRADEBOOK_SMTP_PASS",          # почта
    "GRADEBOOK_KLIPY_API_KEY",      # сторонний сервис GIF
    "GRADEBOOK_RUSTORE_SERVICE_TOKEN",  # отправка пушей
    "GRADEBOOK_S3_KEY",             # объектное хранилище вложений
    "GRADEBOOK_S3_SECRET",
)


def _from_credentials_dir(name: str) -> str | None:
    """systemd LoadCredential / SetCredentialEncrypted."""
    root = os.environ.get("CREDENTIALS_DIRECTORY", "").strip()
    if not root:
        return None
    #systemd не любит подчёркивания и регистр в именах учётных данных, поэтому
    #кладём их в нижнем регистре с дефисами: GRADEBOOK_DB_KEY → gradebook-db-key.
    fname = name.lower().replace("_", "-")
    path = os.path.join(root, fname)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError as e:
        #Имя — да, значение — никогда.
        print(f"[secrets] не прочитан {name} из учётных данных службы: {e.strerror}")
        return None


def _from_file_var(name: str) -> str | None:
    """Docker/K8s-совместимое `<ИМЯ>_FILE=/путь`."""
    path = os.environ.get(name + "_FILE", "").strip()
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError as e:
        #Здесь МОЛЧАТЬ НЕЛЬЗЯ: человек явно указал файл, и тихий откат на пустое
        #значение означал бы «сервер поднялся, но без шифрования» — худший исход.
        print(f"[secrets] указан {name}_FILE, но файл не прочитан: {e.strerror}")
        return None


def get(name: str, default: str = "") -> str:
    """Значение секрета. Порядок: учётные данные службы → файл → окружение."""
    for source in (_from_credentials_dir, _from_file_var):
        value = source(name)
        if value:
            return value
    return os.environ.get(name, default).strip()


def source_of(name: str) -> str:
    """Откуда взят секрет — для диагностики. Возвращает ИМЯ ИСТОЧНИКА, не значение.

    Нужно на приёмке и при разборе инцидента: вопрос «а точно ли сервер читает
    ключ из хранилища, а не из старой переменной» иначе проверяется только
    чтением кода, то есть верой.
    """
    if _from_credentials_dir(name):
        return "учётные данные службы"
    if _from_file_var(name):
        return "файл"
    if os.environ.get(name, "").strip():
        return "переменная окружения"
    return "не задан"
