"""
Приём результатов конвейера HumSpectra: formulas/<проба>.csv (+ qc/<проба>.json) → БД.

Дескрипторы формул и пробы пересчитываются сервером функциями pipeline.descriptors — так в БД всегда одни и те же
определения, даже если CSV получен старой версией конвейера или содержит только состав и интенсивность.
"""
import hashlib
import io
import json
import math
import re
import zipfile
from pathlib import PurePosixPath
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy import insert, select, update
from sqlalchemy.orm import Session

from . import humspectra as hs
from .models import Formula, Project, Sample, Spectrum

ELEMENTS = ("C", "H", "O", "N", "S")
FORMULA_RE = re.compile(r"([A-Z][a-z]?)(\d*)")
RUN_SUFFIX = re.compile(r"_\d{6}$")  # суффикс файла прибора: ADOM-SLB-1_000001


class IngestError(ValueError):
    pass


def _parse_formula(s: str) -> dict:
    d = {e: 0 for e in ELEMENTS}
    for el, n in FORMULA_RE.findall(str(s)):
        if el in d:
            d[el] += int(n) if n else 1
    return d


def _brutto(r) -> str:
    return "".join(f"{e}{int(r[e])}" for e in ELEMENTS if int(r[e]) > 0)


def read_formulas_csv(data: bytes) -> pd.DataFrame:
    """Читает CSV формул (формат pipeline или минимальный: formula|C,H,O,N,S + intensity) и считает дескрипторы."""
    try:
        F = pd.read_csv(io.BytesIO(data), sep=None, engine="python", encoding="utf-8-sig")
    except Exception as e:  # noqa: BLE001
        raise IngestError(f"не удалось прочитать CSV: {e}") from e
    F.columns = [str(c).strip() for c in F.columns]
    if not all(e in F for e in ("C", "H", "O")):
        if "formula" not in F:
            raise IngestError("в CSV нет ни колонок C, H, O, ни колонки formula")
        parsed = pd.DataFrame([_parse_formula(x) for x in F["formula"]], index=F.index)
        for e in ELEMENTS:
            F[e] = parsed[e]
    for e in ELEMENTS:
        F[e] = pd.to_numeric(F[e], errors="coerce").fillna(0).astype(int) if e in F else 0
    F = F[F["C"] > 0].copy()
    if "intensity" not in F:
        raise IngestError("в CSV нет колонки intensity")
    F["intensity"] = pd.to_numeric(F["intensity"], errors="coerce")
    F = F[F["intensity"] > 0]
    if len(F) == 0:
        raise IngestError("в CSV нет формул")
    F["formula"] = F.apply(_brutto, axis=1) if "formula" not in F else F["formula"].astype(str)
    if "theo_mz" not in F:
        mzcol = next((c for c in ("mz_cal", "mass", "mz", "calc_mass") if c in F), None)
        if mzcol is None:
            raise IngestError("в CSV нет m/z (theo_mz, mz_cal или mass)")
        F["theo_mz"] = F[mzcol]
    # одна формула — одна строка (если CSV не из pipeline): оставляем самую интенсивную
    F = F.sort_values("intensity", ascending=False).drop_duplicates("formula").sort_values("theo_mz")
    F = hs.formula_metrics(F)
    F["rel_intensity"] = F["intensity"] / F["intensity"].sum()
    return F.reset_index(drop=True)


