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


# ── Малое число данных и тренд (исследование 20.10.2026) ────────────────────────────

def test_single_two_is_not_neattestation():
    """Обратный ход ложной тревоги: одна двойка давала «средний ниже 2.5» (25 баллов)."""
    old = DR.assess(average=2.0, total_hours=4)
    assert [f for f in old["factors"] if f["code"] == "low_average"][0]["points"] == 25
    new = DR.assess(average=2.0, total_hours=4, grade_count=1)
    f = [f for f in new["factors"] if f["code"] == "low_average"][0]
    assert f["points"] == 8
    assert "2.00" in f["detail"] and "всего 1" in f["detail"], "в тексте — настоящие цифры"


def test_many_twos_still_alarm_fully():
    r = DR.assess(average=2.0, total_hours=60, grade_count=20)
    assert [f for f in r["factors"] if f["code"] == "low_average"][0]["points"] == 25


def test_smoothing_never_creates_alarm_for_a_good_student():
    #Одна пятёрка: сглаживание тянет к 3.5, но берётся мягшее — фактора нет вовсе.
    r = DR.assess(average=5.0, total_hours=4, grade_count=1)
    assert not [f for f in r["factors"] if f["code"] == "low_average"]


def test_first_missed_lesson_is_not_a_visible_risk():
    """Пропуск единственного занятия — 100 % пропусков. Раньше: 25 × 1.4 = 35 баллов,
    видимый риск на первокурснике, заболевшем 1 сентября."""
    r = DR.assess(average=0.0, has_activity=False, absence_hours=2, total_hours=2,
                  unexcused_hours=2)
    assert r["score"] < DR.MIN_VISIBLE
    #А систематический прогул по-прежнему ловится в полную силу.
    r = DR.assess(average=0.0, has_activity=False, absence_hours=40, total_hours=60,
                  unexcused_hours=40)
    assert [f for f in r["factors"] if f["code"] == "absences"][0]["points"] == 35


def test_trend_from_lesson_dates_theil_sen():
    import datetime as dt
    d0 = dt.date(2026, 9, 1)
    falling = [(d0 + dt.timedelta(days=7 * i), v) for i, v in enumerate([5, 5, 4, 4, 3, 3])]
    slope, n = DR.trend_from_points(falling)
    assert n == 6 and slope is not None and slope < -0.5
    r = DR.assess(average=4.0, trend_delta=slope, trend_points=n)
    assert any(f["code"] == "trend" and "6 учебным дням" in f["detail"] for f in r["factors"])


def test_single_bad_grade_does_not_make_a_trend():
    import datetime as dt
    d0 = dt.date(2026, 9, 1)
    pts = [(d0 + dt.timedelta(days=7 * i), v) for i, v in enumerate([4, 4, 4, 4, 4, 2])]
    slope, _ = DR.trend_from_points(pts)
    assert slope == 0


def test_trend_needs_enough_points_and_span():
    import datetime as dt
    d0 = dt.date(2026, 9, 1)
    assert DR.trend_from_points([(d0, 5), (d0, 2), (d0, 2)])[0] is None
    short = [(d0 + dt.timedelta(days=i), 5 - i) for i in range(5)]
    assert DR.trend_from_points(short)[0] is None          # пять дней — это не динамика


def _low(r):
    f = [f for f in r["factors"] if f["code"] == "low_average"]
    return f[0] if f else None


def test_large_sample_is_judged_as_is():
    """🔥 Находка Полковника 21.10.2026: сглаживание действовало при ЛЮБОМ числе оценок —
    30 оценок со средним 2.4 давали «ниже 3» (18) вместо «ниже 2.5» (25) и текст «оценок
    всего 30 — судить рано»."""
    big = _low(DR.assess(average=2.4, grade_count=30))
    assert big["points"] == _low(DR.assess(average=2.4))["points"] == 25
    assert "судить рано" not in big["detail"]
    assert "судить рано" not in _low(DR.assess(average=3.2, grade_count=100))["detail"]


def test_absences_on_a_long_semester_are_counted_as_is():
    """16 пар из 40 — это 40 %, а не «36 % по сглаживанию»: ступень «40 % и выше»."""
    r = DR.assess(absence_hours=32, total_hours=80)
    assert [f for f in r["factors"] if f["code"] == "absences"][0]["points"] == 25


def test_a_good_grade_never_raises_the_risk():
    """Сглаживание гаснет плавно, а не обрывом: иначе на границе малой выборки хорошая
    оценка выключала бы сглаживание и ПОДНИМАЛА риск."""
    for n in range(1, 2 * DR.SMALL_SAMPLE):
        for avg10 in range(20, 34):
            avg = avg10 / 10
            before = DR.assess(average=avg, grade_count=n)["score"]
            after = DR.assess(average=(avg * n + 5) / (n + 1), grade_count=n + 1)["score"]
            assert after <= before, (n, avg, before, after)


# ── Тренд: учебные дни и последовательность (поправка 21.10.2026, разбор Ярослава) ──────

def _weekly(values, step=7):
    import datetime as dt
    d0 = dt.date(2026, 9, 1)
    return [(d0 + dt.timedelta(days=step * i), v) for i, v in enumerate(values)]


