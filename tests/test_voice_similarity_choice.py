"""Выбор меры сходства фамилий в голосовых командах — замер, а не вера (20.10.2026).

Сравниваются мера продукта (`voice_command._similar`, Рэтклифф — Обершелп + фонетика) и
отвергнутая альтернатива — Джаро — Винклер (реализована ЗДЕСЬ: в продукте её нет). Тест
держит два свойства:
  1. варианты одной фамилии, которые путает распознавание речи, проходят порог продукта;
  2. на этом наборе альтернатива при пороге продукта ошибается не реже, — то есть
     «заменить на Джаро — Винклера» без нового замера нельзя.
"""
import voice_command as vc

THRESHOLD = 0.74          # порог `_match_students` по умолчанию

SAME = [("гындынова", "гундынова"), ("самбуев", "самбоев"), ("баянжаргал", "баянжаргалл"),
        ("цыденова", "цыдынова"), ("дашиева", "дашеева"), ("гэндэнова", "гындынова"),
        ("эрдынеев", "ердынеев"), ("доржиев", "доржеев"), ("жамсаранова", "жамцаранова"),
        ("хаанн", "хан"), ("аюшеев", "аюшиев"), ("батуев", "батоев")]
DIFF = [("петров", "петренко"), ("сидоров", "петров"), ("иванов", "ивашов"),
        ("иванов", "иванцов"), ("дашиев", "дамбиев"), ("цыренов", "цыбиков"),
        ("бадмаев", "базаров"), ("николаев", "никифоров"), ("самбуев", "санжиев"),
        ("цыденов", "цыбенов"), ("батуев", "бадуев"), ("иванова", "ивакина"),
        ("петрова", "петрук")]


def _jaro_winkler(a, b, p=0.1):
    if a == b:
        return 1.0
    d = max(len(a), len(b)) // 2 - 1
    ma, mb = [False] * len(a), [False] * len(b)
    m = 0
    for i, ch in enumerate(a):
        for j in range(max(0, i - d), min(len(b), i + d + 1)):
            if not mb[j] and b[j] == ch:
                ma[i] = mb[j] = True
                m += 1
                break
    if not m:
        return 0.0
    t = k = 0
    for i in range(len(a)):
        if ma[i]:
            while not mb[k]:
                k += 1
            t += a[i] != b[k]
            k += 1
    j = (m / len(a) + m / len(b) + (m - t // 2) / m) / 3
    pref = 0
    for x, y in zip(a, b, strict=False):
        if x != y or pref == 4:
            break
        pref += 1
    return j + pref * p * (1 - j)


def _errors(score):
    s = vc._stem
    miss = sum(score(s(a), s(b)) < THRESHOLD for a, b in SAME)
    false = sum(score(s(a), s(b)) >= THRESHOLD for a, b in DIFF)
    return miss, false


def test_speech_variants_of_one_surname_pass_the_product_threshold():
    miss, _ = _errors(vc._similar)
    assert miss == 0


def test_jaro_winkler_is_not_better_on_our_surnames():
    product = sum(_errors(vc._similar))
    jw = sum(_errors(lambda a, b: max(_jaro_winkler(a, b),
                                      _jaro_winkler(vc._phon(a), vc._phon(b)))))
    assert product <= jw, (product, jw)