def _num(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _clean_json(o):
    if isinstance(o, dict):
        return {str(k): _clean_json(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean_json(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (float, np.floating)):
        return float(o) if math.isfinite(o) else None
    return o


def resolve_sample(db: Session, name: str, project: Optional[str] = None, create: bool = True) -> Optional[Sample]:
    """Проба по имени из конвейера: точное совпадение шифра, затем без суффикса прибора (_000001); иначе новая."""
    s = db.scalar(select(Sample).where(Sample.code == name))
    if s is None:
        base = RUN_SUFFIX.sub("", name)
        if base != name:
            s = db.scalar(select(Sample).where(Sample.code == base))
    if s is None and create:
        s = Sample(code=name)
        db.add(s)
    if s is not None and project and s.project_id is None:
        s.project = get_or_create_project(db, project)
    return s


def get_or_create_project(db: Session, name: str) -> Project:
    name = name.strip()
    p = db.scalar(select(Project).where(Project.name == name))
    if p is None:
        p = Project(name=name)
        db.add(p)
        db.flush()
    return p


FORMULA_COLS = {"formula": "formula", "C": "C", "H": "H", "O": "O", "N": "N", "S": "S", "theo_mz": "theo_mz",
                "mz_cal": "mz_cal", "err_ppm": "err_ppm", "intensity": "intensity", "rel_intensity": "rel_intensity",
                "SN": "sn", "elemental_class": "elemental_class", "H/C": "hc", "O/C": "oc", "DBE": "dbe",
                "DBE-O": "dbe_o", "AI_mod": "ai_mod", "NOSC": "nosc", "CRAM": "cram",
                "class_laszakovits": "lasz_class", "square": "square"}


def ingest_spectrum(db: Session, name: str, formulas_csv: bytes, qc_json: Optional[bytes] = None,
                    project: Optional[str] = None) -> dict:
    """Сохраняет загрузку спектра пробы; прежняя загрузка остаётся в истории (is_current = False)."""
    F = read_formulas_csv(formulas_csv)
    qc = {}
    if qc_json:
        try:
            qc = json.loads(qc_json.decode("utf-8-sig"))
        except Exception as e:  # noqa: BLE001
            raise IngestError(f"не удалось прочитать qc JSON: {e}") from e
    name = (name or qc.get("sample") or "").strip()
    if not name:
        raise IngestError("не задано имя пробы")
    sha = hashlib.sha256(formulas_csv).hexdigest()
    sample = resolve_sample(db, name, project)
    db.flush()
    cur = sample.current
    if cur is not None and cur.sha256 == sha:
        # тот же файл формул: обновим только QC, если пришёл
        if qc:
            _apply_qc(cur, qc)
        db.commit()
        return {"sample": sample.code, "status": "unchanged", "spectrum_id": cur.id, "n_formulas": cur.n_formulas}
    same = db.scalar(select(Spectrum).where(Spectrum.sample_id == sample.id, Spectrum.sha256 == sha))
    if same is not None:
        # этот CSV уже загружался раньше (например, повторная съёмка другой даты):
        # не плодим дубли в истории, только обновляем QC и делаем загрузку актуальной
        if qc:
            _apply_qc(same, qc)
        if not same.is_current:
            db.execute(update(Spectrum).where(Spectrum.sample_id == sample.id).values(is_current=False))
            same.is_current = True
        db.commit()
        return {"sample": sample.code, "status": "unchanged", "spectrum_id": same.id,
                "n_formulas": same.n_formulas}
    db.execute(update(Spectrum).where(Spectrum.sample_id == sample.id).values(is_current=False))
    desc = _clean_json(hs.sample_descriptors(F))
    sp = Spectrum(sample=sample, is_current=True, source_name=name, sha256=sha, n_formulas=len(F),
                  descriptors=desc, mz_min=float(F["theo_mz"].min()), mz_max=float(F["theo_mz"].max()))
    if "err_ppm" in F and F["err_ppm"].notna().any():
        sp.final_err_rms_ppm = float(np.sqrt(np.nanmean(F["err_ppm"].astype(float) ** 2)))
    _apply_qc(sp, qc)
    db.add(sp)
    db.flush()
    rows = []
    for r in F.to_dict("records"):
        row = {"spectrum_id": sp.id}
        for src, dst in FORMULA_COLS.items():
            v = r.get(src)
            if dst in ("formula", "elemental_class", "lasz_class", "square"):
                row[dst] = "" if v is None or (isinstance(v, float) and not math.isfinite(v)) else str(v)
            elif dst == "cram":
                row[dst] = bool(v) if v is not None and v == v else False
            elif dst in ELEMENTS:
                row[dst] = int(v)
            else:
                row[dst] = _num(v)
        rows.append(row)
    db.execute(insert(Formula), rows)
    db.commit()
    return {"sample": sample.code, "status": "created", "spectrum_id": sp.id, "n_formulas": len(F),
            "quality": sp.quality or None}


def _apply_qc(sp: Spectrum, qc: dict):
    if not qc:
        return
    q = {k: v for k, v in qc.items() if k not in ("descriptors", "params")}
    sp.qc = _clean_json(q)
    sp.params = _clean_json(qc.get("params") or {})
    sp.quality = str(qc.get("quality") or "")
    sp.n_peaks = qc.get("peaks")
    sp.assign_tol_ppm = _num(qc.get("assign_tol_ppm"))
    sp.sigma_strong_ppm = _num(qc.get("sigma_strong_ppm"))
    if qc.get("final_err_rms_ppm") is not None:
        sp.final_err_rms_ppm = _num(qc.get("final_err_rms_ppm"))
    sp.calib_rms_ppm = _num((qc.get("calibration") or {}).get("rms"))
    sp.c13_confirmed_pct = _num(qc.get("final_13C_confirmed_pct"))


def split_upload_name(filename: str) -> tuple[str, str]:
    """('formulas'|'qc'|'', имя пробы) по имени файла: formulas/X.csv, qc/X.json, X.csv, X__formulas.csv, X.json."""
    p = PurePosixPath(filename.replace("\\", "/"))
    stem, ext = p.stem, p.suffix.lower()
    for suf in ("__formulas", "_formulas", "__qc", "_qc"):
        if stem.endswith(suf):
            stem = stem[: -len(suf)]
    if ext == ".csv":
        return "formulas", stem
    if ext == ".json":
        return "qc", stem
    return "", stem


SKIP_STEMS = {"BLANK", "all_formulas", "summary_descriptors", "summary_qc", "blank_formulas", "statistics",
              "statistics_without_poor"}


def ingest_files(db: Session, files: list[tuple[str, bytes]], project: Optional[str] = None) -> list[dict]:
    """Набор файлов (CSV формул и JSON QC, сопоставляются по имени пробы) или zip папки результатов run_batch."""
    expanded: list[tuple[str, bytes]] = []
    for fn, data in files:
        if fn.lower().endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                for info in z.infolist():
                    parts = PurePosixPath(info.filename).parts
                    if info.is_dir() or "peaks" in parts or "mzml" in parts:
                        continue
                    if info.filename.lower().endswith((".csv", ".json")):
                        expanded.append((info.filename, z.read(info)))
        else:
            expanded.append((fn, data))
    # в zip-архиве папки результатов формулы лежат в formulas/, остальные CSV — сводки
    has_formulas_dir = any("formulas" in PurePosixPath(fn.replace("\\", "/")).parts[:-1] for fn, _ in expanded)
    by_name: dict[str, dict] = {}
    for fn, data in expanded:
        kind, stem = split_upload_name(fn)
        parts = PurePosixPath(fn.replace("\\", "/")).parts
        if not kind or stem in SKIP_STEMS:
            continue
        if kind == "formulas" and has_formulas_dir and "formulas" not in parts[:-1]:
            continue
        by_name.setdefault(stem, {})[kind] = data
    out = []
    for name, d in sorted(by_name.items()):
        if "formulas" not in d:
            out.append({"sample": name, "status": "error", "error": "нет CSV формул (есть только QC)"})
            continue
        try:
            out.append(ingest_spectrum(db, name, d["formulas"], d.get("qc"), project))
        except IngestError as e:
            db.rollback()
            out.append({"sample": name, "status": "error", "error": str(e)})
    return out
