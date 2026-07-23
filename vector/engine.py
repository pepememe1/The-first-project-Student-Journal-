"""
engine.py — Оркестратор Вектора.

Связывает всё в один потокобезопасный конвейер:
    ask(question) -> classify -> run_intent (реальный SQL) -> anonymize ->
                     llm.voice -> deanonymize -> VectorResponse(текст, настроение)

Главное свойство: число в ответе всегда происходит из базы (intents), а LLM лишь
переформулирует. Если LLM недоступна — фразу даёт офлайн-шаблон.
"""
import sqlite3
import log
from dataclasses import dataclass
from typing import List, Optional

from . import intents
from .intents import VectorScope, Facts
from .insights import mood_from_average, compute_insights, InsightCard
from .llm import LLMProvider, OfflineTemplateProvider
from .privacy import Anonymizer
from .prompts import GREETINGS


@dataclass
class VectorResponse:
    text: str
    mood: str = "neutral"            #happy / neutral / sad
    intent: str = "help"
    facts: Optional[Facts] = None


class VectorEngine:
    def __init__(self, scope: VectorScope, llm: Optional[LLMProvider] = None):
        self.scope = scope
        self.llm = llm or OfflineTemplateProvider()
        self._mood = "neutral"
        #Базовый предмет области видимости — чтобы распознанный в ОДНОМ вопросе предмет
        #(«оценки по математике») не «залипал» на следующий вопрос без предмета.
        self._base_subject = scope.subject

    #известные фамилии (для классификатора и анонимайзера)
    def _known_surnames(self) -> List[str]:
        try:
            conn = sqlite3.connect(self.scope.db_path)
            cur = conn.cursor()
            cur.execute("SELECT DISTINCT f FROM students WHERE group_name=?",
                        (self.scope.group,))
            res = [r[0] for r in cur.fetchall()]
            conn.close()
            return res
        except Exception:
            return []

    def _known_subjects(self) -> List[str]:
        """Предметы занятий группы — чтобы vector_nlu распознал «оценки по <предмет>»."""
        try:
            conn = sqlite3.connect(self.scope.db_path)
            cur = conn.cursor()
            cur.execute("SELECT DISTINCT subject FROM lessons WHERE group_name=?",
                        (self.scope.group,))
            res = [r[0] for r in cur.fetchall() if r[0]]
            conn.close()
            return res
        except Exception:
            return []

    #основной вызов
    def ask(self, question: str) -> VectorResponse:
        surnames = self._known_surnames()
        intent, asked, subject, day = intents.classify(question, surnames,
                                                        self._known_subjects())
        #Распознанный предмет кладём в scope — subject-фильтрующие обработчики (оценки,
        #средний, счёт) подхватят его. Сырой вопрос — для матча предмета в расписании.
        self.scope.subject = subject or self._base_subject   #сброс, чтобы не «залипал»
        self.scope._q = question

        #Голая фамилия (или «а Гордеев?», «расскажи про Иванова») без явного интента —
        #это УТОЧНЕНИЕ по студенту (типичный follow-up после списка должников/группы).
        #Не гоним такой вопрос в свободный чат — отвечаем выпиской оценок по названному
        #студенту. Для студента privacy-барьер в _resolve_student всё равно вернёт его
        #самого, так что чужие оценки не утекут.
        if intent == "unknown" and asked:
            intent = "grades"

        #ВОПРОС НЕ ИЗ ПУЛА -> свободный чат с LLM (если она подключена).
        #В чистом офлайне free_chat честно подскажет, что умеет Вектор.
        if intent == "unknown":
            q_for_llm = question
            anon: Optional[Anonymizer] = None
            if getattr(self.llm, "name", "offline") in ("gigachat", "local") and surnames:
                anon = Anonymizer()
                q_for_llm = anon.anonymize_text(question, surnames)
            try:
                text = self.llm.free_chat(q_for_llm, role=self.scope.role)
            except Exception as e:
                log.get("engine").warning(f"[Vector] free_chat не удался, офлайн-фолбэк: {e}")
                #Если это сетевая проблема GigaChat/ollama — честно скажем об этом,
                #вместо общего «вопрос вне моих данных».
                net = ""
                if getattr(self.llm, "name", "offline") in ("gigachat", "local"):
                    try:
                        from .llm import explain_giga_error
                        net = explain_giga_error(e)
                    except Exception:
                        net = ""
                if net:
                    text = ("🐯 Не получилось выйти на связь с ИИ-моделью. " + net +
                            " Пока отвечаю по журналу: спроси про оценки, средний "
                            "балл, пропуски или долги.")
                else:
                    text = OfflineTemplateProvider().free_chat(question,
                                                               role=self.scope.role)
            if anon is not None:
                text = anon.deanonymize(text)
            return VectorResponse(text=text, mood=self._mood, intent="unknown")

        facts = intents.run_intent(intent, self.scope, asked, day)

        #настроение по среднему баллу, если интент его дал
        if facts.mood_value is not None:
            self._mood = mood_from_average(facts.mood_value)

        #Заготовленные ответы (приветствие/спасибо/помощь + справка о ВСГУТУ/
        #колледже) отдаём как есть — они уже дружелюбные, точные и не требуют LLM.
        #schedule НЕ озвучиваем: структурный список пар — LLM мог бы добавить/выкинуть
        #занятие. Набор ОБЯЗАН совпадать с server _NO_VOICE_INTENTS (см. CLAUDE.md §5).
        #weather — реальные показания метеослужбы: LLM, «озвучивая данные», меняет
        #числа, а неверная температура в продукте, обещающем не врать, дороже
        #красивой формулировки.
        if intent in ("hello", "thanks", "help", "about_vsgutu", "about_college",
                      "schedule", "weather", "howto"):
            return VectorResponse(text=facts.facts_text, mood=self._mood,
                                  intent=intent, facts=facts)

        #озвучка. Для облачных провайдеров — сначала обезличиваем.
        facts_for_llm = facts.facts_text
        anon: Optional[Anonymizer] = None
        if getattr(self.llm, "name", "offline") in ("gigachat", "local", "server") and facts.names:
            anon = Anonymizer()
            facts_for_llm = anon.anonymize_text(facts.facts_text, facts.names)

        try:
            if getattr(self.llm, "name", "offline") == "offline":
                voiced = self.llm.voice(facts_for_llm, role=self.scope.role,
                                        user_question=question, intent=intent)
            else:
                voiced = self.llm.voice(facts_for_llm, role=self.scope.role,
                                        user_question=question)
        except Exception as e:
            log.get("engine").warning(f"[Vector] озвучка не удалась, офлайн-фолбэк: {e}")
            voiced = OfflineTemplateProvider().voice(facts.facts_text,
                                                     role=self.scope.role,
                                                     intent=intent)

        if anon is not None:
            voiced = anon.deanonymize(voiced)

        return VectorResponse(text=voiced, mood=self._mood,
                              intent=intent, facts=facts)

    #проактивные карточки (для teacher/admin дашборда)
    def insights(self) -> List[InsightCard]:
        return compute_insights(self.scope)

    def greeting(self) -> str:
        return GREETINGS.get(self.scope.role, GREETINGS["student"])

    @property
    def mood(self) -> str:
        return self._mood
