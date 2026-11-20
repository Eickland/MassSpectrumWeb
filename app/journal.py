"""
Лабораторный журнал: Excel ⇄ БД.

Файл журнала (lab_journal.xlsx):
  лист «Пробы»   — одна строка на пробу; обязателен только «Шифр пробы» (= имя файла спектра без _000001 или с ним);
  лист «Проекты» — проект, описание, руководитель;
  лист «Справка» — описание колонок.
Импорт — обновление по шифру (пустые ячейки не затирают данные в БД). Поддерживается и старый формат
(лист Samples: Name, Project, Description, Notes).
"""
import io
from datetime import date, datetime
from typing import Optional

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .ingest import get_or_create_project
from .models import Project, Sample

# (поле модели, заголовок, ширина, подсказка)
SAMPLE_COLUMNS = [
    ("code", "Шифр пробы", 28, "Обязательно. Совпадает с именем пробы в конвейере (имя файла .d/.mzML)"),
    ("project", "Проект", 20, "Название проекта с листа «Проекты» (новый проект создаётся автоматически)"),
    ("group_label", "Группа", 14, "Группа для статистического сравнения (например, Baikal / Solzan)"),
    ("sample_type", "Тип пробы", 16, "вода, почва, донные отложения, торф, препарат ГВ …"),
    ("location", "Место отбора", 26, "Объект, точка, координаты"),
    ("sampling_date", "Дата отбора", 13, "ДД.ММ.ГГГГ"),
    ("extraction", "Выделение", 16, "Метод выделения/концентрирования: SPE PPL, …"),
    ("measured_at", "Дата съёмки", 13, "Дата регистрации масс-спектра, ДД.ММ.ГГГГ"),
    ("operator", "Оператор", 16, "Кто снимал / обрабатывал"),
    ("description", "Описание", 30, "Краткое описание пробы"),
    ("notes", "Примечания", 30, "Любые заметки"),
]
PROJECT_COLUMNS = [("name", "Проект", 24), ("description", "Описание", 50), ("lead", "Руководитель", 22)]
ALIASES = {  # заголовок (в нижнем регистре) → поле
    "name": "code", "sample": "code", "шифр": "code", "шифр пробы": "code", "проба": "code", "код пробы": "code",
    "project": "project", "проект": "project", "description": "description", "описание": "description",
    "notes": "notes", "примечания": "notes", "group": "group_label", "группа": "group_label",
    "тип": "sample_type", "тип пробы": "sample_type", "место": "location", "место отбора": "location",
    "дата отбора": "sampling_date", "выделение": "extraction", "метод выделения": "extraction",
    "дата съёмки": "measured_at", "дата съемки": "measured_at", "оператор": "operator",
}
DATE_FIELDS = {"sampling_date", "measured_at"}
HEAD_FILL = PatternFill("solid", fgColor="1F3A5F")
HEAD_FONT = Font(bold=True, color="FFFFFF")


def _to_date(v) -> Optional[date]:
    if v in (None, ""):
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d.%m.%y", "%d/%m/%Y", "%Y_%m_%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"не распознана дата «{s}»")


def _header(ws, cols):
    for i, c in enumerate(cols, 1):
        cell = ws.cell(row=1, column=i, value=c[1])
        cell.fill, cell.font = HEAD_FILL, HEAD_FONT
        cell.alignment = Alignment(vertical="center")
        ws.column_dimensions[get_column_letter(i)].width = c[2]
    ws.freeze_panes = "A2"
    ws.row_dimensions[1].height = 22


