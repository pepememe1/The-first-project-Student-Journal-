"""
privacy.py — Обезличивание перед облачной LLM (GigaChat).

Даже отечественная GigaChat — это всё равно передача ПДн стороннему обработчику
(Сберу). С RU-юрисдикцией и договором поручения это законно, но правильнее
минимизировать саму передачу: в облако уходит «Студент №1: средний 3.2», а не
«Иванов Иван». Настоящие имена подставляются обратно ЛОКАЛЬНО, в ответе на экране.

Для офлайн-режима (локальный шаблонизатор или ollama на ПК колледжа) обезличивание
не обязательно — ничего наружу не уходит, — но мы применяем его единообразно,
чтобы код был один.
"""
import re
from typing import Dict, Tuple


class Anonymizer:
    """
    Двусторонняя замена имён на плейсхолдеры.
        anonymize("Иванов получил 4")  -> "Студент №1 получил 4", {"Студент №1": "Иванов"}
        deanonymize("Студент №1 молодец", mapping) -> "Иванов молодец"
    """

    def __init__(self):
        self._fwd: Dict[str, str] = {}     #имя -> плейсхолдер
        self._rev: Dict[str, str] = {}     #плейсхолдер -> имя
        self._n = 0

    def placeholder_for(self, real_name: str) -> str:
        real_name = (real_name or "").strip()
        if not real_name:
            return ""
        if real_name in self._fwd:
            return self._fwd[real_name]
        self._n += 1
        ph = f"Студент №{self._n}"
        self._fwd[real_name] = ph
        self._rev[ph] = real_name
        return ph

    def anonymize_text(self, text: str, names: list) -> str:
        """
        Заменяет вхождения переданных имён на плейсхолдеры. names — список реальных
        имён (фамилий или «Фамилия Имя»), которые встречаются в text.
        Сортируем по длине убыв., чтобы сначала заменить длинные совпадения.
        """
        out = text
        for name in sorted(names, key=len, reverse=True):
            name = (name or "").strip()
            if not name:
                continue
            ph = self.placeholder_for(name)
            out = re.sub(re.escape(name), ph, out)
        return out

    def deanonymize(self, text: str) -> str:
        out = text
        for ph, real in sorted(self._rev.items(), key=lambda x: len(x[0]),
                               reverse=True):
            out = out.replace(ph, real)
        return out

    @property
    def mapping(self) -> Dict[str, str]:
        return dict(self._rev)


def anonymize_facts(facts_text: str, names: list) -> Tuple[str, Anonymizer]:
    """Удобная обёртка: вернуть (обезличенный_текст, анонимайзер)."""
    anon = Anonymizer()
    return anon.anonymize_text(facts_text, names), anon
