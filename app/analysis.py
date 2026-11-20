"""Расчёты для графиков и статистики по загруженным спектрам."""
import math
import re
from typing import Optional

import numpy as np
import pandas as pd
from scipy.stats import kruskal
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from . import humspectra as hs
from .models import Formula, Sample, Spectrum

FORMULA_FIELDS = ["formula", "C", "H", "O", "N", "S", "theo_mz", "mz_cal", "err_ppm", "intensity", "rel_intensity",
                  "sn", "elemental_class", "hc", "oc", "dbe", "dbe_o", "ai_mod", "nosc", "cram", "lasz_class", "square"]

DESCRIPTOR_LABELS = {
    "n_formulas": "Число формул", "CHO": "Доля CHO", "CHON": "Доля CHON", "CHOS": "Доля CHOS", "CHONS": "Доля CHONS",
    "CRAM": "Доля CRAM",
    **{f"lasz_{k}": f"Ласаковиц: {v}" for k, v in (("lignin", "лигнины"), ("tannin", "танины"), ("peptide", "пептиды"),
                                                   ("lipid", "липиды"), ("carbohydrate", "углеводы"),
                                                   ("aminosugar", "аминосахара"), ("undefinded", "не определено"))},
    **{f"D{i:02d}": f"Квадрат D{i:02d}" for i in range(1, 21)},
}
for _k, _l in (("mz", "m/z"), ("C", "C"), ("H", "H"), ("O", "O"), ("N", "N"), ("S", "S"), ("H/C", "H/C"), ("O/C", "O/C"),
               ("DBE", "DBE"), ("DBE-O", "DBE−O"), ("DBE-OC", "(DBE−O)/C"), ("AI", "AI"), ("AI_mod", "AI_mod"),
               ("NOSC", "NOSC")):
    DESCRIPTOR_LABELS[f"mean_{_k}"] = f"{_l}, среднее"
    DESCRIPTOR_LABELS[f"wmean_{_k}"] = f"{_l}, взвеш. по интенсивности"

DESCRIPTOR_GROUPS = [
    ("Состав", ["n_formulas", "CHO", "CHON", "CHOS", "CHONS", "CRAM"]),
    ("Взвешенные средние", [f"wmean_{k}" for k in ("mz", "H/C", "O/C", "DBE", "DBE-O", "AI_mod", "NOSC", "C", "H", "O", "N", "S", "DBE-OC", "AI")]),
    ("Средние без весов", [f"mean_{k}" for k in ("mz", "H/C", "O/C", "DBE", "DBE-O", "AI_mod", "NOSC", "C", "H", "O", "N", "S", "DBE-OC", "AI")]),
    ("Классы Ласаковица", [f"lasz_{k}" for k in ("lignin", "tannin", "peptide", "lipid", "carbohydrate", "aminosugar", "undefinded")]),
    ("Квадраты Ван Кревелена", [f"D{i:02d}" for i in range(1, 21)]),
]
KEY_DESCRIPTORS = ["n_formulas", "wmean_mz", "wmean_H/C", "wmean_O/C", "wmean_DBE", "wmean_AI_mod", "wmean_NOSC",
                   "CHO", "CHON", "CHOS", "CRAM"]


def _f(x):
    if x is None:
        return None
    try:
        x = float(x)
    except (TypeError, ValueError):
        return x
    return x if math.isfinite(x) else None


def clean(o):
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (float, np.floating)):
        return _f(o)
    return o


def formulas_df(db: Session, spectrum_id: int) -> pd.DataFrame:
    rows = db.execute(select(*[getattr(Formula, c) for c in FORMULA_FIELDS]).where(Formula.spectrum_id == spectrum_id)
                      .order_by(Formula.theo_mz)).all()
    return pd.DataFrame(rows, columns=FORMULA_FIELDS)


def current_spectra(db: Session, codes: Optional[list[str]] = None, project_id: Optional[int] = None) -> list[Spectrum]:
    q = (select(Spectrum).join(Sample).where(Spectrum.is_current)
         .options(selectinload(Spectrum.sample).selectinload(Sample.project)))
    if codes is not None:
        q = q.where(Sample.code.in_(codes))
    if project_id is not None:
        q = q.where(Sample.project_id == project_id)
    return list(db.scalars(q.order_by(Sample.code)).all())


def kendrick(df: pd.DataFrame, base: str = "CH2") -> pd.DataFrame:
    factor = {"CH2": 14.0 / 14.01565, "COO": 44.0 / 43.98983, "H2": 2.0 / 2.01565}[base]
    km = df["theo_mz"] * factor
    return pd.DataFrame({"kmd": np.round(km) - km, "nominal": np.round(km)})


