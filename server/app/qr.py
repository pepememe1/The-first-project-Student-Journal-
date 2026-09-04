# -*- coding: utf-8 -*-
"""qr.py — QR-код своими руками, на чистой стандартной библиотеке.

━━ ЗАЧЕМ ОН НУЖЕН И ГДЕ ИМЕННО ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Второй фактор заводится переносом строки `otpauth://…` в приложение-аутентификатор.
Способов ровно два, и они НЕ взаимозаменяемы:
  • НА ТЕЛЕФОНЕ правильный способ — открыть ту же ссылку прямо на устройстве:
    Google Authenticator перехватывает схему `otpauth://` и заводит запись сам.
    QR-код здесь бесполезен и даже вреден — чтобы снять код со своего же экрана,
    нужен ВТОРОЙ телефон (замечание Ярослава 02.09.2026);
  • НА КОМПЬЮТЕРЕ ссылку открывать нечем: аутентификатор живёт на телефоне.
    Остаётся либо переписать секрет из тридцати двух символов руками, либо снять
    QR-код с экрана монитора. Первое люди делают с опечатками.

Поэтому кодировщик существует ради ОДНОГО случая — настройки за компьютером.
Какой из двух путей показать, решает клиент по устройству (`MfaCard.vue`).

━━ ПОЧЕМУ НЕ БИБЛИОТЕКА И НЕ ВНЕШНИЙ СЕРВИС ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔒 Сервис-генератор QR (`api.qrserver.com` и подобные) отпадает СРАЗУ и не по
   вкусовым причинам: в картинку кодируется СЕКРЕТ ВТОРОГО ФАКТОРА, и запрос к
   такому сервису — это отправка секрета третьей стороне, притом иностранной
   (п. 5.6.1 политики ВСГУТУ: трансграничной передачи нет). Второй фактор,
   который по дороге показали чужому серверу, — не второй фактор.
📦 Библиотека (`qrcode`, `segno`) — ещё один пакет в поставке, ещё одна строка в
   SBOM и ещё один вопрос на приёмке в реестр Минцифры. Ровно тот же довод, по
   которому у нас свой TOTP на сорок строк вместо `pyotp` (см. totp.py).

Здесь около трёхсот строк по стандарту ISO/IEC 18004, который не менялся с 2006
года. Это не «изобретение своего»: алгоритм фиксированный, а его правильность
проверяется целиком — сторож читает получившуюся матрицу обратно в строку.

━━ ГРАНИЦЫ, СОЗНАТЕЛЬНО СУЖЕННЫЕ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Кодируем ТОЛЬКО в байтовом режиме и ТОЛЬКО с уровнем коррекции M, версии 1–10
(до 213 байт). Наша строка `otpauth://` — около 140 байт, то есть запас больше
чем полуторный. Полная таблица версий 1–40 добавила бы сотню строк данных,
которые никогда не исполнятся, и опечатка в них была бы невидимой. Не влезло —
честное исключение, а не тихо испорченный код.

⚠️ Уровень M (~15 % восстановления), а не L: код снимают камерой телефона с
экрана монитора, под углом и с бликами. Разница в размере между L и M у нас
одна версия, а разница в читаемости заметная.

⚠️ Наружу отдаём НЕ картинку, а размер и `d` для одного `<path>`. Причина не в
экономии: SVG-строку с сервера пришлось бы вставлять через `v-html`, то есть
завести в продукте место, где сервер вставляет разметку в страницу. `d`
подставляется атрибутом (`:d`), и разметку туда не протащить по построению.
"""

from __future__ import annotations

# ─────────────────────────────────────────────────────────────────────────────────
# Поле Галуа GF(256) — арифметика кодов Рида–Соломона.
# Примитивный многочлен 0x11D задан стандартом; менять его нельзя.
# ─────────────────────────────────────────────────────────────────────────────────
_EXP = [0] * 512
_LOG = [0] * 256


def _init_tables() -> None:
    x = 1
    for i in range(255):
        _EXP[i] = x
        _LOG[x] = i
        x <<= 1
        if x & 0x100:
            x ^= 0x11D
    for i in range(255, 512):
        _EXP[i] = _EXP[i - 255]


_init_tables()


def _rs_generator(degree: int) -> list[int]:
    """Порождающий многочлен кода Рида–Соломона нужной степени."""
    poly = [1]
    for i in range(degree):
        # Умножение на (x - a^i); в GF(2) вычитание — то же сложение по модулю два.
        nxt = [0] * (len(poly) + 1)
        for j, coef in enumerate(poly):
            nxt[j] ^= coef
            if coef:
                nxt[j + 1] ^= _EXP[(_LOG[coef] + i) % 255]
        poly = nxt
    return poly


