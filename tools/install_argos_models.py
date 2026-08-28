# -*- coding: utf-8 -*-
"""
install_argos_models.py — поставить модели локального переводчика на машину сервера.

Зачем отдельный скрипт, а не строка в requirements. Модели весят сотни мегабайт и
качаются с индекса Argos; класть их в репозиторий нельзя (раздуют клон и уедут в
сборку), а тянуть автоматически при первом переводе — значит подвесить запрос человека
на несколько минут закачки. Ставим осознанно, один раз, руками.

    python tools/install_argos_models.py            # поставить недостающее
    python tools/install_argos_models.py --check    # только показать, что уже стоит

⚠️ ПАРЫ ВЫВОДЯТСЯ ИЗ `LANGUAGES` СЕРВЕРНОГО МОДУЛЯ, а не перечислены здесь руками.
Список в комментарии — это снимок значения, и он откажет ровно в тот день, когда в
продукт добавят четвёртый язык: скрипт молча поставит старый набор, перевод на новый
язык не заработает, и искать причину будут в чём угодно, только не здесь. Тот же урок,
что уже стоил нам отдельной сборки .exe со списком общих модулей.

⚠️ ПРЯМОЙ ПАРЫ ru↔zh У ARGOS НЕТ. Перевод между ними идёт пивотом через английский,
поэтому ставим не «все пары», а звезду вокруг английского: для каждого языка — пара
в обе стороны с `en`. Для трёх языков это четыре модели вместо шести.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "server"))


def _wanted_pairs():
    """Пары, которые нужны продукту: звезда вокруг языка-посредника."""
    from app.translate_service import LANGUAGES, _PIVOT
    pairs = []
    for code in LANGUAGES:
        if code == _PIVOT:
            continue
        pairs.append((code, _PIVOT))
        pairs.append((_PIVOT, code))
    return pairs


def _installed():
    import argostranslate.translate as at
    out = set()
    for a in at.get_installed_languages():
        for b in a.translations_from if hasattr(a, "translations_from") else []:
            out.add((a.code, b.to_lang.code))
    if out:
        return out
    #Запасной путь: у части версий состав связей читается только через get_translation.
    langs = {l.code: l for l in at.get_installed_languages()}
    for a in langs.values():
        for b in langs.values():
            if a.code == b.code:
                continue
            try:
                if a.get_translation(b):
                    out.add((a.code, b.code))
            except Exception:
                pass
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Модели локального переводчика Argos")
    ap.add_argument("--check", action="store_true", help="только показать состояние")
    args = ap.parse_args()

    try:
        import argostranslate.package as ap_pkg
        import argostranslate.translate  # noqa: F401
    except Exception as e:                          # noqa: BLE001
        print(f"нет пакета argostranslate ({e}) — поставьте: pip install argostranslate")
        return 2

    wanted = _wanted_pairs()
    have = _installed()
    print("нужно пар:", ", ".join(f"{a}->{b}" for a, b in wanted))
    print("уже стоит:", ", ".join(f"{a}->{b}" for a, b in sorted(have)) or "ничего")

    missing = [p for p in wanted if p not in have]
    if not missing:
        print("ГОТОВО: всё нужное установлено")
        return 0
    if args.check:
        print("НЕ ХВАТАЕТ:", ", ".join(f"{a}->{b}" for a, b in missing))
        return 1

    print("обновляю индекс пакетов…")
    ap_pkg.update_package_index()
    available = ap_pkg.get_available_packages()

    failed = []
    for src, dst in missing:
        found = next((p for p in available if p.from_code == src and p.to_code == dst), None)
        if found is None:
            #Молчать нельзя: отсутствующая пара означает, что перевод в эту сторону не
            #заработает, а выглядеть это будет как «переводчик сломался».
            print(f"  {src}->{dst}: НЕТ В КАТАЛОГЕ")
            failed.append((src, dst))
            continue
        print(f"  {src}->{dst}: качаю…", flush=True)
        try:
            ap_pkg.install_from_path(found.download())
        except Exception as e:                      # noqa: BLE001
            print(f"  {src}->{dst}: НЕ УСТАНОВЛЕНА ({e})")
            failed.append((src, dst))

    if failed:
        print("НЕ ВСЁ УСТАНОВЛЕНО:", ", ".join(f"{a}->{b}" for a, b in failed))
        return 1
    print("ГОТОВО")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
