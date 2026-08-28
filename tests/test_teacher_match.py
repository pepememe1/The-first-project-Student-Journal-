# -*- coding: utf-8 -*-
"""
test_teacher_match.py — сопоставление ФИО с портала ВСГУТУ с нашими аккаунтами.

Главное, что здесь держится: модуль НИКОГДА не называет чужого человека своим. Цена
ошибки — доступ к журналу чужой группы, то есть к ПДн студентов, поэтому неоднозначность
обязана оставаться неоднозначностью, а не «берём первого похожего».

Строки взяты с ЖИВОГО портала (разбор 28.08.2026, 4 группы колледжа, 127 занятий):
«МИХЕЕВ Б.В.», «СЯЧИНОВА Н.В.», «АФХД ИМТЕНОВА Л.Ф.» — последняя показывает, что разбор
ячейки best-effort и к фамилии липнет аббревиатура предмета.
"""
import teacher_match as TM


def acc(uid, surname, name, patronymic="", full_name=""):
    return {"id": uid, "surname": surname, "name": name,
            "patronymic": patronymic, "full_name": full_name}


# ── Разбор строки портала ────────────────────────────────────────────────────────────
def test_parses_plain_portal_name():
    assert TM.parse_portal_name("МИХЕЕВ Б.В.") == ("МИХЕЕВ", "Б", "В")
    assert TM.parse_portal_name("СЯЧИНОВА Н.В.") == ("СЯЧИНОВА", "Н", "В")


def test_junk_before_surname_is_dropped():
    """ЖИВОЙ СЛУЧАЙ: «АФХД ИМТЕНОВА Л.Ф.» — аббревиатура предмета прилипла к фамилии.

    Разбор по ПЕРВОМУ слову дал бы фамилию «АФХД» и сопоставление в никуда; фамилия —
    это токен ПЕРЕД инициалами."""
    assert TM.parse_portal_name("АФХД ИМТЕНОВА Л.Ф.") == ("ИМТЕНОВА", "Л", "Ф")


def test_initials_split_into_two_tokens():
    assert TM.parse_portal_name("БУДАЕВА Л. Ж.") == ("БУДАЕВА", "Л", "Ж")


def test_single_initial_is_enough():
    assert TM.parse_portal_name("КИМ С.") == ("КИМ", "С", "")


def test_name_without_initials_still_gives_surname():
    assert TM.parse_portal_name("ИВАНОВ") == ("ИВАНОВ", "", "")


def test_empty_and_garbage_are_honest_refusals():
    """Пустой разбор — это ОТКАЗ, а не догадка: иначе мусор стал бы назначением."""
    assert TM.parse_portal_name("") == ("", "", "")
    assert TM.parse_portal_name("   ") == ("", "", "")
    assert TM.parse_portal_name("_") == ("", "", "")


# ── Ключ аккаунта ────────────────────────────────────────────────────────────────────
def test_account_key_splits_name_and_patronymic():
    #У нас `name` исторически хранит «Имя Отчество» одной строкой.
    assert TM.account_key("Михеев", "Борис Владимирович") == ("МИХЕЕВ", "Б", "В")
    assert TM.account_key("Михеев", "Борис", "Владимирович") == ("МИХЕЕВ", "Б", "В")


def test_account_key_from_full_name_only():
    assert TM.account_key_from_full_name("Сячинова Наталья Викторовна") == ("СЯЧИНОВА", "Н", "В")


# ── Сопоставление ────────────────────────────────────────────────────────────────────
def test_confident_match_by_surname_and_both_initials():
    accounts = [acc("teach:m", "Михеев", "Борис Владимирович"),
                acc("teach:s", "Сячинова", "Наталья Викторовна")]
    r = TM.match_teacher("МИХЕЕВ Б.В.", accounts)
    assert r["status"] == "matched"
    assert r["teacher_id"] == "teach:m"
    assert r["confidence"] == 3


def test_same_surname_different_initials_is_not_a_match():
    """🔥 Разные инициалы при одной фамилии — это НОЛЬ, а не «почти совпало».

    Именно здесь ошибка выдала бы чужой журнал: Иванов И.И. и Иванов П.С. — разные люди."""
    accounts = [acc("teach:a", "Иванов", "Пётр Сергеевич")]
    r = TM.match_teacher("ИВАНОВ И.И.", accounts)
    assert r["status"] == "unknown"
    assert r["teacher_id"] == ""


def test_namesakes_are_ambiguous_not_first_wins():
    """Двое с одинаковым лучшим счётом — неоднозначность, а НЕ «берём первого»."""
    accounts = [acc("teach:1", "Иванов", "Иван"), acc("teach:2", "Иванов", "Игорь")]
    r = TM.match_teacher("ИВАНОВ И.", accounts)
    assert r["status"] == "ambiguous"
    assert r["teacher_id"] == ""
    assert len(r["candidates"]) == 2


def test_unique_surname_without_initials_matches_weakly():
    accounts = [acc("teach:1", "Сячинова", "Наталья Викторовна")]
    r = TM.match_teacher("СЯЧИНОВА", accounts)
    assert r["status"] == "matched"
    assert r["confidence"] == 1        # слабее, но кандидат один — выбирать не из чего


def test_unknown_teacher_is_reported_not_guessed():
    accounts = [acc("teach:1", "Михеев", "Борис Владимирович")]
    r = TM.match_teacher("НЕИЗВЕСТНАЯ П.П.", accounts)
    assert r["status"] == "unknown"
    assert r["candidates"] == []


def test_unparsed_string_never_becomes_a_match():
    accounts = [acc("teach:1", "Михеев", "Борис Владимирович")]
    r = TM.match_teacher("_", accounts)
    assert r["status"] == "unparsed"
    assert r["teacher_id"] == ""


def test_junk_prefix_still_finds_the_right_person():
    """Сквозной живой случай: мусор перед фамилией не мешает найти человека."""
    accounts = [acc("teach:i", "Имтенова", "Людмила Фёдоровна")]
    r = TM.match_teacher("АФХД ИМТЕНОВА Л.Ф.", accounts)
    assert r["status"] == "matched"
    assert r["teacher_id"] == "teach:i"
    assert r["confidence"] == 3


def test_full_name_only_account_is_supported():
    """Аккаунт без раздельных полей (пришёл со старого десктопа) тоже сопоставляется."""
    accounts = [acc("teach:x", "", "", "", full_name="Базарова Светлана Борисовна")]
    r = TM.match_teacher("БАЗАРОВА С.Б.", accounts)
    assert r["status"] == "matched"
    assert r["teacher_id"] == "teach:x"


def test_case_and_spacing_do_not_matter():
    accounts = [acc("teach:1", "БУДАЕВА", "Лариса Жамсарановна")]
    for s in ("будаева л.ж.", "  БУДАЕВА   Л.Ж.  ", "Будаева Л. Ж."):
        assert TM.match_teacher(s, accounts)["teacher_id"] == "teach:1", s
