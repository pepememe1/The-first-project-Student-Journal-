# -*- coding: utf-8 -*-
"""Одна копия программы на одну папку данных (живой прогон 28.09.2026: второй запуск
открывал второе окно на той же зашифрованной базе и той же очереди досылки)."""
import pathlib
import sys

import pytest

from desktop import single_instance

REPO = pathlib.Path(__file__).resolve().parent.parent


@pytest.mark.skipif(sys.platform != "win32", reason="именованный mutex есть только в Windows")
def test_second_start_on_the_same_data_dir_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(single_instance, "_HANDLE", None)
    a, b = tmp_path / "a", tmp_path / "b"
    assert single_instance.acquire(str(a)) is True
    #Тот же процесс, та же папка — ОС отвечает «уже существует», как и второму процессу.
    assert single_instance.acquire(str(a)) is False
    #Другая папка — своя база и свои ключи: законный второй экземпляр.
    assert single_instance.acquire(str(b)) is True


@pytest.mark.skipif(sys.platform != "win32", reason="именованный mutex есть только в Windows")
def test_after_an_update_the_new_copy_waits_for_the_old_one_to_exit(tmp_path, monkeypatch):
    """Возражение Полковника 29.09.2026: прежняя копия запускает обновлённую и только
    потом выходит. Без ожидания новая упиралась бы в её замок и молча закрывалась."""
    import ctypes
    import threading
    monkeypatch.setattr(single_instance, "_HANDLE", None)
    d = str(tmp_path / "upd")
    assert single_instance.acquire(d) is True
    old = single_instance._HANDLE
    k32 = ctypes.WinDLL("kernel32")
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    #«Старая копия выходит» через полсекунды — ОС снимает её замок.
    threading.Timer(0.5, lambda: k32.CloseHandle(old)).start()
    assert single_instance.acquire(d, wait=5.0) is True, "новая копия не дождалась старую"


def test_relaunch_after_update_tells_the_new_copy_to_wait():
    src = (REPO / "data" / "updater.py").read_text(encoding="utf-8")
    body = src.split("def relaunch(", 1)[1].split("\ndef ", 1)[0]
    assert 'GRADEBOOK_AFTER_UPDATE="1"' in body, "перезапуск не просит новую копию подождать"
    main = (REPO / "main.py").read_text(encoding="utf-8")
    assert "GRADEBOOK_AFTER_UPDATE" in main and "wait=15.0" in main


def test_name_depends_on_the_folder_not_on_its_spelling():
    n1 = single_instance.mutex_name(r"C:\Data\GB")
    assert n1 == single_instance.mutex_name(r"c:\data\gb\.") or sys.platform != "win32"
    assert n1 != single_instance.mutex_name(r"C:\Data\GB2")
    assert n1.startswith("Local\\GradeBookAI-")


def test_main_takes_the_lock_before_installing_an_update():
    """Порядок важен: подменять .exe при живой второй копии нельзя, поэтому замок — ДО
    обновления. Проверяем по тексту main(): запуск окна тут не нужен."""
    src = (REPO / "main.py").read_text(encoding="utf-8")
    body = src.split("def main():", 1)[1]
    lock_at = body.find("single_instance.acquire(")
    update_at = body.find("_apply_pending_update()")
    assert lock_at >= 0, "main() не берёт замок одной копии"
    assert lock_at < update_at, "замок берётся ПОСЛЕ установки обновления"
