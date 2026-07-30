"""
test_grading_scales.py — practice_average() с кастомными шкалами (§ролей, 3.3.1).

Контрактные конвертации (to_five_point/is_failed_scaled по каждой шкале) закреплены в
test_grade_contract.py (общий golden с JS). Здесь — сам practice_average: что scale="5"
(умолчание) не меняет поведение НИ НА БИТ, что 100-балльная/буквенная корректно
переводятся в 5-балльный средний, и что scale-СЛОВАРЬ (разные предметы/преподаватели
в одном списке занятий) резолвит шкалу ПО ЗАНЯТИЮ, а не одну на все.
"""
import grading


def test_default_scale_matches_previous_behavior_bit_for_bit():
    """Регрессия: препод, ничего не выбравший (scale не передан вовсе), получает РОВНО
    тот же средний, что и раньше — to_five_point(v, "5") это lead_num(v)."""
    items = [("l1", "Практика"), ("l2", "Практика"), ("l3", "ДЗ")]
    records = {"l1": "5", "l2": "3", "l3": "Н"}
    assert grading.practice_average(items, records) == grading.practice_average(
        items, records, scale="5")


def test_scale_100_converts_before_averaging():
    items = [("l1", "Практика"), ("l2", "Практика")]
    records = {"l1": "100", "l2": "60"}   # → 5.0 и 3.0
    avg = grading.practice_average(items, records, scale="100")
    assert avg == 4.0


def test_scale_letter_converts_before_averaging():
    items = [("l1", "Практика"), ("l2", "Практика")]
    records = {"l1": "A", "l2": "C"}      # → 5.0 и 3.0
    avg = grading.practice_average(items, records, scale="letter")
    assert avg == 4.0


def test_scale_pass_fail_never_enters_numeric_average():
    """Зачёт/незачёт — статус, не балл (как экзамен с выключенным avg_include_exam)."""
    items = [("l1", "Практика")]
    records = {"l1": "Зачтено"}
    assert grading.practice_average(items, records, scale="pass_fail") == 0.0


def test_scale_dict_resolves_per_lesson():
    """Смешанный список (два предмета, разные преподаватели/шкалы) — словарь
    {lesson_id: scale} даёт КАЖДОМУ занятию свою конвертацию, а не одну на всех."""
    items = [("math1", "Практика"), ("phys1", "Практика")]
    records = {"math1": "90", "phys1": "5"}   # 100-балльная и 5-балльная
    scale_map = {"math1": "100", "phys1": "5"}
    avg = grading.practice_average(items, records, scale=scale_map)
    # 90 на 100-балльной -> 5.0; "5" на 5-балльной -> 5.0
    assert avg == 5.0


def test_scale_dict_missing_lesson_defaults_to_five():
    """Занятие, которого нет в scale_map (напр. без назначения препода) — DEFAULT_SCALE."""
    items = [("l1", "Практика")]
    records = {"l1": "4"}
    assert grading.practice_average(items, records, scale={}) == 4.0


def test_unknown_scale_falls_back_to_default():
    items = [("l1", "Практика")]
    records = {"l1": "5"}
    assert grading.practice_average(items, records, scale="not-a-real-scale") == 5.0


def test_absence_weight_still_applies_regardless_of_scale():
    """«Н» на практике — вес avg_absence_weight, ЭТО правило шкалой не затрагивается
    (шкала конвертирует ЧИСЛОВЫЕ значения, «Н» — отдельный маркер)."""
    items = [("l1", "Практика"), ("l2", "Практика")]
    records = {"l1": "Н", "l2": "95"}   # 95 на 100-балльной -> 5.0
    avg = grading.practice_average(items, records, scale="100")
    # (2.0 [вес Н по умолчанию] + 5.0) / 2 = 3.5
    assert avg == 3.5


def test_scale_values_and_labels_cover_all_scales():
    for sid in ("5", "100", "letter", "pass_fail"):
        vals = grading.scale_values(sid)
        assert vals, f"шкала {sid} должна иметь непустой список значений"
    assert grading.scale_values("bogus") == grading.scale_values(grading.DEFAULT_SCALE)
