"""
test_profanity_filter.py — цензура мата (profanity_filter.py, корень репо).

Список слов в тестах — минимально необходимый для проверки МЕХАНИЗМА (нормализация,
устойчивость к обходу, границы слов), а не аудит полноты словаря (полных словарей
не существует, см. докстринг модуля).
"""
import time

from profanity_filter import MESSENGER_SAFE_MASK, censor, contains_profanity, find_spans


def test_plain_word_is_censored():
    assert censor("ты хуй") == "ты ***"


def test_declined_forms_caught_by_root():
    """Поиск по корню — ловит склонения без явного перечисления каждой формы."""
    assert contains_profanity("нахуярил")
    assert contains_profanity("охуеть")
    assert contains_profanity("ебаный")


def test_stretched_letters_caught():
    assert censor("хууууй") == "*" * len("хууууй")


def test_spaced_out_letters_caught():
    assert contains_profanity("х у й")
    assert contains_profanity("х.у.й")
    assert contains_profanity("х-у-й")


def test_homoglyph_latin_letters_caught():
    """Латинские похожие буквы — типичный обход простого поиска подстроки. «cyka» —
    ВСЕ 4 буквы имеют прямой маппинг (c→с, y→у, k→к, a→а) = «сука» после нормализации."""
    assert contains_profanity("cyka")


def test_leetspeak_digits_caught():
    assert contains_profanity("cyk@")             # c→с, y→у, k→к, @→а = "сука"


def test_case_insensitive():
    assert censor("ХУЙ") == "***"
    assert censor("Хуй") == "***"


def test_whole_word_roots_do_not_false_positive_on_substrings():
    """Короткие двусмысленные корни («бля»,«сука») — только отдельным словом, не
    подстрокой: «бляха»/«сукно» — обычные русские слова, цензурить их неправильно."""
    assert not contains_profanity("бляха")
    assert not contains_profanity("сукно")
    assert not contains_profanity("сукровица")
    assert censor("бляха") == "бляха"


def test_substring_roots_do_match_inside_longer_words():
    """А вот однозначные корни («хуй», «пизд», «ебат») — подстрокой где угодно,
    т.к. легитимных русских слов с такой подстрокой нет."""
    assert contains_profanity("похуй")        # "по" + корень "хуй" встык
    assert contains_profanity("распиздяй")


def test_no_false_positive_on_clean_text():
    text = "Привет! Как дела? Сегодня хорошая погода, идём на пару по физике."
    assert not contains_profanity(text)
    assert censor(text) == text


def test_empty_and_none_safe():
    assert censor("") == ""
    assert find_spans("") == []
    assert not contains_profanity("")


def test_length_preserved_so_message_layout_does_not_shift():
    text = "это просто хуйня какая-то"
    out = censor(text)
    assert len(out) == len(text)


def test_overlapping_matches_collapse_to_longest_span():
    """«ёб» помечен whole_word — не должен плодить отдельное коротенькое совпадение
    внутри уже найденного более длинного («въебал» матчится через корень «въеб»)."""
    spans = find_spans("въебал")
    assert len(spans) == 1


# ── защита от ReDoS: буквы корня и класс разделителей не пересекаются, поэтому
# откат регулярки должен быть линейным, а не экспоненциальным — проверяем эмпирически
# на заведомо провокационном входе (тело сообщения и так ограничено 4000 символами
# до фильтра, но проверяем именно МЕХАНИЗМ, а не полагаемся только на лимит).
def test_no_catastrophic_backtracking_on_adversarial_input():
    adversarial = ("х" * 200 + "у" * 200 + "!" * 200) * 3 + "неподходящийсуффикс"
    started = time.monotonic()
    contains_profanity(adversarial)
    elapsed = time.monotonic() - started
    assert elapsed < 1.0, f"поиск занял {elapsed:.2f}с — похоже на catastrophic backtracking"


def test_no_catastrophic_backtracking_on_max_length_message():
    adversarial = "хуо" * 1334   # ~4000 символов — реальный потолок _MAX_MSG_CHARS
    started = time.monotonic()
    contains_profanity(adversarial)
    elapsed = time.monotonic() - started
    assert elapsed < 1.0


def test_messenger_mask_is_markdown_safe():
    """Тело сообщения мессенджера рендерится markdownLite.js (**жирный**/*курсив*/
    __подчёркнутый__/~~зачёркнутый~~/`код`/#-заголовок/>-цитата/--список). Обычная
    звёздочка как маска — реальный найденный баг: два цензурируемых слова в одном
    сообщении дают два раздельных звёздочных прогона, и разметка может случайно
    склеить их через текст между ними в жирный/курсив (см. web/tests/
    markdownLite.censorMask.test.mjs — там же воспроизведён и сам баг). Маска
    мессенджера обязана не входить ни в один спецсимвол этого списка."""
    assert MESSENGER_SAFE_MASK not in "*_~#>-`"
