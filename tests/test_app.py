"""
Тесты MassSpectrumWeb: загрузка результатов конвейера, журнал, анализ.
Нужен HumSpectra рядом (../HumSpectra) или HUMSPECTRA_PIPELINE_DIR. Запуск: pytest tests
"""
import io
import json
import os
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    os.environ["DATA_PATH"] = str(tmp_path_factory.mktemp("data"))
    os.environ["DATABASE_URL"] = f"sqlite:///{os.environ['DATA_PATH']}/t.sqlite"
    os.environ["API_KEY"] = "test-key"
    os.environ["WEB_PASSWORD"] = ""
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        yield c


def fake_formulas(seed, hc=(0.8, 1.6), n=300):
    """Таблица формул в формате pipeline (только колонки, которые сервер читает)."""
    rng = np.random.default_rng(seed)
    rows, seen = [], set()
    while len(rows) < n:
        C = int(rng.integers(8, 40)); O = int(rng.integers(2, max(3, int(C * 0.7))))
        H = int(round(C * rng.uniform(*hc))); N = int(rng.random() < .1); S = int(rng.random() < .05)
        H += (H + N) % 2 == 1  # чётность для [M−H]⁻ не важна для теста, лишь бы уникально
        f = f"C{C}H{H}O{O}" + ("N1" if N else "") + ("S1" if S else "")
        if f in seen or H / C > 2 or O / C >= 1:
            continue
        seen.add(f)
        mz = C * 12 + H * 1.007825 + O * 15.994915 + N * 14.003074 + S * 31.972071 - 1.007276
        rows.append(dict(formula=f, C=C, H=H, O=O, N=N, S=S, theo_mz=mz, mz_cal=mz * (1 + rng.normal(0, 1e-7)),
                         err_ppm=rng.normal(0, .1), intensity=float(np.exp(rng.normal(10, 1.5))), SN=float(rng.uniform(6, 500))))
    return pd.DataFrame(rows)


def csv_bytes(df):
    return df.to_csv(index=False).encode()


def qc_bytes(name, quality="good"):
    return json.dumps({"sample": name, "quality": quality, "peaks": 1000, "assign_tol_ppm": 0.5, "sigma_strong_ppm": 0.1,
                       "calibration": {"n": 300, "rms": 0.08}, "final_13C_confirmed_pct": 95.0,
                       "params": {"sn": 6.0}, "descriptors": {"ignored": 1}}).encode()


