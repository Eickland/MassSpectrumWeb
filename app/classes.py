"""
Классы формул на диаграмме Ван Кревелена — по Перминовой и по Kellerman.

Определения повторяют HumSpectra.mass_descriptors.mol_class(how='perminova' | 'kellerman'),
чтобы сайт считал те же зоны, что и конвейер:

* Перминова (Perminova I.V., Pure Appl. Chem. 2019, 91(5), 851–864) — области H/C–O/C:
  конденсированные и гидролизуемые танины, фенилпропаноиды, терпеноиды, липиды, пептиды, углеводы;
* Kellerman (Kellerman et al., Nat. Commun. 2014, 5, 3804) — области по H/C, O/C и индексу
  ароматичности AI: ненасыщенные/ароматические/конденсированные с низким и высоким O/C,
  алифатические, липиды, N-содержащие.

Классы считаются по каждой формуле (для раскраски Ван Кревелена) и долями по пробе
(для дескрипторов и статистики). В БД отдельные колонки не нужны: классы восстанавливаются
из C, H, O, N, S, H/C и O/C.
"""
from typing import Dict, Iterable, Sequence

import numpy as np
import pandas as pd

#: (ключ, подпись для графиков, цвет) — порядок как в HumSpectra.get_mol_class
PERMINOVA_ZONES = [
    ("condensed_tanins", "конденсир. танины", "#ffd92f"),
    ("hydrolyzable_tanins", "гидролиз. танины", "#66c2a5"),
    ("phenylisopropanoids", "фенилпропаноиды", "#fc8d62"),
    ("terpenoids", "терпеноиды", "#8da0cb"),
    ("lipids", "липиды", "#e5c494"),
    ("proteins", "пептиды", "#a6d854"),
    ("carbohydrates", "углеводы", "#e78ac3"),
    ("undefinded", "не опред.", "#a0a9b3"),
]

KELLERMAN_ZONES = [
    ("unsat_lowOC", "ненасыщ., низкий O/C", "#2a78d6"),
    ("unsat_highOC", "ненасыщ., высокий O/C", "#7fb3e8"),
    ("condensed_lowOC", "конденсир., низкий O/C", "#6a4c93"),
    ("condensed_highOC", "конденсир., высокий O/C", "#a98bc9"),
    ("aromatic_lowOC", "ароматич., низкий O/C", "#d9762b"),
    ("aromatic_highOC", "ароматич., высокий O/C", "#e8b06a"),
    ("aliphatics", "алифатические", "#2e8b57"),
    ("lipids", "липиды", "#d4a017"),
    ("N-satureted", "N-содержащие", "#d6457a"),
    ("undefinded", "не опред.", "#a0a9b3"),
]

#: длинные подписи для таблиц дескрипторов
PERMINOVA_LABELS = {
    "condensed_tanins": "конденсированные танины",
    "hydrolyzable_tanins": "гидролизуемые танины",
    "phenylisopropanoids": "фенилпропаноиды",
    "terpenoids": "терпеноиды",
    "lipids": "липиды",
    "proteins": "пептиды",
    "carbohydrates": "углеводы",
    "undefinded": "не определено",
}
KELLERMAN_LABELS = {
    "unsat_lowOC": "ненасыщенные, низкий O/C",
    "unsat_highOC": "ненасыщенные, высокий O/C",
    "condensed_lowOC": "конденсированные, низкий O/C",
    "condensed_highOC": "конденсированные, высокий O/C",
    "aromatic_lowOC": "ароматические, низкий O/C",
    "aromatic_highOC": "ароматические, высокий O/C",
    "aliphatics": "алифатические",
    "lipids": "липиды",
    "N-satureted": "N-содержащие",
    "undefinded": "не определено",
}

PERMINOVA_KEYS = [k for k, *_ in PERMINOVA_ZONES]
KELLERMAN_KEYS = [k for k, *_ in KELLERMAN_ZONES]


def _series(F: pd.DataFrame, *names: str) -> pd.Series:
    """Числовая колонка по первому найденному имени (H/C или hc)."""
    for n in names:
        if n in F:
            return pd.to_numeric(F[n], errors="coerce").astype(float)
    raise KeyError(f"нет колонки {names}")


def ai_index(F: pd.DataFrame) -> pd.Series:
    """
    Индекс ароматичности AI = DBE_AI / CAI (Koch & Dittmar 2006) без обрезки по нулю —
    как в HumSpectra.mass_descriptors.ai. Для CAI = 0 возвращается NaN (зона «не определено»).
    """
    C, H, O, N, S = (_series(F, e) for e in "CHONS")
    cai = C - O - N - S
    dbe_ai = 1 + C - O - S - 0.5 * (H + N)
    return (dbe_ai / cai.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)


