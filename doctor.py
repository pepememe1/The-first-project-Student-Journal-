"""
doctor.py — самопроверка установки: почему программа не запускается или не пускает.

Зачем это заведено (3.7.6). Тестировщик склонировал репозиторий и не смог войти. У нас
на машинах всё работало, и разбираться было НЕЧЕМ: интерфейс отвечает одинаковым текстом
и на неверный пароль, и на любой сбой по дороге, а лог лежит в
`%LOCALAPPDATA%\\GradeBookAI\\logs\\` — туда никто не смотрит, пока не подскажешь.

Проверка отвечает на один вопрос: «что на ЭТОЙ машине не так». Она ничего не чинит и
ничего не меняет — только читает и печатает. Сетевые проверки идут ПОСЛЕДНИМИ и с
коротким таймаутом: без интернета программа обязана работать, и «нет связи» — не отказ,
а строка отчёта.

Запуск:  python main.py --doctor   (или python doctor.py)
"""
import importlib
import os
import platform
import sys

#Пакеты, без которых конкретная способность программы отваливается. Список короткий
#НАМЕРЕННО — это не копия requirements.txt, а разбор «что перестанет работать».
_PACKAGES = [
    ("fastapi", "локальный сервер, на котором стоит весь интерфейс"),
    ("uvicorn", "запуск локального сервера"),
    ("httpx", "вход через боевой сервер (без него вход по сети НЕВОЗМОЖЕН)"),
    ("requests", "синхронизация с сервером"),
    ("sqlalchemy", "работа с базой"),
    ("cryptography", "шифрование персональных данных — условие запуска"),
    ("jose", "проверка токенов входа"),
    ("webview", "окно программы (WebView2)"),
    ("openpyxl", "выгрузка в Excel"),
    ("docx", "выгрузка в Word"),
    ("sqlcipher3", "шифрование файла базы целиком (без него база в открытом виде)"),
    ("gostcrypto", "ГОСТ-часть хеша пароля (на сервере — OpenSSL GOST)"),
]


def _line(ok: bool, what: str, detail: str = "") -> str:
    mark = "OK  " if ok else "НЕТ "
    return f"  [{mark}] {what}{(' — ' + detail) if detail else ''}"


def _check_packages() -> list:
    out = []
    for mod, why in _PACKAGES:
        try:
            importlib.import_module(mod)
            out.append(_line(True, mod))
        except Exception as e:
            out.append(_line(False, mod, f"{why}. Ошибка: {type(e).__name__}"))
    return out


def _check_paths() -> list:
    out = []
    try:
        import app_paths
        base = app_paths.data_dir()
        out.append(_line(os.path.isdir(base) or True, "папка данных", base))
        out.append(_line(os.access(os.path.dirname(base) or ".", os.W_OK),
                         "запись в папку данных"))
    except Exception as e:
        out.append(_line(False, "папка данных", f"{type(e).__name__}: {e}"))
    return out


def _check_settings() -> list:
    out = []
    try:
        from data import app_settings
        url = app_settings.get_api_url()
        out.append(_line(bool(url), "адрес сервера", url or "не задан"))
        sess = app_settings.get_saved_session() or {}
        if sess.get("login"):
            alive = app_settings.saved_session_alive()
            out.append(_line(True, "сохранённый вход",
                             f"{sess.get('login')} ({'жив' if alive else 'истёк — нужен пароль'})"))
        else:
            out.append(_line(True, "сохранённый вход", "нет (обычное дело на новой машине)"))
    except Exception as e:
        out.append(_line(False, "настройки программы", f"{type(e).__name__}: {e}"))
    return out


def _check_server(timeout: float = 6.0) -> list:
    """Достаём ли мы боевой сервер. Идёт последним и НЕ влияет на вердикт офлайна."""
    out = []
    try:
        from data import app_settings
        base = (app_settings.get_api_url() or "").rstrip("/")
    except Exception:
        base = ""
    if not base:
        return [_line(False, "связь с сервером", "адрес не задан")]
    try:
        import httpx
    except Exception:
        return [_line(False, "связь с сервером", "нет пакета httpx — проверить нечем")]
    try:
        r = httpx.get(f"{base}/health", timeout=timeout)
        out.append(_line(r.status_code == 200, f"GET {base}/health", f"код {r.status_code}"))
    except Exception as e:
        #Подробность важнее краткости: TLS, DNS и таймаут лечатся по-разному.
        out.append(_line(False, f"GET {base}/health", f"{type(e).__name__}: {e}"))
    return out


def report() -> str:
    """Полный отчёт строкой (её же удобно скинуть в чат)."""
    rows = ["ПРОВЕРКА УСТАНОВКИ GradeBookAI", ""]
    rows.append(f"  Python {platform.python_version()} ({sys.executable})")
    rows.append(f"  Система: {platform.platform()}")
    try:
        from desktop_update import APP_VERSION
        rows.append(f"  Версия программы: {APP_VERSION}")
    except Exception:
        rows.append("  Версия программы: не определяется")
    rows += ["", "ПАКЕТЫ"] + _check_packages()
    rows += ["", "ПУТИ"] + _check_paths()
    rows += ["", "НАСТРОЙКИ"] + _check_settings()
    rows += ["", "СЕТЬ"] + _check_server()
    rows += ["", "Если вход не проходит — пришлите этот отчёт целиком.", ""]
    return "\n".join(rows)


def main() -> int:
    print(report())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
