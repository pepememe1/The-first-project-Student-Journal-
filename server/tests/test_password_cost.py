"""
test_password_cost.py — дешёвый хеш живёт ТОЛЬКО в прогоне, боевой не тронут (17.10.2026).

`conftest.py` опускает итерации SHA-512 до тысячи: на 200 000 один хеш стоит 0.18 с, и
львиная доля серверного прогона уходила на заведение и вход тестовых людей. Подмена
безопасна только при двух условиях, и оба проверяются здесь:

  • боевая стоимость в ИСХОДНИКЕ прежняя — читаем файл, а не подменённый модуль: модуль
    в прогоне уже подменён, и сверка с ним была бы сверкой копии с копией;
  • формат хеша самоописываемый — проверка берёт число итераций из самого хеша, поэтому
    боевой хеш (200 000) проверяется тем же кодом, что и тестовый.

⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН: поставь в `security.py` `_SHA_ITERS = 1_000` — первый тест
краснеет; заставь `verify_password` брать итерации из модуля, а не из хеша — второй.
"""
import ast
import pathlib

SECURITY = pathlib.Path(__file__).resolve().parents[1] / "app" / "security.py"
PROD_SHA_ITERS = 200_000


def _source_constant(name: str) -> int:
    tree = ast.parse(SECURITY.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"в security.py нет константы {name}")


def test_production_hash_cost_is_unchanged_in_the_source():
    assert _source_constant("_SHA_ITERS") >= PROD_SHA_ITERS, (
        "боевая стоимость хеша пароля снижена в исходнике — это ослабляет защиту "
        "украденной базы от перебора, а не только ускоряет тесты")


def test_cheap_test_hash_and_production_hash_share_one_verifier():
    from app import security
    cheap = security.hash_password("пароль-1")
    assert cheap.split("$")[1].startswith(f"{security._SHA_ITERS}-")
    assert security._SHA_ITERS < PROD_SHA_ITERS, "conftest больше не удешевляет хеш"

    saved = security._SHA_ITERS
    security._SHA_ITERS = PROD_SHA_ITERS
    try:
        prod = security.hash_password("пароль-1")
    finally:
        security._SHA_ITERS = saved
    assert prod.split("$")[1].startswith(f"{PROD_SHA_ITERS}-")
    #Оба проверяются ОДНИМ кодом при подменённой константе: итерации — из хеша.
    assert security.verify_password("пароль-1", cheap)
    assert security.verify_password("пароль-1", prod)
    assert not security.verify_password("другой", prod)
