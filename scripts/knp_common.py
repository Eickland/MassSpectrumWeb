#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Общие функции для выгрузки проекта «КНП 2026» в MassSpectrumWeb.

КНП-2026 — серия FT-ICR MS на Байкале: 8 дат съёмки (2026_08_19 … 2026_10_22),
88 файлов прибора .d на диске E:, 80 проб в обработке, 4 группы журнала
(Берег Байкала, Большая вода Байкала, Реки Байкала, Карты Солзана).

Здесь собрано то, что нужно и подготовке пакета (knp_export.py), и загрузчику (knp_upload.py):
шифры проб, чтение инвентаризации, поиск сырых .d на E:, раскладка результатов в формат
сервера (formulas/<проба>.csv + qc/<проба>.json) и журнал в формате листа «Пробы».

Шифр на сайте — журнальный, латиницей: «ВС1-2» → `BC1-2`, «К4-12» → `K4-12`.
Это тот же вид, что в журнале, только кириллические В/С/К заменены латинскими B/C/K,
поэтому шифр совпадает у файлов `BC-1-2_000001`, `K4-12_000001` и строк журнала.
"""
from __future__ import annotations

import json
import math
import re
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd

# --------------------------------------------------------------------------------------
# Пути и константы
# --------------------------------------------------------------------------------------
REPO = Path(__file__).resolve().parents[1]
DATA_DIR = REPO / "data" / "knp_2026"

#: корень с папками дат съёмки на диске E: (внутри — папки <проба>.d)
DEFAULT_RAW = Path("E:/")
#: архив исходных результатов старого конвейера (all_formulas.csv, summary_qc.csv …)
DEFAULT_SOURCE = DATA_DIR / "source_results"
#: инвентаризация сверки с журналом (samples.csv, journal_status.csv, report.md)
DEFAULT_INVENTORY = DATA_DIR / "inventory"
#: куда собирается пакет для сайта (formulas/, qc/, journal.xlsx, manifest.csv)
DEFAULT_EXPORT = DATA_DIR / "export"

#: проект на сайте MassSpectrumWeb
PROJECT = "КНП 2026"
#: тип пробы для журнала — все пробы серии водные
SAMPLE_TYPE = "вода"

DATE_DIR_RE = re.compile(r"^\d{4}_\d{2}_\d{2}$")
RUN_SUFFIX = re.compile(r"[_\-\s]*\d{6}$")

#: подтверждённые вручную исправления имён: файл B-6-9 — это проба BC6-9
SAMPLE_ALIASES = {"B69": "BC69"}

#: кириллические буквы, похожие на латинские: «ВС» ↔ «BC», «К» ↔ «K»
CYR_TO_LAT = str.maketrans({
    "А": "A", "В": "B", "С": "C", "Е": "E", "Н": "H", "К": "K", "М": "M",
    "О": "O", "Р": "R", "Т": "T", "Х": "X", "У": "Y", "І": "I", "Ј": "J",
})

#: колонки листа «Пробы» — совпадают с app/journal.py, чтобы файл читался импортом сайта
SAMPLE_COLUMNS = [
    ("code", "Шифр пробы"),
    ("project", "Проект"),
    ("group_label", "Группа"),
    ("sample_type", "Тип пробы"),
    ("location", "Место отбора"),
    ("sampling_date", "Дата отбора"),
    ("extraction", "Выделение"),
    ("measured_at", "Дата съёмки"),
    ("operator", "Оператор"),
    ("description", "Описание"),
    ("notes", "Примечания"),
]
PROJECT_COLUMNS = [("name", "Проект"), ("description", "Описание"), ("lead", "Руководитель")]


# --------------------------------------------------------------------------------------
# Шифры
# --------------------------------------------------------------------------------------
def sample_key(name: str) -> str:
    """
    Ключ пробы для сопоставления файла и журнала («BC-6-2_000001» → «BC62»).
    Убирает номер съёмки, регистр, разделители и различие кириллица/латиница.
    """
    s = str(name).strip()
    s = RUN_SUFFIX.sub("", s)
    s = s.upper().translate(CYR_TO_LAT)
    return re.sub(r"[^A-Z0-9]", "", s)


def web_code(name: str) -> str:
    """
    Шифр пробы на сайте: журнальный вид латиницей и без номера съёмки.

    «ВС1-2» → `BC1-2`, «BC-1-2_000001» → `BC-1-2`, «К4-12» → `K4-12`.
    Дефисы сохраняются как в журнале; пробелы убираются.
    """
    s = RUN_SUFFIX.sub("", str(name).strip())
    s = s.upper().translate(CYR_TO_LAT)
    return re.sub(r"\s+", "", s)


# --------------------------------------------------------------------------------------
# Инвентаризация (результат сверки с журналом «Пробы с Байкала (фотометрия)»)
# --------------------------------------------------------------------------------------
def read_inventory(inventory_dir: Path = DEFAULT_INVENTORY) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Читает samples.csv (по строке на файл прибора) и journal_status.csv (по строке журнала).

    В samples.csv колонки: date, sample, key, path, is_blank, cipher, group, sampling_date,
    ms_status, photometry, toc, match, notes, duplicate_in_date, repeated_across_dates, keep.
    В обе таблицы добавляется `code` — шифр пробы на сайте.
    """
    samples_path = inventory_dir / "samples.csv"
    journal_path = inventory_dir / "journal_status.csv"
    for p in (samples_path, journal_path):
        if not p.exists():
            raise FileNotFoundError(f"нет файла инвентаризации: {p}")
    S = pd.read_csv(samples_path, encoding="utf-8-sig", dtype=str).fillna("")
    J = pd.read_csv(journal_path, encoding="utf-8-sig", dtype=str).fillna("")
    for df in (S, J):
        df["code"] = df["cipher"].map(web_code)
    for df, col in ((S, "keep"), (S, "is_blank"), (S, "duplicate_in_date"), (S, "repeated_across_dates"),
                    (J, "expected"), (J, "has_file")):
        df[col] = df[col].astype(str).str.strip().str.lower().isin({"true", "1", "yes"})
    S["measured_at"] = S["date"]
    return S, J


