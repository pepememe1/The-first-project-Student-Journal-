"""
xlsx_export.py — сборка журнала в xlsx для веб-версии.

Стиль повторяет десктопный экспорт (data/core.py GradeBook.export_to_excel): весь текст
Times New Roman 14, титульная шапка (журнал/группа/предмет/дата), фирменный цвет GB,
рамки, цвет оценок по уровню, полосатые строки, «средний по группе», закрепление
областей. Данные приходят уже выбранными по роли (routers/web.py), поэтому модуль
чистый: (group, subject, lessons, rows) → bytes.
"""
import io
import re
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter

FNT = "Times New Roman"
ACCENT = "147C8B"


def _grade_color(v: str) -> str:
    v = (v or "").strip()
    if v.startswith("5"):
        return "1E7B33"
    if v.startswith("4"):
        return "1F5FBF"
    if v.startswith("3"):
        return "B26B00"
    if v.startswith("2") or v.upper().startswith("Н") or "Не зачтено" in v:
        return "B3261E"
    return "222222"


def build_journal_xlsx(group: str, subject: str, lessons, rows) -> bytes:
    """lessons — ORM-строки Lesson (id/type/number/topic/date/retake_date);
    rows — [{surname, name, records: {lesson_id→оценка}, average: float}]."""
    thin = Side(style="thin", color="C9D4D6")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    wb = Workbook()
    ws = wb.active
    ws.title = re.sub(r'[\[\]:*?/\\]', '_', f"Успеваемость {group}")[:31]

    headers = ["Фамилия", "Имя"]
    #(колонка → ключ records): у экзамена с пересдачей — две колонки
    keys = []
    for l in lessons:
        if l.type == "Экзамен":
            headers.append(f"Экзамен №{l.number}\n({l.date})\n{l.topic}")
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

    ws.merge_cells(f"A1:{last_col}1")
    ws["A1"] = "Журнал успеваемости"
    ws["A1"].font = Font(name=FNT, size=18, bold=True, color=ACCENT)
    ws["A1"].alignment = Alignment(horizontal="center")
    ws.merge_cells(f"A2:{last_col}2")
    ws["A2"] = f"Группа {group}  ·  {subject}"
    ws["A2"].font = Font(name=FNT, size=14, bold=True)
    ws["A2"].alignment = Alignment(horizontal="center")
    ws.merge_cells(f"A3:{last_col}3")
    ws["A3"] = (f"Выгружено {datetime.now().strftime('%d.%m.%Y %H:%M')}  ·  "
                f"GradeBookAI · Технологический колледж ВСГУТУ")
    ws["A3"].font = Font(name=FNT, size=11, italic=True, color="7A8A8C")
    ws["A3"].alignment = Alignment(horizontal="center")

    HDR = 5
    ws.append([])
    ws.append(headers)
    for cell in ws[HDR]:
        cell.font = Font(name=FNT, size=14, bold=True, color="FFFFFF")
        cell.fill = PatternFill(start_color=ACCENT, end_color=ACCENT, fill_type="solid")
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = border

    stripe = PatternFill(start_color="F2F7F8", end_color="F2F7F8", fill_type="solid")
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
            cell.border = border
            if i % 2:
                cell.fill = stripe
            if c <= 2:
                cell.font = Font(name=FNT, size=14)
                cell.alignment = Alignment(horizontal="left", vertical="center")
            elif c == ncols:
                cell.font = Font(name=FNT, size=14, bold=True, color=ACCENT)
                cell.alignment = Alignment(horizontal="center", vertical="center")
            else:
                cell.font = Font(name=FNT, size=14, color=_grade_color(str(cell.value or "")))
                cell.alignment = Alignment(horizontal="center", vertical="center")

    vals = [a for a in averages if a > 0]
    total_row = HDR + len(rows) + 1
    ws.cell(row=total_row, column=1, value="Средний по группе:")
    ws.merge_cells(start_row=total_row, start_column=1, end_row=total_row, end_column=ncols - 1)
    ws.cell(row=total_row, column=1).font = Font(name=FNT, size=14, bold=True)
    ws.cell(row=total_row, column=1).alignment = Alignment(horizontal="right")
    tc = ws.cell(row=total_row, column=ncols,
                 value=round(sum(vals) / len(vals), 2) if vals else "—")
    tc.font = Font(name=FNT, size=14, bold=True, color=ACCENT)
    tc.alignment = Alignment(horizontal="center")

    ws.column_dimensions["A"].width = 20
    ws.column_dimensions["B"].width = 16
    for c in range(3, ncols):
        ws.column_dimensions[get_column_letter(c)].width = 14
    ws.column_dimensions[last_col].width = 15
    ws.row_dimensions[HDR].height = 54
    ws.freeze_panes = f"C{HDR + 1}"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