def sample_chart_data(db: Session, sp: Spectrum) -> dict:
    F = formulas_df(db, sp.id)
    K = kendrick(F)
    d = {c: F[c].tolist() for c in ("formula", "theo_mz", "intensity", "rel_intensity", "hc", "oc", "dbe", "C", "O", "N",
                                    "S", "elemental_class", "err_ppm", "lasz_class", "square", "nosc", "ai_mod", "sn")}
    d["kmd"] = K["kmd"].round(5).tolist()
    sq = {f"D{i:02d}": 0.0 for i in range(1, 21)}
    sqi = dict(sq)
    for s, g in F.groupby("square"):
        if s:
            sq[s] = len(g) / len(F)
            sqi[s] = float(g["rel_intensity"].sum())
    by_class = (F.groupby("elemental_class").agg(n=("formula", "size"), w=("rel_intensity", "sum"))
                .reindex(["CHO", "CHON", "CHOS", "CHONS"]).fillna(0))
    by_lasz = F.groupby("lasz_class").agg(n=("formula", "size"), w=("rel_intensity", "sum"))
    return clean({
        "formulas": d,
        "squares": {"count": sq, "intensity": sqi, "hc_bins": hs.HC_BINS, "oc_bins": hs.OC_BINS,
                    "layout": {f"{r},{c}": v for (r, c), v in hs.STANDARD_SQUARES.items()}},
        "classes": {"labels": list(by_class.index), "count": (by_class["n"] / len(F)).tolist(),
                    "intensity": by_class["w"].tolist()},
        "lasz": {"labels": list(by_lasz.index), "count": (by_lasz["n"] / len(F)).tolist(),
                 "intensity": by_lasz["w"].tolist()},
    })


def descriptor_table(spectra: list[Spectrum]) -> pd.DataFrame:
    rows = []
    for sp in spectra:
        r = {"sample": sp.sample.code, "project": sp.sample.project.name if sp.sample.project else "",
             "group": sp.sample.group_label, "quality": sp.quality}
        r.update(sp.descriptors or {})
        rows.append(r)
    return pd.DataFrame(rows)


def assign_groups(spectra: list[Spectrum], by: str, patterns: Optional[dict] = None,
                  manual: Optional[dict] = None) -> dict[str, list[str]]:
    """Группы проб: by = project | group | regex (patterns {группа: regex}) | manual ({группа: [шифры]})."""
    groups: dict[str, list[str]] = {}
    codes = [sp.sample.code for sp in spectra]
    if by == "manual":
        for g, lst in (manual or {}).items():
            sel = [c for c in lst if c in codes]
            if sel:
                groups[g] = sel
        return groups
    for sp in spectra:
        s = sp.sample
        if by == "project":
            g = s.project.name if s.project else "без проекта"
        elif by == "group":
            g = s.group_label or "без группы"
        elif by == "regex":
            g = next((name for name, rx in (patterns or {}).items() if rx and re.search(rx, s.code)), None)
            if g is None:
                continue
        else:
            raise ValueError(f"неизвестный способ группировки: {by}")
        groups.setdefault(g, []).append(s.code)
    return dict(sorted(groups.items()))


def numeric_descriptors(D: pd.DataFrame) -> list[str]:
    cols = [c for c in D.columns if c not in ("sample", "project", "group", "quality")]
    return [c for c in cols if pd.api.types.is_numeric_dtype(D[c])]


def compare(D: pd.DataFrame, groups: dict[str, list[str]], exclude_poor: bool = False) -> dict:
    T = D.copy()
    T["_g"] = ""
    for g, codes in groups.items():
        T.loc[T["sample"].isin(codes), "_g"] = g
    T = T[T["_g"] != ""]
    if exclude_poor:
        T = T[T["quality"] != "poor"]
    cols = [c for c in numeric_descriptors(D) if T[c].notna().any()]
    names = list(groups)
    if len(names) < 2:
        raise ValueError("нужно минимум две группы")
    if len(names) == 2:
        S = hs.compare_groups(T, "_g", names, cols)  # HumSpectra: Манн–Уитни, δ Клиффа, БХ
        a, b = names
        rows = [{"descriptor": r["descriptor"], "label": DESCRIPTOR_LABELS.get(r["descriptor"], r["descriptor"]),
                 "n": [r[f"n_{a}"], r[f"n_{b}"]], "median": [r[f"median_{a}"], r[f"median_{b}"]],
                 "iqr": [r[f"iqr_{a}"], r[f"iqr_{b}"]], "stat": r["U"], "p": r["p"], "q": r["q"],
                 "effect": r["cliffs_delta"]} for r in S.to_dict("records")]
        test, effect = "Манн–Уитни (двусторонний)", "δ Клиффа (a vs b)"
    else:
        rows = []
        for c in cols:
            vals = [T.loc[T["_g"] == g, c].dropna().to_numpy(float) for g in names]
            ok = all(len(v) >= 2 for v in vals) and np.ptp(np.concatenate(vals)) > 0
            H, p = kruskal(*vals) if ok else (np.nan, np.nan)
            rows.append({"descriptor": c, "label": DESCRIPTOR_LABELS.get(c, c), "n": [len(v) for v in vals],
                         "median": [float(np.median(v)) if len(v) else None for v in vals],
                         "iqr": [float(np.subtract(*np.percentile(v, [75, 25]))) if len(v) else None for v in vals],
                         "stat": H, "p": p, "effect": None})
        q = hs.benjamini_hochberg([r["p"] for r in rows])
        for r, qq in zip(rows, q):
            r["q"] = qq
        test, effect = "Краскел–Уоллис", ""
    rows.sort(key=lambda r: (r["p"] is None or not np.isfinite(r["p"]), r["p"] if r["p"] is not None else 1))
    return clean({"groups": names, "sizes": [int((T["_g"] == g).sum()) for g in names], "test": test,
                  "effect_name": effect, "rows": rows})


