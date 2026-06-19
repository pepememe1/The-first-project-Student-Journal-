"""
utils.py — Вспомогательные функции и утилиты
"""

import os
import re
import sys

from styles import DEFAULT_GROUPS, DEFAULT_SUBJECTS
from data_store import get_store


#AI TEXT PROCESSING

def clean_ai_text(text: str) -> str:
    """Очистить текст ИИ от markdown и спецсимволов"""
    text = re.sub(r"#{1,6}\s*", "", text)
    text = re.sub(r"\*{1,3}(.*?)\*{1,3}", r"\1", text)
    text = re.sub(r"_{1,2}(.*?)_{1,2}", r"\1", text)
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    text = re.sub(r"`(.*?)`", r"\1", text)
    text = re.sub(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]+", "", text)
    text = re.sub(r"\b[a-zA-Z]{2,}\b", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ДОСТУП К ДАННЫМ ЧЕРЕЗ ХРАНИЛИЩЕ (data_store: локальный SQLite + синк с сервером)

def get_groups():
    """Список групп из хранилища или значения по умолчанию."""
    store = get_store()
    if store:
        try:
            stored = store.get_groups()
            return stored if stored else DEFAULT_GROUPS
        except Exception as e:
            print(f"[ERROR] get_groups: {e}")
    return DEFAULT_GROUPS


def get_subjects_for_group(group_name: str):
    """Предметы для группы."""
    store = get_store()
    if store:
        try:
            for g in store.get_groups():
                if g.get("name") == group_name:
                    return g.get("subjects", DEFAULT_SUBJECTS)
        except Exception as e:
            print(f"[ERROR] get_subjects_for_group: {e}")
    return DEFAULT_SUBJECTS


def get_api_key() -> str:
    """API-ключ из хранилища."""
    store = get_store()
    if store:
        try:
            return store.get_api_key()
        except Exception as e:
            print(f"[ERROR] get_api_key: {e}")
    return ""


def parse_logins():
    """База преподавателей из хранилища."""
    store = get_store()
    if store:
        try:
            t = store.get_teachers()
            if t:
                return t, ""
        except Exception as e:
            print(f"[ERROR] parse_logins: {e}")
    return {}, ""


#  FILE SYSTEM UTILITIES

def resource_path(rel):
    """Получить абсолютный путь к ресурсу (работает с pyinstaller)"""
    try:
        base = sys._MEIPASS
    except AttributeError:
        base = os.path.abspath(".")
    return os.path.join(base, rel)
