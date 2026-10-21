"""Формулы `estimators.py` — ответы сверены с источниками (исследование 20.10.2026).

Тест зовёт функции ПРОДУКТА и сверяет их с числами, посчитанными вручную по формуле
из первоисточника, а не повторяет формулу у себя (иначе он сверял бы копию с копией).
У каждой формулы — проверка того свойства, ради которого её взяли: там, где голая доля
или голое среднее врут, формула обязана вести себя иначе."""
import math

import pytest

import estimators as E


# ── Уилсон ──────────────────────────────────────────────────────────────────────────

def test_wilson_two_of_two_is_not_certainty():
    lo, hi = E.wilson_interval(2, 2)
    assert lo == pytest.approx(0.3424, abs=1e-4)
    assert hi == pytest.approx(1.0)


def test_wilson_57_of_60():
    lo, hi = E.wilson_interval(57, 60)
    assert lo == pytest.approx(0.8630, abs=1e-3)
    assert hi == pytest.approx(0.9829, abs=1e-3)


def test_wilson_orders_by_evidence_not_by_raw_share():
    """Ради этого формулу и взяли: по голой доле «2 из 2» выше «57 из 60», по нижней
    границе — наоборот. Обратный ход: голая доля даёт неверный порядок."""
    assert 2 / 2 > 57 / 60
    assert E.wilson_lower(57, 60) > E.wilson_lower(2, 2)


def test_wilson_degenerate_inputs():
    assert E.wilson_interval(0, 0) == (0.0, 1.0)
    assert E.wilson_lower(0, 10) == 0.0
    assert E.wilson_interval(15, 10)[1] == pytest.approx(1.0)   # k > n — обрезается


# ── Лаплас и сглаживание ────────────────────────────────────────────────────────────

def test_laplace_rule_of_succession():
    assert E.laplace_rate(1, 1) == pytest.approx(2 / 3)
    assert E.laplace_rate(0, 1) == pytest.approx(1 / 3)
    assert E.laplace_rate(0, 0) == pytest.approx(0.5)


def test_shrunk_share_pulls_small_samples_only():
    one_of_one = E.shrunk_share(1, 1, prior_share=0.1, prior_weight=4)
    assert one_of_one == pytest.approx(0.28)
    many = E.shrunk_share(50, 100, prior_share=0.1, prior_weight=4)
    assert many == pytest.approx(50.4 / 104)
    #Свойство: чем больше данных, тем ближе к голой доле.
    assert abs(many - 0.5) < abs(one_of_one - 1.0)


def test_shrunk_mean_single_two_is_not_failure():
    #Одна двойка при среднем группы 3.8 и весе 5 — это 3.5, а не «ниже 2.5».
    assert E.shrunk_mean(2.0, 1, prior_mean=3.8, prior_weight=5) == pytest.approx(3.5)
    assert E.shrunk_mean(2.0, 40, prior_mean=3.8, prior_weight=5) == pytest.approx(
        (80 + 19) / 45)
    assert E.shrunk_mean(0.0, 0, prior_mean=3.8, prior_weight=5) == pytest.approx(3.8)


# ── Тейл — Сен ──────────────────────────────────────────────────────────────────────

def test_theil_sen_exact_line():
    assert E.theil_sen_slope([(t, 2 * t + 1) for t in range(6)]) == pytest.approx(2.0)


def test_theil_sen_ignores_single_outlier_where_least_squares_does_not():
    """Четыре четвёрки и одна двойка в конце: тренда нет, есть одна неудача.
    Наименьшие квадраты дают −0.4 балла за шаг (ложная тревога), Тейл — Сен — 0."""
    pts = [(0, 4), (1, 4), (2, 4), (3, 4), (4, 2)]
    ts = [t for t, _ in pts]
    ys = [y for _, y in pts]
    mt, my = sum(ts) / 5, sum(ys) / 5
    ols = (sum((t - mt) * (y - my) for t, y in pts) / sum((t - mt) ** 2 for t in ts))
    assert ols == pytest.approx(-0.4)
    assert E.theil_sen_slope(pts) == pytest.approx(0.0)