def measured_samples(samples: pd.DataFrame) -> pd.DataFrame:
    """Строки, которые пошли в обработку: не бланки, без повторных съёмок в тот же день и неоднозначных имён."""
    return samples[samples["keep"] & ~samples["is_blank"]].copy()


# --------------------------------------------------------------------------------------
# Сырые данные на диске E:
# --------------------------------------------------------------------------------------
def scan_raw(root: Path = DEFAULT_RAW, dates: Optional[set[str]] = None) -> pd.DataFrame:
    """
    Все папки прибора `<root>/<дата>/<проба>.d`.

    `dates` ограничивает поиск датами серии (на E: лежат и другие проекты).
    Return: date, sample (без .d), key, path, is_blank.
    """
    root = Path(root)
    if not root.exists():
        raise FileNotFoundError(f"нет диска/папки с исходными данными: {root}")
    rows = []
    for date_dir in sorted(p for p in root.iterdir() if p.is_dir() and DATE_DIR_RE.match(p.name)):
        if dates is not None and date_dir.name not in dates:
            continue
        for d in sorted(p for p in date_dir.iterdir() if p.is_dir() and p.name.lower().endswith(".d")):
            stem = d.name[:-2]
            rows.append({"date": date_dir.name, "sample": stem, "key": sample_key(stem),
                         "path": str(d), "is_blank": sample_key(stem).startswith("MEOH")})
    return pd.DataFrame(rows)


