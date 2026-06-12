"""
diag_gigachat.py — расширенная диагностика «почему GigaChat не отвечает».

Запусти из папки gradebook:
    python diag_gigachat.py

Скрипт отдельно показывает:
  • прокси-настройки (переменные окружения + системный прокси Windows) —
    главная причина, когда VPN «выключен», но трафик всё равно завёрнут;
  • РАЗДЕЛЬНО сбой DNS (имя не разрешилось) и сбой TCP (имя есть, но порт молчит);
  • несколько попыток подряд — чтобы поймать нестабильность;
  • сравнение DNS на российском (ya.ru) и зарубежном (ipapi.co) хосте.
"""
import os
import socket
import sys

HOSTS = [
    ("ngw.devices.sberbank.ru", 9443, "получение токена (OAuth)"),
    ("gigachat.devices.sberbank.ru", 443, "сам чат"),
]
ATTEMPTS = 3


def show_proxies():
    print("[*] Прокси-настройки (должны быть ПУСТЫЕ):")
    found = False
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
                "http_proxy", "https_proxy", "all_proxy"):
        v = os.environ.get(var)
        if v:
            print(f"      {var} = {v}   <- ВОТ ОНО, прокси активен!")
            found = True
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings")
        enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
        if enabled:
            server, _ = winreg.QueryValueEx(key, "ProxyServer")
            print(f"      Системный прокси Windows ВКЛЮЧЁН: {server}  <- отключи в "
                  f"Параметры -> Сеть -> Прокси")
            found = True
        else:
            print("      Системный прокси Windows: выключен (ок)")
        winreg.CloseKey(key)
    except Exception:
        pass
    if not found:
        print("      переменных прокси нет (ок)")
    return found


def resolve(host: str):
    try:
        infos = socket.getaddrinfo(host, None)
        return sorted({i[4][0] for i in infos})
    except Exception as e:
        print(f"      DNS не разрешает {host}: {e}")
        return None


def tcp_ok(host: str, port: int, timeout: float = 6.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception as e:
        print(f"      TCP {host}:{port} — {e}")
        return False


def check_host(host, port, what):
    print(f"[*] {host}:{port} ({what})")
    ips = resolve(host)
    if ips is None:
        print("    итог: СБОЙ DNS (имя не разрешается — обычно прокси/DNS)")
        return
    print(f"    DNS ок: {', '.join(ips)}")
    oks = sum(1 for _ in range(ATTEMPTS) if tcp_ok(host, port))
    if oks == ATTEMPTS:
        print(f"    итог: доступен ({oks}/{ATTEMPTS})")
    elif oks == 0:
        print(f"    итог: НЕ доступен (0/{ATTEMPTS}) — порт режет файрвол/сеть/прокси")
    else:
        print(f"    итог: НЕСТАБИЛЬНО ({oks}/{ATTEMPTS}) — кривой маршрут/TUN-адаптер")


def main():
    print("=== Диагностика GigaChat (расширенная) ===\n")
    try:
        import gigachat  # noqa: F401
        print("[1] Пакет gigachat: установлен (ок)\n")
    except ImportError:
        print("[1] Пакет gigachat: НЕ установлен  ->  pip install gigachat\n")

    proxy = show_proxies()
    print()

    for host, port, what in HOSTS:
        check_host(host, port, what)

    print("\n[*] Сравнение DNS (РФ vs зарубеж):")
    ru = resolve("ya.ru")
    foreign = resolve("ipapi.co")
    print(f"    ya.ru: {'ок' if ru else 'СБОЙ'} | ipapi.co: {'ок' if foreign else 'СБОЙ'}")

    print("\n=== Итог ===")
    if proxy:
        print("Найден активный прокси — это и есть причина. Отключи его (см. выше) "
              "и перезапусти диагностику.")
    elif ru and not foreign:
        print("РФ-домены резолвятся, зарубежные нет. Похоже на DNS-фильтр прокси/"
              "клиента, который не до конца выключился. Закрой VPN-клиент полностью "
              "и перезагрузись.")
    else:
        print("Если хосты GigaChat нестабильны/недоступны без прокси — закрой VPN-"
              "клиент ПОЛНОСТЬЮ (выход из процесса), отключи его сетевой адаптер, "
              "ipconfig /flushdns и перезагрузись. Затем повтори.")


if __name__ == "__main__":
    sys.exit(main())
