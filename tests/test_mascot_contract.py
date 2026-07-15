"""
test_mascot_contract.py — Контракт выбора эмоции маскота (Python-сторона).

Пиннит vector.emotes.pick к общему golden-файлу docs/contracts/mascot-cases.json. Тот же
файл проверяет JS (web/tests/mascot.contract.test.mjs) → десктоп и веб выбирают одну и ту
же эмоцию на один и тот же (state, mood, intent). pick возвращает русский кортеж
(морда, жест); переводим его в английскую строку 'face-gesture' мостом из контракта.
"""
import json
from pathlib import Path

from vector.emotes import pick   # ВАЖНО: vector.emotes, иначе подхватится папка арта emotes/

_C = json.loads(
    (Path(__file__).resolve().parents[1] / "docs" / "contracts" / "mascot-cases.json")
    .read_text(encoding="utf-8")
)
_FACE, _GESTURE, _CASES = _C["face_map"], _C["gesture_map"], _C["pick"]


def _key(face: str, gesture: str) -> str:
    return f"{_FACE[face]}-{_GESTURE[gesture]}"


def test_pick_matches_contract():
    for c in _CASES:
        face, gesture = pick(c["state"], c["mood"], c["intent"])
        got = _key(face, gesture)
        assert got == c["expected"], (
            f"pick({c['state']!r}, {c['mood']!r}, {c['intent']!r}) = {got}, "
            f"ожидалось {c['expected']}")


def test_maps_cover_all_faces_and_gestures():
    #Гард: мост должен покрывать ВСЕ морды/жесты (иначе новая эмоция «провалится» молча).
    import vector.emotes as emotes
    assert set(emotes.FACES) <= set(_FACE), "face_map не покрывает все морды"
    assert set(emotes.GESTURES) <= set(_GESTURE), "gesture_map не покрывает все жесты"