def build_workbook(samples: list[Sample], projects: list[Project]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Пробы"
    _header(ws, SAMPLE_COLUMNS)
    for s in samples:
        row = []
        for f, *_ in SAMPLE_COLUMNS:
            v = s.project.name if f == "project" and s.project else ("" if f == "project" else getattr(s, f))
            row.append(v)
        ws.append(row)
    for f in DATE_FIELDS:
        col = get_column_letter([c[0] for c in SAMPLE_COLUMNS].index(f) + 1)
        for cell in ws[col][1:]:
            cell.number_format = "DD.MM.YYYY"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(SAMPLE_COLUMNS))}{max(ws.max_row, 2)}"

    wp = wb.create_sheet("Проекты")
    _header(wp, PROJECT_COLUMNS)
    for p in projects:
        wp.append([p.name, p.description, p.lead])
    # выпадающий список проектов
    n = max(len(projects) + 50, 100)
    dv = DataValidation(type="list", formula1=f"='Проекты'!$A$2:$A${n}", allow_blank=True, showErrorMessage=False)
    ws.add_data_validation(dv)
    dv.add(f"B2:B{max(ws.max_row + 500, 1000)}")

    wh = wb.create_sheet("Справка")
    wh.column_dimensions["A"].width, wh.column_dimensions["B"].width = 22, 90
    wh.append(["Колонка", "Что заполнять"])
    for c in (wh["A1"], wh["B1"]):
        c.fill, c.font = HEAD_FILL, HEAD_FONT
    for _, title, _, hint in SAMPLE_COLUMNS:
        wh.append([title, hint])
    wh.append([])
    wh.append(["Импорт", "Страница «Журнал» → «Импорт из Excel». Строки сопоставляются по шифру пробы; "
                         "пустые ячейки не стирают данные, уже внесённые в базу."])
    wh.append(["Спектры", "Пробы, для которых загружены спектры (CSV формул), но которых нет в журнале, "
                          "появляются в базе автоматически — их метаданные можно дописать здесь или на сайте."])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def export_journal(db: Session) -> bytes:
    samples = db.scalars(select(Sample).options(selectinload(Sample.project)).order_by(Sample.code)).all()
    projects = db.scalars(select(Project).order_by(Project.name)).all()
    return build_workbook(list(samples), list(projects))


def _rows(ws):
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []
    head = [ALIASES.get(str(h).strip().lower(), None) if h is not None else None for h in rows[0]]
    out = []
    for r in rows[1:]:
        d = {h: v for h, v in zip(head, r) if h}
        if any(v not in (None, "") for v in d.values()):
            out.append(d)
    return out


def import_journal(db: Session, data: bytes) -> dict:
    wb = load_workbook(io.BytesIO(data), data_only=True)
    report = {"projects": 0, "created": 0, "updated": 0, "errors": []}
    if "Проекты" in wb.sheetnames:
        for i, r in enumerate(wb["Проекты"].iter_rows(min_row=2, values_only=True), 2):
            if not r or not r[0]:
                continue
            p = get_or_create_project(db, str(r[0]))
            if len(r) > 1 and r[1]:
                p.description = str(r[1])
            if len(r) > 2 and r[2]:
                p.lead = str(r[2])
            report["projects"] += 1
    ws = next((wb[n] for n in ("Пробы", "Samples") if n in wb.sheetnames), wb.worksheets[0])
    for i, d in enumerate(_rows(ws), 2):
        code = str(d.get("code") or "").strip()
        if not code:
            report["errors"].append(f"строка {i}: нет шифра пробы")
            continue
        s = db.scalar(select(Sample).where(Sample.code == code))
        if s is None:
            s = Sample(code=code)
            db.add(s)
            report["created"] += 1
        else:
            report["updated"] += 1
        try:
            apply_fields(db, s, d, overwrite_empty=False)
        except ValueError as e:
            report["errors"].append(f"строка {i} ({code}): {e}")
    db.commit()
    return report


EDITABLE = [c[0] for c in SAMPLE_COLUMNS if c[0] != "code"]


def apply_fields(db: Session, s: Sample, d: dict, overwrite_empty: bool = True):
    for f in EDITABLE:
        if f not in d:
            continue
        v = d[f]
        empty = v is None or (isinstance(v, str) and not v.strip())
        if empty and not overwrite_empty:
            continue
        if f == "project":
            s.project = None if empty else get_or_create_project(db, str(v))
        elif f in DATE_FIELDS:
            setattr(s, f, None if empty else _to_date(v))
        else:
            setattr(s, f, "" if empty else str(v).strip())