def reconcile_raw(samples: pd.DataFrame, raw: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """
    Сверяет инвентаризацию с тем, что реально лежит на диске.

    Имена на E: могли поменять расстановку дефисов (`B-1-2` ↔ `B1-2`), поэтому кроме
    точного имени файла сравнивается ключ пробы (`sample_key`). В samples добавляются
    raw_path (папка .d) и raw_sample (фактическое имя файла).

    Return: (samples, замечания).
    """
    exact = {(r.date, r.sample): r.path for r in raw.itertuples()}
    by_key = {(r.date, r.key): (r.sample, r.path) for r in raw.itertuples()}
    out = samples.copy()
    paths, names = [], []
    for d, s, k in zip(out["date"], out["sample"], out["key"]):
        p = exact.get((d, s))
        n = s
        if p is None and (d, k) in by_key:
            n, p = by_key[(d, k)]
        paths.append(p or "")
        names.append(n)
    out["raw_path"], out["raw_sample"] = paths, names
    problems = []
    for r in out[(~out["is_blank"]) & (out["raw_path"] == "")].itertuples():
        problems.append(f"{r.date}/{r.sample}: папки .d нет на диске (в инвентаризации ожидалась)")
    known = set(zip(samples["date"], samples["key"])) | set(zip(samples["date"], samples["sample"]))
    extra = []
    for r in raw.itertuples():
        if r.is_blank:
            continue
        if (r.date, r.key) not in known and (r.date, r.sample) not in known:
            problems.append(f"{r.date}/{r.sample}: .d есть на диске, но нет в инвентаризации КНП-2026")
            extra.append({"date": r.date, "sample": r.sample, "path": r.path})
    out.attrs["raw_extra"] = extra
    return out, problems


# --------------------------------------------------------------------------------------
# Журнал и пакет для сайта
# --------------------------------------------------------------------------------------
def _as_date(value: str) -> Optional[date]:
    """«2026-08-19» / «19.08.2026» / «2026_08_19» → date; пусто → None."""
    s = str(value or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y_%m_%d", "%d.%m.%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def journal_rows(journal: pd.DataFrame, manifest: pd.DataFrame) -> list[dict]:
    """
    Строки листа «Пробы» для сайта: все строки журнала, включая пробы без спектров.

    Группа — лист журнала, место отбора — та же группа, дата съёмки — последняя дата,
    когда проба снималась (у повторных съёмок в истории сайта остаются все даты).
    """
    latest: dict[str, str] = {}
    for r in manifest.itertuples():
        if not latest.get(r.code) or r.date > latest[r.code]:
            latest[r.code] = r.date
    rows, seen = [], set()
    for r in journal.itertuples():
        code = web_code(r.cipher)
        if not code or code in seen:
            continue
        seen.add(code)
        note = [f"журнал: {r.sheet}"]
        if r.photometry:
            note.append(f"фотометрия: {r.photometry}")
        if r.toc:
            note.append(f"TOC: {r.toc} мг/л")
        if r.note:
            note.append(str(r.note))
        rows.append({
            "code": code,
            "project": PROJECT,
            "group_label": r.group,
            "sample_type": SAMPLE_TYPE,
            "location": r.group,
            "sampling_date": _as_date(r.sampling_date),
            "extraction": "",
            "measured_at": _as_date(latest.get(code, "")),
            "operator": "",
            "description": f"КНП-2026, {r.group}",
            "notes": "; ".join(note),
        })
    return rows


def write_journal_xlsx(path: Path, rows: Iterable[dict], projects: Optional[list[dict]] = None) -> Path:
    """
    Журнал в формате MassSpectrumWeb: лист «Пробы» (SAMPLE_COLUMNS) и «Проекты».

    Импортируется страницей «Журнал» → «Импорт из Excel»; коды проб совпадают
    с именами в пакете выгрузки, поэтому метаданные ложатся на уже загруженные спектры.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "Пробы"
    head_fill, head_font = PatternFill("solid", fgColor="1F3A5F"), Font(bold=True, color="FFFFFF")
    for i, (_, title) in enumerate(SAMPLE_COLUMNS, 1):
        c = ws.cell(row=1, column=i, value=title)
        c.fill, c.font = head_fill, head_font
        c.alignment = Alignment(vertical="center")
        ws.column_dimensions[get_column_letter(i)].width = 26 if i in (1, 5, 11) else 16
    for row in rows:
        ws.append([row.get(f) for f, _ in SAMPLE_COLUMNS])
    for f in ("sampling_date", "measured_at"):
        col = get_column_letter([c[0] for c in SAMPLE_COLUMNS].index(f) + 1)
        for cell in ws[col][1:]:
            cell.number_format = "DD.MM.YYYY"
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(SAMPLE_COLUMNS))}{max(ws.max_row, 2)}"

    wp = wb.create_sheet("Проекты")
    for i, (_, title) in enumerate(PROJECT_COLUMNS, 1):
        c = wp.cell(row=1, column=i, value=title)
        c.fill, c.font = head_fill, head_font
        wp.column_dimensions[get_column_letter(i)].width = 28 if i == 1 else 60
    for p in projects or [{"name": PROJECT, "description": "Масс-спектрометрия FT-ICR MS, Байкал 2026",
                           "lead": ""}]:
        wp.append([p.get(f) for f, _ in PROJECT_COLUMNS])
    wb.save(path)
    return path


def _jsonable(value):
    if value is None:
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if hasattr(value, "item"):  # numpy scalar
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def qc_from_row(row) -> dict:
    """
    QC пробы в формате qc/<проба>.json конвейера — из строки summary_qc.csv старого прогона.

    Сервер читает quality, peaks, assign_tol_ppm, sigma_strong_ppm, final_err_rms_ppm,
    calibration.rms и final_13C_confirmed_pct, остальное хранит в истории загрузки.
    """
    g = lambda k: _jsonable(row.get(k))  # noqa: E731
    calib = {
        "n": g("calib_n"), "mz_min": g("calib_mz_min"), "mz_max": g("calib_mz_max"),
        "rms": g("calib_rms_ppm"), "period": bool(row.get("calib_periodic") in (True, "True", "true", 1)),
    }
    return {
        "sample": g("sample"), "date": g("date"), "quality": g("quality"),
        "peaks": g("peaks"), "assigned": g("assigned"), "final": g("final_formulas"),
        "iso13C": g("iso13C"), "iso34S": g("iso34S"), "duplicate": g("duplicate"),
        "removed_filters": g("removed_filters"), "removed_blank": g("removed_blank"),
        "removed_list": g("removed_list"), "removed_polyether": g("removed_polyether"),
        "calibration": {k: v for k, v in calib.items() if v is not None},
        "sigma_strong_ppm": g("sigma_strong_ppm"), "assign_tol_ppm": g("assign_tol_ppm"),
        "final_err_rms_ppm": g("final_err_rms_ppm"),
        "final_13C_confirmed_pct": g("final_13C_confirmed_pct"),
    }


def dump_json(data: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


#: колонки, которые не нужно передавать на сайт: проба/дата/группа берутся из имени файла и журнала
FORMULA_META_COLUMNS = ["sample", "date", "group"]
