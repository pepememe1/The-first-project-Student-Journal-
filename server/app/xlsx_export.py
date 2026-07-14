"""
xlsx_export.py — сборка журнала и ведомости в xlsx (веб).

ЕДИНЫЙ стиль десктопа и веба (по требованию заказчика): весь текст Times New Roman 14,
БЕЗ цветов (чёрный текст на белом), тонкие рамки, заголовки жирным, адаптивная ширина
столбцов (текст не обрезается). Официальный чёрно-белый вид, пригодный для печати.
Данные приходят уже выбранными по роли (routers/web.py): (group, subject, lessons, rows).
"""
import io
import re
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, Border, Side
from openpyxl.utils import get_column_letter

FNT = "Times New Roman"
SZ = 14                    #единый размер шрифта везде
_THIN = Side(style="thin", color="000000")
BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)


def _autofit(ws, ncols: int, rows: list, min_w=8, max_w=48):
    """Адаптивная ширина столбцов по содержимому (openpyxl сам не умеет auto-fit).
    Меряем ТОЛЬКО переданные строки (шапка+данные), без объединённых титульных —
    иначе длинный заголовок раздул бы все колонки. Для многострочных ячеек берём
    самую длинную строку. Times New Roman 14 шире — коэффициент 1.45."""
    for c in range(1, ncols + 1):
        best = 0
        for r in rows:
            v = ws.cell(row=r, column=c).value
            if v is None:
                continue
            best = max(best, max((len(s) for s in str(v).split("\n")), default=0))
        ws.column_dimensions[get_column_letter(c)].width = max(min_w, min(max_w, best * 1.45 + 2))


def _title(ws, row, last_col, text, size, bold=False, italic=False):
    ws.merge_cells(f"A{row}:{last_col}{row}")
    c = ws[f"A{row}"]
    c.value = text
    c.font = Font(name=FNT, size=size, bold=bold, italic=italic)
    c.alignment = Alignment(horizontal="center", vertical="center")