def test_theil_sen_needs_two_distinct_times():
    assert E.theil_sen_slope([]) is None
    assert E.theil_sen_slope([(1, 5), (1, 2)]) is None


# ── Холт ────────────────────────────────────────────────────────────────────────────

def test_holt_on_a_straight_line_keeps_level_and_slope():
    level, trend = E.holt_forecast([(t, 10 + 2 * t) for t in range(6)])
    assert level == pytest.approx(20.0)
    assert trend == pytest.approx(2.0)


def test_holt_handles_skipped_days():
    level, trend = E.holt_forecast([(0, 0), (1, 3), (4, 12), (5, 15)])
    assert trend == pytest.approx(3.0)
    assert level == pytest.approx(15.0)


def test_holt_too_short():
    assert E.holt_forecast([(0, 1)]) is None


# ── Бернулли ────────────────────────────────────────────────────────────────────────

def test_two_outcome_sum_is_bernoulli_formula():
    """Свёртка для двух исходов обязана совпасть с формулой Бернулли:
    C(5,3)·0.4³·0.6² + C(5,4)·0.4⁴·0.6 + 0.4⁵ = 0.31744."""
    dist = E.sum_distribution({0: 0.6, 1: 0.4}, 5)
    assert sum(p for s, p in dist.items() if s >= 3) == pytest.approx(0.31744)
    assert sum(dist.values()) == pytest.approx(1.0)


def test_laplace_distribution_never_says_impossible():
    probs = E.value_distribution([5, 5])
    assert probs[5] == pytest.approx(3 / 6)
    assert probs[3] == pytest.approx(1 / 6), "тройка не стала невозможной из-за двух пятёрок"
    assert sum(probs.values()) == pytest.approx(1.0)
    assert E.value_distribution([2.0, 4.6])[5] == pytest.approx(2 / 6)   # 4.6 ≈ 5


def test_chance_mean_at_least():
    #Средний 4.0 по 4 оценкам, впереди 4 работы, цель 4.5: нужны все четыре пятёрки.
    sure_five = {5: 1.0}
    assert E.chance_mean_at_least(16, 4, sure_five, 4, 4.5) == pytest.approx(1.0)
    half = {4: 0.5, 5: 0.5}
    assert E.chance_mean_at_least(16, 4, half, 4, 4.5) == pytest.approx(0.5 ** 4)
    assert E.chance_mean_at_least(16, 4, half, 0, 4.5) == 0.0   # работ не осталось
    assert E.chance_mean_at_least(19, 4, half, 0, 4.5) == 1.0   # цель уже достигнута


def test_grades_needed_is_exact_arithmetic():
    #Средний 4.0 по четырём оценкам; до 4.5 нужно четыре пятёрки: (16+20)/8 = 4.5.
    assert E.grades_needed(16, 4, 4.5) == 4
    #Три пятёрки не хватает: (16+15)/7 = 4.43.
    assert (16 + 15) / 7 < 4.5
    assert E.grades_needed(19, 4, 4.5) == 0          # уже 4.75
    assert E.grades_needed(16, 4, 5.0) is None       # пятёрками до 5.0 не дотянуть
    assert E.grades_needed(0, 0, 4.5) == 1           # оценок нет — средним станет первая


# ── Квантиль ────────────────────────────────────────────────────────────────────────

def test_p99_of_256_samples_is_a_range_not_a_point():
    lo, hi = E.quantile_rank_interval(256, 0.99)
    assert (lo, hi) == (249, 255)
    lo, hi = E.quantile_rank_interval(10000, 0.5)
    assert hi - lo < 0.03 * 10000                    # при большом n интервал узкий


# ── Психометрия ─────────────────────────────────────────────────────────────────────

