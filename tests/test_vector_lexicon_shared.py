"""
test_vector_lexicon_shared.py — десктоп и сервер делят ОДИН лексикон.

Веб раньше имел вторую упрощённую копию классификатора (8 интентов) — она отставала и
разъезжалась с десктопом (баг плейсхолдеров приехал из этого). Теперь лексикон — в
корневом vector_nlu, а vector/faq.py его РЕЭКСПОРТИРУЕТ. Тест держит это единство.
"""
import vector_nlu
from vector import faq


def test_faq_reexports_shared_lexicon():
    assert faq.INTENT_STEMS is vector_nlu.INTENT_STEMS
    assert faq.classify_by_stems is vector_nlu.classify_by_stems
    assert faq.classify is vector_nlu.classify


def test_new_intents_recognized():
    subs = ["Информатика", "Математика"]
    assert faq.classify("сколько у меня оценок", subjects=subs)["intent"] == "grade_count"
    assert faq.classify("оценки по информатике", subjects=subs)["intent"] == "subject_grades"
    assert faq.classify("когда математика", subjects=subs)["intent"] == "schedule"
    assert faq.classify("какие у меня группы")["intent"] == "groups"