def perminova_classes(hc: Sequence[float], oc: Sequence[float]) -> np.ndarray:
    """Зоны Перминовой по H/C и O/C (границы — как в HumSpectra get_zone_perm)."""
    hc = np.asarray(hc, dtype=float)
    oc = np.asarray(oc, dtype=float)
    lo, mid = oc < 0.5, oc <= 1.0
    return np.select(
        [lo & (hc < 1.0),
         lo & (hc < 1.4),
         lo & (hc < 1.8),
         lo & (hc <= 2.2) & (oc < 0.25),
         lo & (hc <= 2.2),
         lo,
         mid & (hc < 1.4),
         mid & (hc <= 2.2)],
        ["condensed_tanins", "phenylisopropanoids", "terpenoids", "lipids", "proteins", "undefinded",
         "hydrolyzable_tanins", "carbohydrates"],
        default="undefinded",
    )


def kellerman_classes(hc: Sequence[float], oc: Sequence[float], ai: Sequence[float],
                      n: Sequence[float]) -> np.ndarray:
    """Зоны Kellerman по H/C, O/C, AI и числу атомов N (как в HumSpectra get_zone_kell)."""
    hc = np.asarray(hc, dtype=float)
    oc = np.asarray(oc, dtype=float)
    ai = np.asarray(ai, dtype=float)
    n = np.asarray(n, dtype=float)
    high_hc = hc >= 1.5
    cond = [high_hc & (oc < 0.3) & (n == 0),
            high_hc & (n >= 1),
            high_hc,
            (hc < 1.5) & (ai < 0.5) & (oc <= 0.5),
            (hc < 1.5) & (ai < 0.5),
            (ai > 0.5) & (ai <= 0.67) & (oc <= 0.5),
            (ai > 0.5) & (ai <= 0.67),
            (ai > 0.67) & (oc <= 0.5),
            ai > 0.67]
    return np.select(cond, ["lipids", "N-satureted", "aliphatics", "unsat_lowOC", "unsat_highOC",
                            "aromatic_lowOC", "aromatic_highOC", "condensed_lowOC", "condensed_highOC"],
                     default="undefinded")


def add_formula_classes(F: pd.DataFrame) -> pd.DataFrame:
    """Добавляет к таблице формул AI_std, class_perminova и class_kellerman."""
    F = F.copy()
    hc = _series(F, "H/C", "hc")
    oc = _series(F, "O/C", "oc")
    F["AI_std"] = ai_index(F)
    F["class_perminova"] = perminova_classes(hc, oc)
    F["class_kellerman"] = kellerman_classes(hc, oc, F["AI_std"], _series(F, "N", "n"))
    return F


def _fractions(F: pd.DataFrame, column: str, keys: Iterable[str], prefix: str) -> Dict[str, float]:
    if len(F) == 0:
        return {f"{prefix}_{k}": 0.0 for k in keys}
    values = F[column].to_numpy()
    return {f"{prefix}_{k}": float((values == k).mean()) for k in keys}


def descriptor_fractions(F: pd.DataFrame) -> Dict[str, float]:
    """
    Доли формул по зонам Перминовой и Kellerman для дескрипторов пробы:
    `perm_<зона>`, `kell_<зона>` (по числу формул, как lasz_* в HumSpectra).
    """
    if len(F) == 0:
        return {}
    out = _fractions(F, "class_perminova", PERMINOVA_KEYS, "perm")
    out.update(_fractions(F, "class_kellerman", KELLERMAN_KEYS, "kell"))
    return out


def distribution(F: pd.DataFrame, column: str, zones: Sequence[tuple]) -> dict:
    """Распределение формул по зонам: число, доля по числу и доля по интенсивности — для графиков."""
    keys = [k for k, *_ in zones]
    if len(F) == 0:
        return {"keys": keys, "labels": [lab for _, lab, _ in zones], "colors": [c for *_, c in zones],
                "count": [0.0] * len(keys), "intensity": [0.0] * len(keys)}
    rel = (pd.to_numeric(F["rel_intensity"], errors="coerce") if "rel_intensity" in F
           else pd.to_numeric(F["intensity"], errors="coerce") / pd.to_numeric(F["intensity"], errors="coerce").sum())
    values = F[column].to_numpy()
    cnt = [float((values == k).mean()) for k in keys]
    inten = [float(rel[values == k].sum()) for k in keys]
    return {"keys": keys, "labels": [lab for _, lab, _ in zones], "colors": [c for *_, c in zones],
            "count": cnt, "intensity": inten}
