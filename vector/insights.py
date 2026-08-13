"""
insights.py — Проактивные карточки-инсайты.

Вектор не ждёт вопроса, а сам подсвечивает важное на дашборде: «у группы просела
посещаемость», «у N студентов незакрытые пересдачи», «M в зоне риска». Все числа —
из intents (то есть из базы), модель тут не нужна вовсе; LLM может лишь красиво
переформулировать готовую карточку.

Каждая карточка возвращается структурно — отрисовку (цвет/иконку) делает widget.
"""
from dataclasses import dataclass

from . import intents
from .intents import VectorScope


@dataclass
class InsightCard:
    severity: str          #"info" | "warn" | "alert"
    icon: str
    title: str
    detail: str
    action: str = ""       #предлагаемый шаг


def mood_from_average(avg: float) -> str:
    """По ТЗ: 4–5 радостный, 3–4 нейтральный, 2–3 грустный (злого нет)."""
    if not avg:
        return "neutral"
    if avg >= 4.0:
        return "happy"
    if avg >= 3.0:
        return "neutral"
    return "sad"


def compute_insights(scope: VectorScope) -> list[InsightCard]:
    """Набор карточек для роли teacher/admin по текущей группе(+предмету)."""
    cards: list[InsightCard] = []

    stats = intents.intent_group_stats(scope)
    d = stats.data
    avg = d.get("average", 0.0)
    if avg:
        mood = mood_from_average(avg)
        sev = {"happy": "info", "neutral": "info", "sad": "warn"}[mood]
        cards.append(InsightCard(
            sev, "📊", f"Средний балл группы {scope.group}",
            f"{avg} — настроение Вектора: "
            f"{ {'happy':'радостное','neutral':'спокойное','sad':'грустное'}[mood] }.",
        ))

    debt = intents.intent_debtors(scope)
    debtors = debt.data.get("debtors", [])
    if debtors:
        cards.append(InsightCard(
            "warn", "⚠️", "Незакрытые задолженности",
            f"Должников: {len(debtors)}. Стоит назначить пересдачи.",
            action="Открыть вкладку «Долги»",
        ))

    risk = intents.intent_at_risk(scope)
    risky = risk.data.get("risky", [])
    if risky:
        cards.append(InsightCard(
            "alert", "🚨", "Студенты в зоне риска",
            f"{len(risky)} студ. со средним < 3 или большими пропусками.",
            action="Связаться с куратором группы",
        ))

    absc = d.get("absences", 0)
    if absc and d.get("students"):
        per = round(absc / max(d["students"], 1), 1)
        if per >= 5:
            cards.append(InsightCard(
                "warn", "🕒", "Высокая доля пропусков",
                f"В среднем {per} ч пропусков на студента в группе {scope.group}.",
            ))

    if not cards:
        cards.append(InsightCard("info", "✅", "Всё спокойно",
                                 f"По группе {scope.group} тревожных сигналов нет."))
    return cards