def test_one_late_two_after_three_fives_is_not_a_trend():
    """Пример Ярослава: 5, 5, 5, 2 с шагом 10 дней — Тейл — Сен даёт −1.5 балла в месяц,
    потому что при четырёх точках одна оценка входит в ПОЛОВИНУ пар. Тревоги быть не должно."""
    import estimators
    pts = _weekly([5, 5, 5, 2], step=10)
    assert round(estimators.theil_sen_slope([(d.toordinal(), v) for d, v in pts]) * 30, 2) == -1.5
    assert DR.trend_from_points(pts)[0] is None           #четыре дня — мало
    slope, n = DR.trend_from_points(_weekly([5, 5, 5, 5, 2], step=10))
    assert n == 5 and slope == 0.0                        #пять — одна двойка медиану не двигает


def test_steep_but_inconsistent_slope_is_not_a_decline():
    """Колебания: наклон −0.71 в месяц (ниже порога −0.5), но падение непоследовательное
    (Манн — Кендалл Z ≈ −0.47). Без проверки последовательности это была бы тревога."""
    import estimators
    vals = [4, 2, 5, 3, 4, 2, 3]
    pts = _weekly(vals)
    raw = estimators.theil_sen_slope([(d.toordinal(), v) for d, v in pts]) * 30
    assert raw <= -0.5
    assert DR.trend_from_points(pts) == (0.0, 7)
    r = DR.assess(average=3.3, trend_delta=DR.trend_from_points(pts)[0], trend_points=7)
    assert not [f for f in r["factors"] if f["code"] == "trend"]


def test_several_grades_of_one_day_count_as_one_day():
    """Шесть работ, проверенных в один день, не весят вшестеро: наблюдение — учебный день."""
    import datetime as dt
    d0 = dt.date(2026, 9, 1)
    pts = [(d0, 2)] * 6 + [(d0 + dt.timedelta(days=7 * i), 5 - (i - 1) * 0.5) for i in range(1, 5)]
    slope, n = DR.trend_from_points(pts)
    assert n == 5, "учебных дней пять, а не десять оценок"
    #Средние по дням: 2, 5, 4.5, 4, 3.5 — после первого дня ровное падение.
    assert slope is not None


# ── Сдвиг уровня (Петтитт) и тревоги всей системы (21.10.2026, разбор Ярослава) ────────

def test_abrupt_drop_names_the_date():
    pts = _weekly([5, 5, 4, 5, 5, 5, 3, 3, 2, 3, 3, 3])
    shift = DR.shift_from_points(pts)
    assert shift is not None and shift["date"] == pts[6][0], shift
    r = DR.assess(average=3.8, trend_shift=shift, trend_delta=-1.0, trend_points=12)
    f = [f for f in r["factors"] if f["code"] == "trend"]
    assert len(f) == 1, "одно падение не считается дважды"
    assert f"С {pts[6][0]:%d.%m}" in f[0]["detail"]


def test_short_history_and_a_recovered_dip_do_not_alarm():
    #Восемь дней идеальной ступеньки — p ещё не дотягивает: тест на коротком ряду молчит.
    assert DR.shift_from_points(_weekly([5, 5, 5, 5, 3, 3, 3, 3])) is None
    #Несколько переломов: провал значим сам по себе (p < 0.05), но студент из него
    #выбрался — последние дни на прежнем уровне, тревожить незачем.
    import estimators
    dip = [5] * 8 + [2] * 10 + [5] * 3
    assert estimators.pettitt(dip)["p"] < 0.05
    assert DR.shift_from_points(_weekly(dip, step=4)) is None


def _simulated(rnd, drop=0.0, gradual=0.0):
    import datetime as dt
    mu = rnd.uniform(2.9, 4.7)
    d0 = dt.date(2026, 9, 1)
    days = sorted(rnd.sample(range(120), rnd.randint(8, 30)))
    mid = days[len(days) // 2]
    out = []
    for d in days:
        level = mu - (drop if d >= mid else 0) - gradual * d / 30
        for _ in range(rnd.choice((1, 1, 2, 3))):
            out.append((d0 + dt.timedelta(days=d), max(2, min(5, round(level + rnd.gauss(0, 0.8))))))
    return out


def _system_fires(pts):
    slope, _n = DR.trend_from_points(pts)
    return (slope is not None and slope <= -0.5) or DR.shift_from_points(pts) is not None


def test_false_alarm_rate_of_the_whole_warning_system():
    """Разбор Ярослава: тестов несколько (наклон, Манн — Кендалл, Петтитт), и проверять надо
    частоту ложных тревог ВСЕЙ связки. Моделирование: студенты без настоящего изменения
    (свой уровень 2.9–4.7, шум ±0.8 балла, 8–30 учебных дней за семестр, 1–3 оценки в
    день). Замер 21.10.2026 на 2000 студентах: 0.3 %. Держим не выше 2 %."""
    import random
    rnd = random.Random(2026)
    n = 1000
    rate = sum(_system_fires(_simulated(rnd)) for _ in range(n)) / n
    assert rate <= 0.02, f"ложных тревог {rate:.1%}"


def test_the_warning_system_is_not_deaf():
    """Обратная сторона: осторожность не должна превратиться в глухоту. Замер 21.10.2026:
    резкий спад на 1.5 балла ловится в 73.5 % случаев, плавное падение на балл в месяц —
    в 55.5 %. Пропуски — это короткие истории (8–10 дней), где тесты честно молчат."""
    import random
    rnd = random.Random(2026)
    n = 400
    abrupt = sum(_system_fires(_simulated(rnd, drop=1.5)) for _ in range(n)) / n
    gradual = sum(_system_fires(_simulated(rnd, gradual=1.0)) for _ in range(n)) / n
    assert abrupt >= 0.6 and gradual >= 0.45, (abrupt, gradual)
