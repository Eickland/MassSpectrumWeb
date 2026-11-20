#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Подготовка пакета «КНП 2026» для загрузки в MassSpectrumWeb.

Что делает
----------
1. Читает инвентаризацию сверки с журналом (data/knp_2026/inventory: samples.csv,
   journal_status.csv) — она уже учитывает бланки MeOH, повторные съёмки и исправленное
   имя B-6-9 → BC6-9.
2. Проверяет, что исходные папки .d на диске E: на месте (`--raw E:\\`), и пишет
   расхождения в отчёт.
3. Собирает пакет в формате, который принимает сайт:
       <out>/formulas/<шифр>__<дата>.csv   таблица формул пробы (без колонок sample/date/group)
       <out>/qc/<шифр>__<дата>.json        QC: качество, калибровка, пики, изотопологи
       <out>/journal.xlsx                  журнал для «Импорт из Excel» (лист «Пробы»)
       <out>/manifest.csv                  список того, что и под каким шифром загружать
       <out>/report.md                     что собрано и что не сошлось
4. Источник формул — либо архив старого прогона (--source, all_formulas.csv + summary_qc.csv),
   либо свежие результаты конвейера (--runs <папка results>, внутри runs/<дата>/formulas|qc).

Шифры на сайте — журнальные, латиницей: ВС1-2 → BC1-2, К4-12 → K4-12 (см. knp_common.web_code).
Поэтому `BC-1-2_000001`, `K4-12_000001` и соответствующие строки журнала попадают в одну пробу.

Примеры
-------
    python scripts/knp_export.py --raw E:/ --out data/knp_2026/export
    python scripts/knp_export.py --runs D:/lab/KNP-2026/results --raw E:/
    python scripts/knp_export.py --no-raw               # без проверки диска E:
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import knp_common as kc  # noqa: E402


def safe_name(name: str) -> str:
    """Имя файла пакета: шифр пробы без символов, недопустимых в путях Windows."""
    import re
    return re.sub(r'[<>:"/\\|?*]+', "_", str(name)).strip(" .") or "sample"


def _formulas_from_source(source: Path, manifest: pd.DataFrame) -> tuple[dict, pd.DataFrame, list[str]]:
    """Раскладывает all_formulas.csv старого прогона по пробам: (sample, date) → таблица формул."""
    path = source / "all_formulas.csv"
    if not path.exists():
        raise FileNotFoundError(f"нет {path}; укажите --source или --runs")
    F = pd.read_csv(path, encoding="utf-8-sig")
    need = {"sample", "date", "formula", "C", "H", "O", "intensity"}
    if not need.issubset(F.columns):
        raise ValueError(f"{path}: нет колонок {need - set(F.columns)}")
    keys = set(zip(manifest["sample"], manifest["date"]))
    F = F[[(s, d) in keys for s, d in zip(F["sample"], F["date"])]]
    out, errors = {}, []
    for (stem, date), G in F.groupby(["sample", "date"], sort=False):
        out[(stem, date)] = G.drop(columns=[c for c in kc.FORMULA_META_COLUMNS if c in G.columns])
    found = {(s, d) for s, d in out}
    for r in manifest.itertuples():
        if (r.sample, r.date) not in found:
            errors.append(f"{r.date}/{r.sample}: нет формул в {path.name}")
    return out, pd.read_csv(source / "summary_qc.csv", encoding="utf-8-sig"), errors