def test_pearson_basic_and_undefined():
    assert E.pearson([1, 2, 3], [2, 4, 6]) == pytest.approx(1.0)
    assert E.pearson([1, 1, 1], [1, 2, 3]) is None


def test_cronbach_alpha_textbook_matrix():
    m = [[1, 1, 1], [1, 1, 0], [1, 0, 0], [0, 0, 0]]
    res = E.item_analysis(m, [1, 1, 1])
    assert res["alpha"] == pytest.approx(0.75)
    assert [round(i["facility"], 2) for i in res["items"]] == [0.75, 0.5, 0.25]


def test_wrong_answer_key_shows_negative_discrimination():
    """Ради этого анализ и заведён: сильные отвечают на вопрос «неверно», слабые —
    «верно». Так выглядит вопрос, у которого перепутан правильный ответ."""
    m = [
        [1, 1, 1, 0],
        [1, 1, 1, 0],
        [1, 1, 0, 1],
        [0, 0, 0, 1],
        [0, 0, 0, 1],
    ]
    items = E.item_analysis(m, [1, 1, 1, 1])["items"]
    assert items[0]["discrimination"] > 0.5
    assert items[3]["discrimination"] < 0


def test_question_everyone_answers_has_no_discrimination():
    items = E.item_analysis([[1, 1], [1, 0], [1, 1]], [1, 1])["items"]
    assert items[0]["facility"] == pytest.approx(1.0)
    assert items[0]["discrimination"] is None


def test_module_is_pure_stdlib():
    import ast
    import pathlib
    tree = ast.parse(pathlib.Path(E.__file__).read_text(encoding="utf-8"))
    mods = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import)
            for a in n.names}
    mods |= {n.module.split(".")[0] for n in ast.walk(tree)
             if isinstance(n, ast.ImportFrom) and n.module}
    assert mods <= {"math", "collections", "__future__"}, mods
    assert math.isclose(E.Z95, 1.96, abs_tol=1e-3)


def test_mann_kendall_matches_hand_calculation():
    """S, Var с поправкой на совпадения и Z — сверены вручную (21.10.2026)."""
    r = E.mann_kendall([(0, 5), (10, 5), (20, 5), (30, 2)])
    assert (r["s"], r["var"]) == (-3, 5.0) and round(r["z"], 4) == -0.8944
    r = E.mann_kendall([(0, 4), (1, 3), (2, 2), (3, 1)])
    assert r["s"] == -6 and r["tau_b"] == -1.0 and r["z"] < -E.Z95_ONE_SIDED
    #Меньше четырёх точек — судить не о чем.
    assert E.mann_kendall([(0, 5), (1, 2), (2, 1)])["z"] == 0.0



def test_pettitt_rank_formula_equals_the_definition():
    """U_t через ранги обязан совпадать с определением Σ sgn(x_i − x_j) — на рядах с
    совпадениями, где средние ранги легко посчитать неверно."""
    import random
    rnd = random.Random(1)
    for _ in range(300):
        xs = [rnd.choice([2, 3, 4, 5]) for _ in range(rnd.randint(2, 20))]
        best = max(((t, sum((xs[i] > xs[j]) - (xs[i] < xs[j]) for i in range(t)
                            for j in range(t, len(xs)))) for t in range(1, len(xs))),
                   key=lambda p: (p[1], -p[0]))
        r = E.pettitt(xs)
        if best[1] > 0:
            assert (r["t"], r["k"]) == (best[0], float(best[1])), (xs, r, best)
        else:
            assert r["p"] == 1.0


def test_pettitt_is_cautious_on_short_series_with_ties():
    """Совпадения уменьшают K — приближённое p осторожное: восемь дней «5,5,5,5,3,3,3,3»
    ещё не доказательство, двенадцать — уже да."""
    assert E.pettitt([5] * 4 + [3] * 4)["p"] > 0.05
    r = E.pettitt([5] * 6 + [3] * 6)
    assert r["t"] == 6 and r["p"] < 0.05