def _ecc(data: list[int], count: int) -> list[int]:
    """Проверочные байты одного блока."""
    gen = _rs_generator(count)
    res = list(data) + [0] * count
    for i in range(len(data)):
        coef = res[i]
        if coef:
            lc = _LOG[coef]
            for j, g in enumerate(gen):
                if g:
                    res[i + j] ^= _EXP[_LOG[g] + lc]
    return res[len(data):]


# ─────────────────────────────────────────────────────────────────────────────────
# Таблица блоков для уровня коррекции M, версии 1–10.
# (проверочных байт на блок, [(сколько блоков, данных в блоке), …])
#
# ⚠️ Числа из таблицы 9 стандарта. Глазами их не проверить, поэтому `matrix()`
# сверяет получившуюся длину с общим числом кодовых слов версии: опечатка здесь
# иначе испортила бы код молча, и узнали бы мы об этом от человека с телефоном.
# ─────────────────────────────────────────────────────────────────────────────────
_ECC_M: dict[int, tuple[int, list[tuple[int, int]]]] = {
    1: (10, [(1, 16)]),
    2: (16, [(1, 28)]),
    3: (26, [(1, 44)]),
    4: (18, [(2, 32)]),
    5: (24, [(2, 43)]),
    6: (16, [(4, 27)]),
    7: (18, [(4, 31)]),
    8: (22, [(2, 38), (2, 39)]),
    9: (22, [(3, 36), (2, 37)]),
    10: (26, [(4, 43), (1, 44)]),
}

# Центры выравнивающих узоров по версиям (таблица E.1 стандарта).
_ALIGN: dict[int, list[int]] = {
    1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30],
    6: [6, 34], 7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50],
}

MAX_VERSION = 10
ECL_BITS_M = 0b00        # уровень коррекции M в битах формата


def total_codewords(version: int) -> int:
    ec, groups = _ECC_M[version]
    return sum(n * (d + ec) for n, d in groups)


def data_codewords(version: int) -> int:
    return sum(n * d for n, d in _ECC_M[version][1])


def count_bits(version: int) -> int:
    """Длина поля «сколько байт»: 8 бит до версии 9, дальше 16."""
    return 8 if version <= 9 else 16


def pick_version(length: int) -> int:
    for v in range(1, MAX_VERSION + 1):
        if data_codewords(v) * 8 - 4 - count_bits(v) >= length * 8:
            return v
    raise ValueError(
        f"строка длиной {length} байт не помещается в QR версии {MAX_VERSION}. "
        "Это не «надо расширить таблицу»: у otpauth-ссылки размер около 140 байт, "
        "и такой перебор означает, что кодируется не то, что задумано.")


# ─────────────────────────────────────────────────────────────────────────────────
# Поток данных
# ─────────────────────────────────────────────────────────────────────────────────

def _bitstream(payload: bytes, version: int) -> list[int]:
    bits: list[int] = []

    def push(value: int, width: int) -> None:
        for i in range(width - 1, -1, -1):
            bits.append((value >> i) & 1)

    push(0b0100, 4)                       # режим «байты»
    push(len(payload), count_bits(version))
    for byte in payload:
        push(byte, 8)

    capacity = data_codewords(version) * 8
    # Ограничитель: до четырёх нулей, но не больше, чем осталось места.
    push(0, min(4, capacity - len(bits)))
    while len(bits) % 8:                  # добиваем до целого байта
        bits.append(0)

    words = [int("".join(str(b) for b in bits[i:i + 8]), 2)
             for i in range(0, len(bits), 8)]
    # Набивка чередующимися 0xEC/0x11 — так велит стандарт. Произвольные байты
    # сдвинули бы долю тёмных модулей и ухудшили распознавание.
    pad = (0xEC, 0x11)
    i = 0
    while len(words) < data_codewords(version):
        words.append(pad[i % 2])
        i += 1
    return words


