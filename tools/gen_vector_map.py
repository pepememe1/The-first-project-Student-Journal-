# -*- coding: utf-8 -*-
"""
gen_vector_map.py — пересобрать КАРТУ ОТВЕТОВ ВЕКТОРА.

    py -3.11 -X utf8 tools/gen_vector_map.py          пересобрать и показать, что изменилось
    py -3.11 -X utf8 tools/gen_vector_map.py --check  только сверить (код выхода 1 — разошлось)

Карта — `docs/contracts/vector-map.json` и её читаемый вид `docs/contracts/VECTOR-MAP.md`:
каждый вопрос каждой роли на выдуманном колледже, как он понят и чем отвечено. Собирает
её не этот файл, а тот же код, что её сверяет (`server/tests/test_vector_map.py` с
`GB_WRITE_VECTOR_MAP=1`): два сборщика разошлись бы молча, и карта перестала бы
совпадать с собой же.

Как читать после обновления Вектора: запусти, затем `git diff docs/contracts/VECTOR-MAP.md`.
Изменившаяся строка называет роль, вопрос и новый ответ. Ожидал — коммить вместе с
правкой; не ожидал — это и есть поломка, и карта её нашла.

⚠️ Сборка поднимает тестовую базу, общую для всех прогонов pytest на машине. Не запускать,
пока идёт другой pytest.
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(ROOT, "server")
FILES = ["docs/contracts/vector-map.json", "docs/contracts/VECTOR-MAP.md"]


def _pytest(write: bool) -> int:
    env = dict(os.environ)
    env.pop("GB_WRITE_VECTOR_MAP", None)
    if write:
        env["GB_WRITE_VECTOR_MAP"] = "1"
    cmd = [sys.executable, "-X", "utf8", "-m", "pytest", "tests/test_vector_map.py", "-q",
           "-p", "no:warnings", "--tb=short"]
    if write:
        cmd += ["-k", "the_map_matches_the_one_in_the_repository", "-s"]
    return subprocess.run(cmd, cwd=SERVER, env=env).returncode


def main() -> int:
    if "--check" in sys.argv[1:]:
        return 1 if _pytest(write=False) else 0
    if _pytest(write=True):
        print("Карта НЕ собрана: сборка упала, файлы могли остаться прежними.")
        return 1
    #Свойства (маршруты по ролям, чужие данные, фамилии в модель, числа) — на свежей карте.
    code = _pytest(write=False)
    try:
        diff = subprocess.run(["git", "diff", "--stat", "--"] + FILES, cwd=ROOT,
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace").stdout.strip()
    except OSError:
        diff = ""
    print("\nИзменилось против git:\n" + diff if diff else
          "\nКарта совпадает с лежащей в git (либо ещё не добавлена в него).")
    if code:
        print("\nКарта записана, но СВОЙСТВА красные — см. вывод выше: это не «обновить "
              "карту», а расхождение с требованиями.")
    return 1 if code else 0


if __name__ == "__main__":
    sys.exit(main())
