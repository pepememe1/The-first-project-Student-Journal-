"""
test_dropout_risk.py — правила риска отчисления (общий корневой модуль, 3.6).

Тесты «чистые»: модуль не ходит в базу и не знает ни про сервер, ни про десктоп —
проверяем ровно то, ради чего он и вынесен в корень: одинаковые правила у всех.

Главное, что здесь держится, — НЕ конкретные числа весов (их ещё будут крутить), а
ИНВАРИАНТЫ: без фактов риска нет; один признак не даёт «критического»; порог видимости
работает; каждый показанный фактор объясним и снабжён советом.
"""
import dropout_risk as DR


def test_clean_student_has_no_risk():
    """Ни долгов, ни пропусков, нормальный средний — риска нет, и он НЕ показывается."""
    r = DR.assess(average=4.3, subject_averages={"Физика": 4.5, "Химия": 4.1},
                  total_hours=40, absence_hours=2)
    assert r["score"] == 0
    assert r["level"] == "none"
    assert r["visible"] is False
    assert r["factors"] == []


def test_below_threshold_is_not_shown():
    """Единственный слабый фактор даёт индекс НИЖЕ порога видимости.

    Это и есть требование «не показывать риск, если он не 1 %»: пока набралось на
    один мелкий признак, тревожить некого."""
    r = DR.assess(average=3.2, subject_averages={"Физика": 3.2}, total_hours=40)
    assert 0 < r["score"] < DR.MIN_VISIBLE
    assert r["visible"] is False


def test_failed_exam_alone_is_not_critical():
    """Один несданный экзамен — это серьёзно, но НЕ «критический» уровень.

    Критический обязан складываться из совпадения нескольких признаков, иначе слово
    обесценится: с одной задолженностью на пересдаче ходит половина курса."""
    r = DR.assess(average=3.4, failed_exams=["Математика"], subject_averages={"Математика": 3.4})
    assert r["visible"] is True
    assert r["level"] != "critical"


def test_combination_reaches_high_or_critical():
    """Долги + провалы + прогулы + слабые предметы = высокий/критический уровень."""
    r = DR.assess(
        average=2.3,
        subject_averages={"Математика": 2.1, "Физика": 2.4, "История": 2.8},
        debts=5, failed_exams=["Математика", "Физика"],
        absence_hours=24, total_hours=50, unexcused_hours=20)
    assert r["level"] in ("high", "critical")
    assert r["visible"] is True


def test_score_never_exceeds_100():
    """Индекс — шкала 0..100. Сумма весов может её перевалить, наружу это не выходит."""
    r = DR.assess(average=2.0, subject_averages={f"П{i}": 2.0 for i in range(8)},
                  debts=20, failed_exams=[f"Э{i}" for i in range(6)],
                  absence_hours=48, total_hours=50, unexcused_hours=48,
                  silent_subjects=["А", "Б", "В"], zet_earned=0, zet_min=30)
    assert r["score"] == 100
    assert r["level"] == "critical"


def test_unexcused_absences_weigh_more_than_excused():
    """Пропуски «по болезни» и прогулы — не одно и то же.

    Формально пропущенных часов поровну, но прогул это ВЫБОР, а болезнь нет; система
    раннего предупреждения, которая их уравнивает, начинает наказывать за болезнь."""
    excused = DR.assess(average=3.5, absence_hours=20, total_hours=50, unexcused_hours=0)
    skipped = DR.assess(average=3.5, absence_hours=20, total_hours=50, unexcused_hours=20)
    assert skipped["score"] > excused["score"]


def test_absences_are_counted_as_a_share_not_absolute():
    """20 пропущенных часов из 200 и из 40 — разные вещи; считаем ДОЛЮ."""
    big = DR.assess(average=3.5, absence_hours=20, total_hours=200)
    small = DR.assess(average=3.5, absence_hours=20, total_hours=40)
    assert small["score"] > big["score"]


def test_no_grades_at_all_is_a_factor_but_only_if_lessons_happened():
    """Студент без единой отметки — «тихий», и это отдельный признак.

    ⚠️ Только если занятия ШЛИ. В начале семестра оценок нет у всех, и записывать в
    зону риска целый курс — ровно то ложное срабатывание, из-за которого функцию
    перестают читать."""
    silent = DR.assess(average=0.0, has_activity=True)
    assert any(f["code"] == "no_grades" for f in silent["factors"])

    fresh = DR.assess(average=0.0, has_activity=False)
    assert fresh["factors"] == []
    assert fresh["visible"] is False