def build_journal_xlsx(group: str, subject: str, lessons, rows) -> bytes:
    """lessons — ORM-строки Lesson; rows — [{surname, name, records: {lid→оценка}, average}]."""
    wb = Workbook()
    ws = wb.active
    ws.title = re.sub(r'[\[\]:*?/\\]', '_', f"Успеваемость {group}")[:31]

    headers = ["Фамилия", "Имя"]
    keys = []
    for l in lessons:
        if l.type == "Экзамен":
            headers.append(f"Экзамен №{l.number}\n({l.date})\n{l.topic or ''}".strip())
            keys.append(l.id)
            if l.retake_date:
                headers.append(f"Пересдача\n({l.retake_date})")
                keys.append(l.id + "_retake")
        else:
            headers.append(f"{l.type} №{l.number}\n({l.date})")
            keys.append(l.id)
    headers.append("Средний балл")
    ncols = len(headers)
    last_col = get_column_letter(ncols)

    _title(ws, 1, last_col, "Журнал успеваемости", 16, bold=True)
    _title(ws, 2, last_col, f"Группа {group}  ·  {subject}", SZ, bold=True)
    _title(ws, 3, last_col, f"Выгружено {datetime.now().strftime('%d.%m.%Y %H:%M')}  ·  "
                            f"Технологический колледж ВСГУТУ", 12, italic=True)

    HDR = 5
    ws.append([])
    ws.append(headers)
    for cell in ws[HDR]:
        cell.font = Font(name=FNT, size=SZ, bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = BORDER

    averages = []
    for i, s in enumerate(rows):
        recs = s.get("records") or {}
        row = [s.get("surname", ""), s.get("name", "")]
        for k in keys:
            val = recs.get(k, "")
            if not val and k.endswith("_retake"):
                base = (recs.get(k[:-len("_retake")], "") or "").strip()
                failed = base.startswith(("2", "Н")) or "Не зачтено" in base
                val = "" if failed else "—"
            row.append(val)
        avg = round(float(s.get("average") or 0), 2)
        averages.append(avg)
        row.append(avg if avg > 0 else "")
        ws.append(row)
        r = HDR + 1 + i
        for c in range(1, ncols + 1):
            cell = ws.cell(row=r, column=c)
            cell.border = BORDER
            cell.font = Font(name=FNT, size=SZ, bold=(c == ncols))
            cell.alignment = Alignment(horizontal="left" if c <= 2 else "center", vertical="center")

    vals = [a for a in averages if a > 0]
    total_row = HDR + len(rows) + 1
    ws.cell(row=total_row, column=1, value="Средний по группе:")
    ws.merge_cells(start_row=total_row, start_column=1, end_row=total_row, end_column=ncols - 1)
    ws.cell(row=total_row, column=1).font = Font(name=FNT, size=SZ, bold=True)
    ws.cell(row=total_row, column=1).alignment = Alignment(horizontal="right")
    tc = ws.cell(row=total_row, column=ncols, value=round(sum(vals) / len(vals), 2) if vals else "—")
    tc.font = Font(name=FNT, size=SZ, bold=True)
    tc.alignment = Alignment(horizontal="center")

    _autofit(ws, ncols, [HDR] + list(range(HDR + 1, total_row + 1)), min_w=10, max_w=44)
    ws.row_dimensions[HDR].height = 62
    ws.freeze_panes = f"C{HDR + 1}"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_vedomost_xlsx(group: str, subject: str, term: dict, form: str, rows,
                        teacher: str = "") -> bytes:
    """Экзаменационно-зачётная (аттестационная) ведомость: группа+предмет+семестр,
    список студентов с ИТОГОВОЙ оценкой, форма контроля, дата и строка подписи.
    rows — [{surname, name, patronymic, grade}]. term — {year, semester}."""
    year = (term or {}).get("year", "")
    sem = (term or {}).get("semester", "")
    sem_txt = "осенний" if sem == 1 else ("весенний" if sem == 2 else str(sem))

    wb = Workbook()
    ws = wb.active
    ws.title = re.sub(r'[\[\]:*?/\\]', '_', f"Ведомость {group}")[:31]
    headers = ["№", "Фамилия Имя Отчество", "Итоговая оценка", "Подпись"]
    ncols = len(headers)
    last_col = get_column_letter(ncols)

    _title(ws, 1, last_col, "Технологический колледж ВСГУТУ", 12)
    _title(ws, 2, last_col, "Экзаменационная ведомость" if (form or "").lower().startswith("экз")
           else "Зачётно-экзаменационная ведомость", 16, bold=True)
    _title(ws, 3, last_col, f"Группа {group}  ·  {subject}", SZ, bold=True)
    _title(ws, 4, last_col, f"{year}, {sem_txt} семестр"
           + (f"  ·  форма контроля: {form}" if form else ""), 12, italic=True)

    HDR = 6
    for _ in range(5):
        ws.append([])
    ws.append(headers)
    for cell in ws[HDR]:
        cell.font = Font(name=FNT, size=SZ, bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = BORDER

    for i, s in enumerate(rows):
        fio = " ".join(x for x in (s.get("surname", ""), s.get("name", ""),
                                   s.get("patronymic", "")) if x).strip()
        if s.get("patronymic") and s.get("name", "").endswith(s.get("patronymic", "")):
            fio = f"{s.get('surname','')} {s.get('name','')}".strip()
        grade = (s.get("grade") or "").strip()
        ws.append([i + 1, fio, grade, ""])
        r = HDR + 1 + i
        for c in range(1, ncols + 1):
            cell = ws.cell(row=r, column=c)
            cell.border = BORDER
            cell.font = Font(name=FNT, size=SZ)
            cell.alignment = Alignment(horizontal="left" if c == 2 else "center", vertical="center")

    foot = HDR + len(rows) + 2
    ws.cell(row=foot, column=1, value=f"Дата: {datetime.now().strftime('%d.%m.%Y')}").font = Font(name=FNT, size=SZ)
    ws.merge_cells(start_row=foot, start_column=1, end_row=foot, end_column=2)
    sign = ws.cell(row=foot, column=3, value=f"Преподаватель: {teacher or '____________'}")
    sign.font = Font(name=FNT, size=SZ)
    ws.merge_cells(start_row=foot, start_column=3, end_row=foot, end_column=ncols)

    _autofit(ws, ncols, [HDR] + list(range(HDR + 1, HDR + len(rows) + 1)), min_w=6, max_w=55)
    ws.column_dimensions["A"].width = 5
    ws.row_dimensions[HDR].height = 30
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
