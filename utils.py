"""
utils.py — Вспомогательные функции и утилиты
"""

import os
import re
import sys

from styles import DEFAULT_GROUPS, DEFAULT_SUBJECTS
from data_store import get_store as get_gh_store


#  AI TEXT PROCESSING

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


#  DATA RETRIEVAL FROM GITHUB STORAGE

def get_groups():
    """Получить список групп из GitHub или значения по умолчанию"""
    gh = get_gh_store()
    if gh:
        try:
            stored = gh.get_groups()
            return stored if stored else DEFAULT_GROUPS
        except Exception as e:
            print(f"[ERROR] get_groups: {e}")
    return DEFAULT_GROUPS


def get_subjects_for_group(group_name: str):
    """Получить предметы для группы"""
    gh = get_gh_store()
    if gh:
        try:
            for g in gh.get_groups():
                if g.get("name") == group_name:
                    return g.get("subjects", DEFAULT_SUBJECTS)
        except Exception as e:
            print(f"[ERROR] get_subjects_for_group: {e}")
    return DEFAULT_SUBJECTS


def get_api_key() -> str:
    """Получить API ключ из GitHub"""
    gh = get_gh_store()
    if gh:
        try:
            return gh.get_api_key()
        except Exception as e:
            print(f"[ERROR] get_api_key: {e}")
    return ""


def parse_logins():
    """Получить базу учителей из GitHub"""
    gh = get_gh_store()
    if gh:
        try:
            t = gh.get_teachers()
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