def test_many_weak_subjects_weigh_more_than_one():
    """Риск растёт от ЧИСЛА проседающих предметов: один долг закрывают, три — почти нет."""
    one = DR.assess(average=2.9, subject_averages={"А": 2.5})
    three = DR.assess(average=2.9, subject_averages={"А": 2.5, "Б": 2.6, "В": 2.7})
    assert three["score"] > one["score"]


def test_zet_shortfall_only_counts_when_threshold_is_set():
    """Порог перевода задаёт куратор/админ. Не задан — норму НЕ выдумываем."""
    without = DR.assess(average=3.5, zet_earned=10, zet_min=None)
    with_min = DR.assess(average=3.5, zet_earned=10, zet_min=30)
    assert not any(f["code"] == "zet" for f in without["factors"])
    assert any(f["code"] == "zet" for f in with_min["factors"])


def test_every_factor_explains_itself():
    """Каждый показанный фактор обязан иметь подпись, подробность и совет.

    Индекс без объяснения бесполезен куратору и воспринимается студентом как приговор —
    это прямое требование к функции, а не украшение."""
    r = DR.assess(average=2.2, subject_averages={"Математика": 2.0, "Физика": 2.4},
                  debts=3, failed_exams=["Математика"],
                  absence_hours=20, total_hours=50, unexcused_hours=15,
                  silent_subjects=["Химия"], zet_earned=5, zet_min=30,
                  trend_delta=-0.8)
    assert r["factors"], "при таких фактах разложение не может быть пустым"
    for f in r["factors"]:
        assert f["label"] and f["detail"] and f["advice"], f
        assert f["points"] > 0, "нулевые вклады в разложение не попадают — это шум"


def test_factors_are_sorted_by_weight():
    """Первым читают верхнюю строку — там обязано быть главное, а не то, что раньше
    посчиталось."""
    r = DR.assess(average=2.2, subject_averages={"А": 2.0}, debts=2,
                  failed_exams=["А", "Б"], absence_hours=25, total_hours=50)
    pts = [f["points"] for f in r["factors"]]
    assert pts == sorted(pts, reverse=True)
    #Совет берётся от САМОГО ТЯЖЁЛОГО фактора — с него и надо начинать.
    assert r["advice"] == r["factors"][0]["advice"]


def test_problem_subjects_are_named_with_reasons():
    """«Из-за каких предметов» — обязательная часть ответа студенту."""
    r = DR.assess(average=2.4, subject_averages={"Математика": 2.0, "Физика": 4.5},
                  failed_exams=["История"], silent_subjects=["Химия"])
    names = {s["subject"]: s["reason"] for s in r["subjects"]}
    assert names["История"] == "экзамен не сдан"
    assert names["Математика"] == "ниже 3"
    assert names["Химия"] == "нет отметок"
    assert "Физика" not in names, "нормальный предмет в список проблем не попадает"


def test_problem_subjects_have_no_duplicates():
    """Предмет, попавший сразу в две категории, называется ОДИН раз."""
    r = DR.assess(average=2.0, subject_averages={"Математика": 2.0},
                  failed_exams=["Математика"])
    assert [s["subject"] for s in r["subjects"]] == ["Математика"]


def test_level_boundaries_are_monotonic():
    """Уровень не может понижаться при росте индекса — иначе шкала врёт."""
    order = ["none", "low", "medium", "high", "critical"]
    seen = [DR.level_of(score)[0] for score in range(0, 101)]
    idx = [order.index(x) for x in seen]
    assert idx == sorted(idx)


def test_summary_line_is_empty_when_risk_is_hidden():
    """Строка для тесных мест пуста, когда показывать нечего: «риск: нет» в списке из
    тридцати студентов — это тридцать строк ни о чём."""
    assert DR.summary_line(DR.assess(average=4.5)) == ""
    line = DR.summary_line(DR.assess(average=2.0, subject_averages={"А": 2.0},
                                     debts=4, failed_exams=["А"]))
    assert "риск отчисления" in line