def _formulas_from_runs(runs: Path, manifest: pd.DataFrame) -> tuple[dict, pd.DataFrame, list[str], dict]:
    """Берёт formulas/<проба>.csv и qc/<проба>.json из свежего прогона run_batch."""
    out, qc_rows, errors, qc_paths = {}, [], [], {}
    qc_index = {}
    for r in manifest.itertuples():
        f = runs / "runs" / r.date / "formulas" / f"{r.sample}.csv"
        q = runs / "runs" / r.date / "qc" / f"{r.sample}.json"
        if not f.exists():
            errors.append(f"{r.date}/{r.sample}: нет {f}")
            continue
        F = pd.read_csv(f, encoding="utf-8-sig")
        out[(r.sample, r.date)] = F.drop(columns=[c for c in kc.FORMULA_META_COLUMNS if c in F.columns])
        if q.exists():
            qc_paths[(r.sample, r.date)] = q
    return out, pd.DataFrame(), errors, qc_paths


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", default=str(kc.DEFAULT_RAW), help="корень с папками дат и .d (по умолчанию E:/)")
    ap.add_argument("--no-raw", action="store_true", help="не проверять наличие .d на диске")
    ap.add_argument("--inventory", default=str(kc.DEFAULT_INVENTORY), help="папка инвентаризации сверки")
    ap.add_argument("--source", default=str(kc.DEFAULT_SOURCE),
                    help="архив старого прогона (all_formulas.csv, summary_qc.csv)")
    ap.add_argument("--runs", default="", help="папка results конвейера (runs/<дата>/formulas|qc); приоритетнее --source")
    ap.add_argument("--out", default=str(kc.DEFAULT_EXPORT), help="папка пакета выгрузки")
    ap.add_argument("--project", default=kc.PROJECT, help="проект на сайте")
    ap.add_argument("--overwrite", action="store_true", help="очистить formulas/ и qc/ перед сборкой")
    args = ap.parse_args(argv)

    inventory = Path(args.inventory)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    S, J = kc.read_inventory(inventory)
    manifest = kc.measured_samples(S)
    print(f"Инвентаризация: {inventory}")
    print(f"  файлов прибора: {len(S)} (бланков {int(S['is_blank'].sum())}); проб в обработке: {len(manifest)}")

    # --- шифры: один код на пробу, без конфликтов между разными пробами -------------------
    codes = manifest.drop_duplicates("sample")[["sample", "code", "key"]]
    aliased = {frm: kc.web_code(to) for frm, to in kc.SAMPLE_ALIASES.items()}
    conflicts = []
    for code, G in codes.groupby("code"):
        keys = {r.key for _, r in G.iterrows()}
        if len(keys) > 1 and len({aliased.get(k, k) for k in keys}) > 1:
            conflicts.append(f"{code}: " + ", ".join(f"{r['sample']} ({r['key']})" for _, r in G.iterrows()))
    if conflicts:
        print("ВНИМАНИЕ: разные пробы получают один шифр на сайте:")
        for c in conflicts:
            print("  " + c)

    # --- сырые .d на E: ------------------------------------------------------------------
    problems, raw = [], pd.DataFrame()
    extra = pd.DataFrame()
    if not args.no_raw:
        try:
            raw = kc.scan_raw(Path(args.raw), dates=set(S["date"]))
            manifest, problems = kc.reconcile_raw(manifest, raw)
            extra = pd.DataFrame(manifest.attrs.get("raw_extra", []))
            if len(extra):
                extra.to_csv(out / "raw_not_in_journal.csv", index=False, encoding="utf-8-sig")
            print(f"Сырые данные: {args.raw}; папок .d: {len(raw)} в {raw['date'].nunique()} датах серии")
            renamed = manifest[manifest["raw_sample"].ne(manifest["sample"])]
            if len(renamed):
                print(f"  имя .d отличается расстановкой дефисов/регистром: {len(renamed)} "
                      f"(сопоставлены по ключу пробы)")
            missing = int((manifest["raw_path"] == "").sum())
            if missing:
                print(f"  нет на диске: {missing} проб (см. report.md)")
            if len(extra):
                print(f"  .d вне журнала: {len(extra)} (список — raw_not_in_journal.csv)")
        except FileNotFoundError as e:
            print(f"ВНИМАНИЕ: {e} — проверка сырых данных пропущена")
    for c in conflicts:
        problems.append("конфликт шифров: " + c)

    # --- формулы и QC --------------------------------------------------------------------
    qc_paths = {}
    if args.runs:
        runs = Path(args.runs)
        print(f"Источник формул: свежий прогон {runs}")
        formulas, qc_table, errors, qc_paths = _formulas_from_runs(runs, manifest)
    else:
        source = Path(args.source)
        print(f"Источник формул: архив старого прогона {source}")
        formulas, qc_table, errors = _formulas_from_source(source, manifest)
    problems.extend(errors)

    # --- запись пакета -------------------------------------------------------------------
    fdir, qdir = out / "formulas", out / "qc"
    if args.overwrite:
        for d in (fdir, qdir):
            if d.exists():
                shutil.rmtree(d)
    fdir.mkdir(parents=True, exist_ok=True)
    qdir.mkdir(parents=True, exist_ok=True)

    qc_by_key = {}
    if len(qc_table):
        for (stem, date), G in qc_table.groupby(["sample", "date"], sort=False):
            qc_by_key[(stem, date)] = G.iloc[0]

    rows, total = [], 0
    for r in manifest.itertuples():
        key = (r.sample, r.date)
        if key not in formulas:
            continue
        tag = f"{safe_name(r.code)}__{r.date}"
        F = formulas[key]
        fpath = fdir / f"{tag}.csv"
        F.to_csv(fpath, index=False, encoding="utf-8-sig")
        qpath = qdir / f"{tag}.json"
        if key in qc_paths:
            shutil.copyfile(qc_paths[key], qpath)
            import json
            qc = json.loads(qpath.read_text(encoding="utf-8-sig"))
        elif key in qc_by_key:
            qc = kc.qc_from_row(qc_by_key[key])
        else:
            qc = {"sample": r.sample, "date": r.date}
        qc["sample"] = r.code
        qc["date"] = r.date
        kc.dump_json(qc, qpath)
        rows.append({
            "code": r.code, "date": r.date, "sample": r.sample,
            "group": getattr(r, "group", ""), "sampling_date": getattr(r, "sampling_date", ""),
            "measured_at": r.date, "formulas": str(fpath.relative_to(out)),
            "qc": str(qpath.relative_to(out)), "n_formulas": len(F),
            "quality": qc.get("quality", ""), "raw_path": getattr(r, "raw_path", ""),
        })
        total += len(F)

    M = pd.DataFrame(rows).sort_values(["group", "code", "date"])
    M.to_csv(out / "manifest.csv", index=False, encoding="utf-8-sig")

    # --- журнал --------------------------------------------------------------------------
    journal = kc.journal_rows(J, M)
    for row in journal:
        if args.project != kc.PROJECT:
            row["project"] = args.project
    kc.write_journal_xlsx(out / "journal.xlsx", journal,
                          projects=[{"name": args.project,
                                     "description": "FT-ICR MS, Байкал 2026 (КНП)",
                                     "lead": ""}])

    # --- отчёт ---------------------------------------------------------------------------
    qcount = M["quality"].value_counts().to_dict() if len(M) else {}
    lines = [
        "# Пакет выгрузки «КНП 2026» в MassSpectrumWeb\n",
        f"- проб в пакете: **{len(M)}** ({M['code'].nunique()} шифров, {M['date'].nunique()} дат съёмки)",
        f"- формул всего: **{total}**",
        f"- строк журнала: **{len(journal)}** (включая пробы без спектров)",
        f"- качество: {qcount}",
        f"- проект на сайте: **{args.project}**",
        f"- пакет: `{out}`\n",
        "## Файлы\n",
        "- `formulas/<шифр>__<дата>.csv` — таблицы формул, по одной на съёмку;",
        "- `qc/<шифр>__<дата>.json` — QC (качество, калибровка, пики, изотопологи);",
        "- `journal.xlsx` — журнал для «Журнал → Импорт из Excel» (шифры совпадают с формулами);",
        "- `manifest.csv` — что загружать; используется `knp_upload.py`.\n",
    ]
    if raw is not None and len(raw) and not args.no_raw:
        lines.append("## Сырые данные\n")
        lines.append(f"Диск: `{args.raw}`; папок .d серии: {len(raw)} в {raw['date'].nunique()} датах "
                     f"({', '.join(sorted(raw['date'].unique()))}). Повторная обработка — конвейером "
                     "HumSpectra, затем `knp_export.py --runs <results>`.\n")
        if len(extra):
            lines.append(f"Вне журнала (в пакет не входят): {len(extra)} папок .d — "
                         f"{', '.join(extra['sample'])}. Список: `raw_not_in_journal.csv`.\n")
    lines.append("## Замечания\n")
    lines.extend(f"- {p}" for p in problems) if problems else lines.append("- расхождений нет")
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"\nПакет: {out}")
    print(f"  формул: {len(M)} файлов, {total} строк; журнал: {len(journal)} строк")
    print(f"  качество: {qcount}")
    if problems:
        print(f"  замечаний: {len(problems)} (подробно — {out / 'report.md'})")
    return 0 if len(M) else 2


if __name__ == "__main__":
    sys.exit(main())