def upload_zip(client, samples, project="Тест"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, df in samples.items():
            z.writestr(f"out/formulas/{name}.csv", csv_bytes(df))
            z.writestr(f"out/qc/{name}.json", qc_bytes(name))
        z.writestr("out/summary_qc.csv", "sample\nx\n")
        z.writestr("out/all_formulas.csv", "sample\nx\n")
    return client.post("/api/upload", headers={"X-API-Key": "test-key"},
                       files=[("files", ("out.zip", buf.getvalue(), "application/zip"))], data={"project": project})


def test_upload_zip_and_registry(client):
    S = {f"ADOM-A-{i}_000001": fake_formulas(i, (1.2, 1.8)) for i in range(4)}
    S.update({f"ADOM-B-{i}_000001": fake_formulas(10 + i, (0.6, 1.2)) for i in range(4)})
    r = upload_zip(client, S)
    assert r.status_code == 200, r.text
    assert r.json()["ok"] == 8 and r.json()["errors"] == 0
    reg = client.get("/api/samples").json()
    assert len(reg) == 8 and all(x["project"] == "Тест" and x["n_formulas"] == 300 and x["quality"] == "good" for x in reg)
    assert client.get("/samples").status_code == 200


def test_descriptors_match_humspectra(client):
    from app import humspectra as hs
    df = fake_formulas(0, (1.2, 1.8))
    expected = hs.sample_descriptors(hs.formula_metrics(df).assign(rel_intensity=lambda d: d.intensity / d.intensity.sum()))
    got = client.get("/api/samples/ADOM-A-0_000001").json()["descriptors"]
    for k, v in expected.items():
        assert got[k] == pytest.approx(v, rel=1e-9, abs=1e-12), k


def test_reupload_same_is_unchanged_new_is_history(client):
    name = "ADOM-A-0_000001"
    df = fake_formulas(0, (1.2, 1.8))
    r = client.post("/api/upload", headers={"X-API-Key": "test-key"}, files={"formulas": (f"{name}.csv", csv_bytes(df))})
    assert r.json()["results"][0]["status"] == "unchanged"
    r = client.post("/api/upload", headers={"X-API-Key": "test-key"},
                    files={"formulas": (f"{name}.csv", csv_bytes(df.head(200))), "qc": (f"{name}.json", qc_bytes(name, "poor"))})
    assert r.json()["results"][0]["status"] == "created"
    s = client.get(f"/api/samples/{name}").json()
    assert s["n_formulas"] == 200 and s["quality"] == "poor" and len(s["spectra"]) == 2
    old = next(x for x in s["spectra"] if not x["is_current"])
    client.post(f"/api/spectra/{old['id']}/current")
    assert client.get(f"/api/samples/{name}").json()["n_formulas"] == 300


def test_reupload_old_measurement_is_idempotent(client):
    name = "ADOM-HIST-1_000001"
    first, second = fake_formulas(100), fake_formulas(101)
    for df in (first, second):
        r = client.post("/api/upload", headers={"X-API-Key": "test-key"},
                        files={"formulas": (f"{name}.csv", csv_bytes(df))})
        assert r.json()["results"][0]["status"] == "created"
    s = client.get(f"/api/samples/{name}").json()
    assert len(s["spectra"]) == 2 and s["n_formulas"] == len(second)
    # повторная загрузка первой съёмки не должна добавлять третью запись в историю
    r = client.post("/api/upload", headers={"X-API-Key": "test-key"},
                    files={"formulas": (f"{name}.csv", csv_bytes(first))})
    assert r.json()["results"][0]["status"] == "unchanged"
    s = client.get(f"/api/samples/{name}").json()
    assert len(s["spectra"]) == 2 and s["n_formulas"] == len(first)


def test_minimal_csv_and_journal_suffix_match(client):
    # проба есть в журнале без суффикса прибора; CSV — только формула и интенсивность
    client.post("/api/samples", json={"code": "PEAT-7", "project": "Торф", "group_label": "T"})
    df = fake_formulas(42)[["formula", "intensity", "theo_mz"]]
    r = client.post("/api/upload", headers={"X-API-Key": "test-key"}, files={"formulas": ("PEAT-7_000001.csv", csv_bytes(df))})
    assert r.json()["results"][0]["sample"] == "PEAT-7"
    s = client.get("/api/samples/PEAT-7").json()
    assert s["n_formulas"] == 300 and s["project"] == "Торф"
    cd = client.get("/api/samples/PEAT-7/chart-data").json()
    assert len(cd["formulas"]["formula"]) == 300 and abs(sum(cd["squares"]["count"].values()) - 1) < 0.05


def test_bad_csv_is_reported(client):
    r = client.post("/api/upload", headers={"X-API-Key": "test-key"}, files={"formulas": ("X.csv", b"a,b\n1,2\n")})
    assert r.status_code == 422 and r.json()["results"][0]["status"] == "error"


def test_compare_pca_overlap(client):
    body = {"samples": [f"ADOM-{g}-{i}_000001" for g in "AB" for i in range(4)], "by": "regex",
            "patterns": {"A": "-A-", "B": "-B-"}}
    r = client.post("/api/analysis/compare", json=body)
    assert r.status_code == 200, r.text
    rows = {x["descriptor"]: x for x in r.json()["rows"]}
    assert rows["wmean_H/C"]["effect"] == 1.0 and rows["wmean_H/C"]["p"] < 0.05     # группа A — выше H/C
    r = client.post("/api/analysis/pca", json=body)
    P = r.json()
    assert r.status_code == 200 and len(P["scores"]) == 8
    pc1 = np.array([s[0] for s in P["scores"]])
    assert np.sign(pc1[:4]).tolist() == [np.sign(pc1[0])] * 4 and np.sign(pc1[4:]).tolist() == [-np.sign(pc1[0])] * 4
    r = client.post("/api/analysis/overlap", json=body)
    O = r.json()
    assert r.status_code == 200 and set(O["sets"]) == {"A", "B"} and len(O["jaccard"]["matrix"]) == 8


def test_three_groups_kruskal(client):
    body = {"by": "regex", "patterns": {"A": "-A-[01]", "A2": "-A-[23]", "B": "-B-"}}
    r = client.post("/api/analysis/compare", json=body)
    assert r.status_code == 200 and r.json()["test"].startswith("Краскел")


def test_journal_roundtrip_and_old_format(client):
    from openpyxl import Workbook, load_workbook
    x = client.get("/journal/export.xlsx")
    wb = load_workbook(io.BytesIO(x.content))
    assert wb.sheetnames == ["Пробы", "Проекты", "Справка"]
    ws = wb["Пробы"]
    codes = [r[0] for r in ws.iter_rows(min_row=2, values_only=True)]
    assert "PEAT-7" in codes
    # заполняем место и дату и импортируем обратно
    i = codes.index("PEAT-7") + 2
    ws.cell(i, 5, "болото Тёплое"); ws.cell(i, 6, "05.07.2026")
    b = io.BytesIO(); wb.save(b)
    r = client.post("/api/journal/import", files={"file": ("j.xlsx", b.getvalue())})
    assert r.status_code == 200 and not r.json()["errors"], r.text
    s = client.get("/api/samples/PEAT-7").json()
    assert s["location"] == "болото Тёплое" and s["sampling_date"] == "2026-07-05" and s["group"] == "T"
    # старый формат: лист Samples, Name/Project/Description/Notes
    old = Workbook(); w = old.active; w.title = "Samples"
    w.append(["Name", "Project", "Description", "Notes"]); w.append(["ADOM_B_2025_000001_vk", "Диплом", None, None])
    b = io.BytesIO(); old.save(b)
    r = client.post("/api/journal/import", files={"file": ("old.xlsx", b.getvalue())})
    assert r.json()["created"] == 1
    assert client.get("/api/samples/ADOM_B_2025_000001_vk").json()["project"] == "Диплом"


def test_project_masslists_zip(client):
    S = {f"ADOM-ML-{i}_000001": fake_formulas(200 + i) for i in range(2)}
    r = upload_zip(client, S, project="Масс-листы")
    assert r.status_code == 200, r.text
    projects = {p["name"]: p["id"] for p in client.get("/api/projects").json()}
    pid = projects["Масс-листы"]
    r = client.get(f"/api/projects/{pid}/masslists.zip")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        names = set(z.namelist())
        assert {"all_mass_lists.csv", "README.txt", "ADOM-ML-0_000001.csv", "ADOM-ML-1_000001.csv"} <= names
        body = z.read("ADOM-ML-0_000001.csv").decode("utf-8-sig")
        head, *rows = body.strip().splitlines()
        assert head.split(",") == ["mz_cal", "intensity", "rel_intensity", "formula", "elemental_class",
                                   "C", "H", "O", "N", "S", "DBE", "AI_mod", "err_ppm"]
        assert len(rows) == 300
        mz = [float(x.split(",")[0]) for x in rows]
        assert mz == sorted(mz)
        combined = z.read("all_mass_lists.csv").decode("utf-8-sig").strip().splitlines()
        assert len(combined) == 601 and combined[0].startswith("sample,")
    # проект без спектров — понятная ошибка, а не пустой архив
    pid2 = client.post("/api/projects", json={"name": "Пустой проект"}).json()["id"]
    assert client.get(f"/api/projects/{pid2}/masslists.zip").status_code == 404
    page = client.get(f"/projects/{pid}")
    assert page.status_code == 200 and "Масс-листы проекта (ZIP)" in page.text
    assert f"/api/projects/{pid}/masslists.zip" in page.text


def test_pages_render(client):
    for u in ["/samples", "/samples/PEAT-7", "/samples/ADOM_B_2025_000001_vk", "/projects", "/projects/1",
              "/analysis", "/analysis?project_id=1", "/journal", "/upload"]:
        assert client.get(u).status_code == 200, u


def test_api_key_required_when_password_set(client, monkeypatch):
    from app import config
    monkeypatch.setattr(config, "WEB_PASSWORD", "secret")
    assert client.get("/samples").status_code == 401
    assert client.get("/samples", auth=("lab", "secret")).status_code == 200
    r = client.post("/api/upload", files={"formulas": ("X.csv", b"a")})
    assert r.status_code == 401
    assert client.get("/api/health").status_code == 200
