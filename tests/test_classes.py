"""Границы зон Перминовой и Kellerman — сверка с HumSpectra.mass_descriptors.mol_class."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import classes as cl  # noqa: E402


def perm(hc, oc):
    return cl.perminova_classes([hc], [oc])[0]


def kell(hc, oc, ai, n=0):
    return cl.kellerman_classes([hc], [oc], [ai], [n])[0]


def test_perminova_zones():
    assert perm(0.8, 0.2) == "condensed_tanins"
    assert perm(1.2, 0.2) == "phenylisopropanoids"
    assert perm(1.6, 0.2) == "terpenoids"
    assert perm(2.0, 0.1) == "lipids"
    assert perm(2.0, 0.3) == "proteins"
    assert perm(2.3, 0.3) == "undefinded"
    assert perm(1.0, 0.8) == "hydrolyzable_tanins"      # O/C >= 0.5, H/C < 1.4
    assert perm(1.6, 0.8) == "carbohydrates"
    assert perm(2.3, 0.8) == "undefinded"
    assert perm(1.6, 1.2) == "undefinded"


def test_kellerman_zones():
    assert kell(1.6, 0.2, 0.8) == "lipids"
    assert kell(1.6, 0.5, 0.8, n=1) == "N-satureted"
    assert kell(1.6, 0.5, 0.8) == "aliphatics"
    assert kell(1.2, 0.3, 0.2) == "unsat_lowOC"
    assert kell(1.2, 0.6, 0.2) == "unsat_highOC"
    assert kell(1.2, 0.3, 0.6) == "aromatic_lowOC"
    assert kell(1.2, 0.6, 0.6) == "aromatic_highOC"
    assert kell(1.2, 0.3, 0.8) == "condensed_lowOC"
    assert kell(1.2, 0.6, 0.8) == "condensed_highOC"
    assert kell(1.2, 0.6, 0.5) == "undefinded"          # ровно 0.5 — не попадает ни в одну зону
    assert kell(1.2, 0.6, 0.67) == "aromatic_highOC"    # граница включительно


def test_ai_index_matches_humspectra_formula():
    # C10H16O4: DBE_AI = 1+10-4-0.5*16 = -1, CAI = 10-4 = 6 -> AI = -1/6
    F = {"C": [10], "H": [16], "O": [4], "N": [0], "S": [0]}
    import pandas as pd
    df = pd.DataFrame(F)
    assert abs(cl.ai_index(df).iloc[0] - (-1 / 6)) < 1e-12
    # CAI = 0 -> NaN (зона «не определено»), без падения
    df0 = pd.DataFrame({"C": [4], "H": [8], "O": [4], "N": [0], "S": [0]})
    assert np.isnan(cl.ai_index(df0).iloc[0])


def test_distribution_sums():
    import pandas as pd
    F = pd.DataFrame({"C": [10, 12], "H": [12, 18], "O": [4, 4], "N": [0, 0], "S": [0, 0],
                      "H/C": [1.2, 1.5], "O/C": [0.4, 0.33], "intensity": [1.0, 3.0], "rel_intensity": [0.25, 0.75]})
    F = cl.add_formula_classes(F)
    d = cl.distribution(F, "class_perminova", cl.PERMINOVA_ZONES)
    assert abs(sum(d["count"]) - 1) < 1e-12 and abs(sum(d["intensity"]) - 1) < 1e-12
    assert len(d["labels"]) == len(d["keys"]) == len(d["colors"])
    frac = cl.descriptor_fractions(F)
    assert abs(sum(v for k, v in frac.items() if k.startswith("perm_")) - 1) < 1e-12
    assert abs(sum(v for k, v in frac.items() if k.startswith("kell_")) - 1) < 1e-12