def pca(D: pd.DataFrame, columns: Optional[list[str]] = None, n: int = 3) -> dict:
    cols = columns or [c for c in numeric_descriptors(D) if c != "n_formulas"]
    X = D[cols].astype(float)
    X = X.loc[:, X.notna().all() & (X.std() > 1e-12)]
    if X.shape[0] < 3 or X.shape[1] < 2:
        raise ValueError("для PCA нужно минимум 3 пробы и 2 меняющихся дескриптора")
    Z = (X - X.mean()) / X.std(ddof=1)
    U, s, Vt = np.linalg.svd(Z.to_numpy(), full_matrices=False)
    k = min(n, len(s))
    var = s ** 2 / np.sum(s ** 2)
    scores = U[:, :k] * s[:k]
    load = Vt[:k].T
    top = np.argsort(-(load[:, 0] ** 2 + load[:, 1] ** 2))[:12] if k >= 2 else np.arange(min(12, len(load)))
    return clean({"samples": D["sample"].tolist(), "scores": scores.tolist(), "explained": var[:k].tolist(),
                  "loadings": {"names": [X.columns[i] for i in top],
                               "labels": [DESCRIPTOR_LABELS.get(X.columns[i], X.columns[i]) for i in top],
                               "values": load[top].tolist()}})


def overlap(db: Session, groups: dict[str, list[str]], min_presence: float = 0.5) -> dict:
    """
    Общие и специфичные формулы групп. Формула «принадлежит» группе, если встречается не менее чем в min_presence
    доле её проб; специфичная — принадлежит только одной группе и не встречается ни в одной пробе других групп.
    """
    codes = [c for lst in groups.values() for c in lst]
    q = (select(Sample.code, Formula.formula, Formula.hc, Formula.oc, Formula.theo_mz, Formula.rel_intensity,
                Formula.elemental_class)
         .join(Spectrum, Spectrum.id == Formula.spectrum_id).join(Sample, Sample.id == Spectrum.sample_id)
         .where(Spectrum.is_current, Sample.code.in_(codes)))
    L = pd.DataFrame(db.execute(q).all(), columns=["sample", "formula", "hc", "oc", "mz", "rel", "cls"])
    if L.empty:
        raise ValueError("у выбранных проб нет формул")
    g_of = {c: g for g, lst in groups.items() for c in lst}
    L["g"] = L["sample"].map(g_of)
    size = {g: len(lst) for g, lst in groups.items()}
    pres = L.groupby(["formula", "g"])["sample"].nunique().unstack(fill_value=0)
    for g in groups:
        if g not in pres:
            pres[g] = 0
    frac = pres[list(groups)].div(pd.Series(size))
    info = L.groupby("formula").agg(hc=("hc", "first"), oc=("oc", "first"), mz=("mz", "first"), cls=("cls", "first"))
    member = frac >= min_presence
    res = {"groups": list(groups), "sizes": [size[g] for g in groups], "min_presence": min_presence, "sets": {}}
    common = member.all(axis=1)
    res["common"] = int(common.sum())
    for g in groups:
        others = [o for o in groups if o != g]
        spec = member[g] & (pres[others].sum(axis=1) == 0 if others else True)
        idx = frac.index[spec]
        meanrel = L[L["formula"].isin(idx) & (L["g"] == g)].groupby("formula")["rel"].mean()
        res["sets"][g] = {"n_member": int(member[g].sum()), "n_specific": int(spec.sum()),
                          "formula": list(idx), "hc": info.loc[idx, "hc"].tolist(), "oc": info.loc[idx, "oc"].tolist(),
                          "mz": info.loc[idx, "mz"].tolist(), "cls": info.loc[idx, "cls"].tolist(),
                          "rel": meanrel.reindex(idx).fillna(0).tolist()}
    ci = frac.index[common]
    res["common_set"] = {"formula": list(ci), "hc": info.loc[ci, "hc"].tolist(), "oc": info.loc[ci, "oc"].tolist()}
    # индекс Жаккара между пробами
    sets = L.groupby("sample")["formula"].apply(set)
    order = [c for c in codes if c in sets.index]
    J = [[len(sets[a] & sets[b]) / max(1, len(sets[a] | sets[b])) for b in order] for a in order]
    res["jaccard"] = {"samples": order, "matrix": J}
    return clean(res)