def _interleave(words: list[int], version: int) -> list[int]:
    """Разложить данные по блокам, посчитать коррекцию и перемешать по стандарту.

    Перемешивание не украшение: оно разносит каждый блок по всей площади кода,
    и пятно на экране портит по несколько байт КАЖДОГО блока вместо того, чтобы
    убить один блок целиком. Без него код перестаёт восстанавливаться от блика.
    """
    ec_count, groups = _ECC_M[version]
    blocks: list[list[int]] = []
    pos = 0
    for count, size in groups:
        for _ in range(count):
            blocks.append(words[pos:pos + size])
            pos += size
    eccs = [_ecc(b, ec_count) for b in blocks]

    out: list[int] = []
    for i in range(max(len(b) for b in blocks)):
        for b in blocks:
            if i < len(b):
                out.append(b[i])
    for i in range(ec_count):
        for e in eccs:
            out.append(e[i])
    return out


# ─────────────────────────────────────────────────────────────────────────────────
# Матрица
# ─────────────────────────────────────────────────────────────────────────────────

MASKS = (
    lambda x, y: (x + y) % 2 == 0,
    lambda x, y: y % 2 == 0,
    lambda x, y: x % 3 == 0,
    lambda x, y: (x + y) % 3 == 0,
    lambda x, y: (x // 3 + y // 2) % 2 == 0,
    lambda x, y: x * y % 2 + x * y % 3 == 0,
    lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
    lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0,
)


class _Canvas:
    def __init__(self, version: int):
        self.version = version
        self.size = 17 + 4 * version
        self.m = [[False] * self.size for _ in range(self.size)]
        # Служебные модули маской НЕ накрываются и данными не перезаписываются.
        self.fixed = [[False] * self.size for _ in range(self.size)]

    def _set(self, row: int, col: int, dark: bool) -> None:
        self.m[row][col] = dark
        self.fixed[row][col] = True

    def draw_function_patterns(self) -> None:
        size = self.size
        # Поисковые узоры вместе с отступами.
        for r0, c0 in ((0, 0), (0, size - 7), (size - 7, 0)):
            for dr in range(-1, 8):
                for dc in range(-1, 8):
                    r, c = r0 + dr, c0 + dc
                    if not (0 <= r < size and 0 <= c < size):
                        continue
                    inside = 0 <= dr <= 6 and 0 <= dc <= 6
                    dark = inside and (dr in (0, 6) or dc in (0, 6)
                                       or (2 <= dr <= 4 and 2 <= dc <= 4))
                    self._set(r, c, dark)

        # Синхрополосы.
        for i in range(8, size - 8):
            self._set(6, i, i % 2 == 0)
            self._set(i, 6, i % 2 == 0)

        # Выравнивающие узоры — везде, кроме углов, занятых поисковыми.
        centers = _ALIGN[self.version]
        last = centers[-1] if centers else 0
        for r in centers:
            for c in centers:
                if (r == 6 and c == 6) or (r == 6 and c == last) or (r == last and c == 6):
                    continue
                for dr in range(-2, 3):
                    for dc in range(-2, 3):
                        self._set(r + dr, c + dc, max(abs(dr), abs(dc)) != 1)

        # Область формата резервируем; значения впишем после выбора маски.
        # ⚠️ Индекс 6 ПРОПУСКАЕМ: там проходит синхрополоса, и запись сюда стёрла бы
        # её посередине. Отказ был бы тихим — код рисуется, выглядит как настоящий,
        # а камера не находит сетку и не читает вообще ничего.
        for i in range(9):
            if i == 6:
                continue
            self._set(8, i, False)
            self._set(i, 8, False)
        for i in range(8):
            self._set(8, size - 1 - i, False)
            self._set(size - 1 - i, 8, False)
        self._set(size - 8, 8, True)      # всегда тёмный модуль

        if self.version >= 7:
            rem = self.version
            for _ in range(12):
                rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
            bits = (self.version << 12) | rem
            for i in range(18):
                bit = (bits >> i) & 1 == 1
                a, b = size - 11 + i % 3, i // 3
                self._set(b, a, bit)
                self._set(a, b, bit)

    def draw_codewords(self, words: list[int]) -> None:
        size = self.size
        i, total = 0, len(words) * 8
        for right in range(size - 1, 0, -2):
            # ⚠️ Шестая колонка занята синхрополосой, поэтому ВСЕ пары левее неё
            # сдвигаются на единицу — не только та, что на неё попала. Условие
            # `right == 6` (первая версия этой строки) сдвигало ровно одну пару, и
            # дальше колонки шли внахлёст: 4-я и 3-я заполнялись дважды, а нулевая
            # не заполнялась НИКОГДА. Код при этом рисуется целиком и выглядит
            # настоящим — не читается только телефоном.
            if right <= 6:
                right -= 1
            for vert in range(size):
                for j in range(2):
                    col = right - j
                    upward = ((right + 1) & 2) == 0
                    row = (size - 1 - vert) if upward else vert
                    if not self.fixed[row][col] and i < total:
                        self.m[row][col] = (words[i >> 3] >> (7 - (i & 7))) & 1 == 1
                        i += 1

    def apply_mask(self, mask: int) -> None:
        rule = MASKS[mask]
        for row in range(self.size):
            for col in range(self.size):
                if not self.fixed[row][col] and rule(col, row):
                    self.m[row][col] = not self.m[row][col]

    def draw_format(self, mask: int) -> None:
        data = (ECL_BITS_M << 3) | mask
        rem = data
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        bits = ((data << 10) | rem) ^ 0x5412

        def bit(i: int) -> bool:
            return (bits >> i) & 1 == 1

        size = self.size
        for i in range(6):
            self._set(i, 8, bit(i))
        self._set(7, 8, bit(6))
        self._set(8, 8, bit(7))
        self._set(8, 7, bit(8))
        for i in range(9, 15):
            self._set(8, 14 - i, bit(i))
        for i in range(8):
            self._set(8, size - 1 - i, bit(i))
        for i in range(8, 15):
            self._set(size - 15 + i, 8, bit(i))
        self._set(size - 8, 8, True)

    def penalty(self) -> int:
        """Штраф раскладки. Чем меньше, тем легче камере отличить код от фона."""
        size, m = self.size, self.m
        lines = [list(r) for r in m] + [list(c) for c in zip(*m)]
        score = 0
        # Правило 1: длинные одноцветные полосы.
        for line in lines:
            run, prev = 1, line[0]
            for cell in line[1:]:
                if cell == prev:
                    run += 1
                else:
                    if run >= 5:
                        score += 3 + (run - 5)
                    run, prev = 1, cell
            if run >= 5:
                score += 3 + (run - 5)
        # Правило 2: одноцветные квадраты 2×2.
        for r in range(size - 1):
            for c in range(size - 1):
                if m[r][c] == m[r][c + 1] == m[r + 1][c] == m[r + 1][c + 1]:
                    score += 3
        # Правило 3: узор, который камера спутает с поисковым.
        p1 = [True, False, True, True, True, False, True, False, False, False, False]
        p2 = list(reversed(p1))
        for line in lines:
            for i in range(size - 10):
                window = line[i:i + 11]
                if window == p1 or window == p2:
                    score += 40
        # Правило 4: перекос доли тёмных модулей от половины.
        dark = sum(1 for row in m for cell in row if cell)
        total = size * size
        score += (abs(dark * 100 // total - 50) // 5) * 10
        return score


def matrix(text: str) -> list[list[bool]]:
    """Матрица модулей БЕЗ полей вокруг. True — тёмный."""
    payload = text.encode("utf-8")
    version = pick_version(len(payload))
    words = _interleave(_bitstream(payload, version), version)
    if len(words) != total_codewords(version):
        # Не assert: с ключом -O проверки исчезают, а испорченный код молча уедет
        # человеку на экран, и разбираться он будет с телефоном, а не с нами.
        raise RuntimeError(
            f"кодовых слов {len(words)}, а версия {version} требует "
            f"{total_codewords(version)} — опечатка в таблице _ECC_M")

    best, best_score = None, None
    for mask in range(8):
        canvas = _Canvas(version)
        canvas.draw_function_patterns()
        canvas.draw_codewords(words)
        canvas.apply_mask(mask)
        canvas.draw_format(mask)
        score = canvas.penalty()
        if best_score is None or score < best_score:
            best, best_score = canvas, score
    return best.m


# Поле вокруг кода. Стандарт требует четыре модуля: без него камера не находит
# границу, и код «не читается» без единого признака ошибки.
QUIET_ZONE = 4


def svg_path(text: str, quiet: int = QUIET_ZONE) -> tuple[int, str]:
    """(сторона в модулях вместе с полями, содержимое `d` для одного `<path>`).

    Соседние тёмные модули в строке склеиваются в один прямоугольник: иначе на
    сорока модулях выходит под тысячу команд, и строка весит больше страницы.
    """
    m = matrix(text)
    size = len(m)
    parts: list[str] = []
    for r, row in enumerate(m):
        c = 0
        while c < size:
            if not row[c]:
                c += 1
                continue
            start = c
            while c < size and row[c]:
                c += 1
            parts.append(f"M{start + quiet} {r + quiet}h{c - start}v1h-{c - start}z")
    return size + 2 * quiet, "".join(parts)
