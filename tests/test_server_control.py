"""
test_server_control.py — Фоновый сервер хоста: постоянное имя/ссылка и PID-хелперы.

Реальные процессы (uvicorn/ssh) НЕ поднимаем — в CI нет ssh и свободных портов.
Проверяем чистые куски: генерацию/персист постоянного имени serveo, детерминированный
публичный адрес и кросс-платформенные PID-хелперы. server/.env подменяем на временный,
чтобы не трогать реальную конфигурацию.
"""
import os

import server_control as sc


def test_ensure_tunnel_name_persists(tmp_path, monkeypatch):
    monkeypatch.setattr(sc, "ENV_PATH", str(tmp_path / ".env"))
    #Имени ещё нет — генерится стабильное gradebook-<hex>.
    name1 = sc.ensure_tunnel_name()
    assert name1.startswith("gradebook-") and len(name1) > len("gradebook-")
    #Повторный вызов НЕ меняет имя (адрес должен быть постоянным).
    name2 = sc.ensure_tunnel_name()
    assert name2 == name1
    #И оно реально сохранено в .env.
    assert sc.get_tunnel_name() == name1


def test_public_tunnel_url_deterministic():
    assert sc.public_tunnel_url("vsgutu") == "https://vsgutu.serveo.net"
    assert sc.public_tunnel_url("") == ""


def test_pid_file_roundtrip(tmp_path):
    p = str(tmp_path / "x.pid")
    sc._write_pid(p, 4242)
    assert sc._read_pid(p) == 4242
    #Несуществующий файл — 0, не исключение.
    assert sc._read_pid(str(tmp_path / "nope.pid")) == 0


def test_pid_alive():
    #Свой процесс — жив; заведомо отсутствующий PID — нет.
    assert sc._pid_alive(os.getpid()) is True
    assert sc._pid_alive(999999) is False
    assert sc._pid_alive(0) is False


def test_detached_flags_is_int():
    assert isinstance(sc._detached_flags(), int)
