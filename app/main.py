"""MassSpectrumWeb: реестр проб, лаб. журнал, графики и статистика по результатам конвейера HumSpectra."""
import base64
import logging
import io
import secrets
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import Body, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from . import analysis as an
from . import config, humspectra, journal
from .db import SessionLocal, get_db, init_db
from .ingest import IngestError, get_or_create_project, ingest_files
from .models import Formula, Project, Sample, Spectrum

BASE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=BASE / "templates")
QUALITY_RU = {"good": "хорошее", "reduced mass accuracy": "сниженная точность", "poor": "плохое", "blank": "бланк",
              "": "—"}
templates.env.globals.update(quality_ru=QUALITY_RU, labels=an.DESCRIPTOR_LABELS)
templates.env.filters["dt"] = lambda d: d.strftime("%d.%m.%Y %H:%M") if d else ""
templates.env.filters["d"] = lambda d: d.strftime("%d.%m.%Y") if d else ""
templates.env.filters["num"] = lambda x, n=3: "" if x is None else (f"{x:.{n}f}" if isinstance(x, float) else str(x))


@asynccontextmanager
async def lifespan(_app):
    init_db()
    log = logging.getLogger("uvicorn.error")
    legacy = config.DATA_PATH / "lab_journal.xlsx"
    if legacy.exists():  # первый запуск: переносим прежний журнал (Excel) в пустую БД
        with SessionLocal() as db:
            if not db.scalar(select(func.count()).select_from(Sample)):
                log.info("Импорт прежнего журнала %s: %s", legacy, journal.import_journal(db, legacy.read_bytes()))
    log.info("HumSpectra pipeline: %s; БД: %s", humspectra.pipeline_dir(), config.DATABASE_URL.split("@")[-1])
    if not config.WEB_PASSWORD:
        log.warning("WEB_PASSWORD не задан — веб-интерфейс и загрузка открыты без пароля")
    if not config.API_KEY:
        log.warning("API_KEY не задан — загрузка скриптом по ключу отключена")
    yield


app = FastAPI(title="MassSpectrumWeb", docs_url="/api/docs", redoc_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")


# ---------- доступ ----------
def _basic_ok(request: Request) -> bool:
    if not config.WEB_PASSWORD:
        return True
    h = request.headers.get("authorization", "")
    if not h.lower().startswith("basic "):
        return False
    try:
        user, _, pwd = base64.b64decode(h[6:]).decode("utf-8").partition(":")
    except Exception:  # noqa: BLE001
        return False
    return secrets.compare_digest(user, config.WEB_USER) and secrets.compare_digest(pwd, config.WEB_PASSWORD)


def _key_ok(request: Request) -> bool:
    k = request.headers.get("x-api-key", "")
    return bool(config.API_KEY) and secrets.compare_digest(k, config.API_KEY)


@app.middleware("http")
async def auth(request: Request, call_next):
    path = request.url.path
    if path == "/api/health" or (path.startswith("/api/upload") and _key_ok(request)):
        return await call_next(request)
    if not _basic_ok(request):
        return Response("Требуется авторизация", 401, {"WWW-Authenticate": 'Basic realm="MassSpectrumWeb", charset="UTF-8"'})
    return await call_next(request)


# ---------- страницы ----------
def _registry(db: Session, project_id: Optional[int] = None):
    q = select(Sample).options(selectinload(Sample.project), selectinload(Sample.spectra)).order_by(Sample.code)
    if project_id is not None:
        q = q.where(Sample.project_id == project_id)
    return list(db.scalars(q).all())


def _page(request: Request, name: str, **ctx):
    return templates.TemplateResponse(request, name, {"page": name.split(".")[0], **ctx})


@app.get("/", include_in_schema=False)
def index():
    return RedirectResponse("/samples")


@app.get("/samples", response_class=HTMLResponse, include_in_schema=False)
def samples_page(request: Request, db: Session = Depends(get_db)):
    samples = _registry(db)
    projects = db.scalars(select(Project).order_by(Project.name)).all()
    with_sp = [s for s in samples if s.current]
    stats = {"samples": len(samples), "with_spectra": len(with_sp), "projects": len(projects),
             "formulas": int(sum(s.current.n_formulas for s in with_sp)),
             "last": max((s.current.uploaded_at for s in with_sp), default=None)}
    return _page(request, "samples.html", samples=samples, projects=projects, stats=stats)


@app.get("/samples/{code}", response_class=HTMLResponse, include_in_schema=False)
def sample_page(code: str, request: Request, db: Session = Depends(get_db)):
    s = _sample(db, code)
    return _page(request, "sample.html", s=s, sp=s.current, groups=an.DESCRIPTOR_GROUPS,
                 projects=db.scalars(select(Project).order_by(Project.name)).all(), fields=journal.SAMPLE_COLUMNS)


@app.get("/projects", response_class=HTMLResponse, include_in_schema=False)
def projects_page(request: Request, db: Session = Depends(get_db)):
    projects = db.scalars(select(Project).options(selectinload(Project.samples).selectinload(Sample.spectra))
                          .order_by(Project.name)).all()
    orphans = db.scalar(select(func.count()).select_from(Sample).where(Sample.project_id.is_(None)))
    return _page(request, "projects.html", projects=projects, orphans=orphans)


@app.get("/projects/{pid}", response_class=HTMLResponse, include_in_schema=False)
def project_page(pid: int, request: Request, db: Session = Depends(get_db)):
    p = db.get(Project, pid) or _404("проект не найден")
    samples = _registry(db, pid)
    sp = [s.current for s in samples if s.current]
    D = an.descriptor_table(sp)
    summary = []
    if len(D):
        for k in an.KEY_DESCRIPTORS:
            if k in D:
                v = D[k].astype(float)
                summary.append({"key": k, "label": an.DESCRIPTOR_LABELS.get(k, k), "median": v.median(),
                                "min": v.min(), "max": v.max()})
    return _page(request, "project.html", p=p, samples=samples, summary=summary)


@app.get("/analysis", response_class=HTMLResponse, include_in_schema=False)
def analysis_page(request: Request, db: Session = Depends(get_db)):
    samples = [s for s in _registry(db) if s.current]
    projects = db.scalars(select(Project).order_by(Project.name)).all()
    return _page(request, "analysis.html", samples=samples, projects=projects, groups=an.DESCRIPTOR_GROUPS)


@app.get("/journal", response_class=HTMLResponse, include_in_schema=False)
def journal_page(request: Request, db: Session = Depends(get_db)):
    return _page(request, "journal.html", samples=_registry(db), fields=journal.SAMPLE_COLUMNS,
                 projects=db.scalars(select(Project).order_by(Project.name)).all())


@app.get("/upload", response_class=HTMLResponse, include_in_schema=False)
def upload_page(request: Request, db: Session = Depends(get_db)):
    return _page(request, "upload.html", projects=db.scalars(select(Project).order_by(Project.name)).all(),
                 api_enabled=bool(config.API_KEY))


# ---------- API: загрузка ----------
@app.post("/api/upload", tags=["загрузка"])
async def upload(files: list[UploadFile] = File(default=[]), file: Optional[UploadFile] = File(default=None),
                 formulas: Optional[UploadFile] = File(default=None), qc: Optional[UploadFile] = File(default=None),
                 sample: Optional[str] = Form(default=None), project: Optional[str] = Form(default=None),
                 db: Session = Depends(get_db)):
    """
    Результаты конвейера: formulas/<проба>.csv и qc/<проба>.json.
    Варианты: formulas+qc (+sample) — одна проба; files — набор CSV/JSON или zip папки результатов run_batch.
    Пробы сопоставляются по имени файла; project назначается пробам без проекта.
    """
    items: list[tuple[str, bytes]] = []
    limit = config.MAX_UPLOAD_MB << 20
    for f in [*files, *(x for x in (file,) if x)]:
        items.append((f.filename or "", await f.read(limit + 1)))
    if formulas is not None:
        nm = sample or Path(formulas.filename or "").stem
        items.append((f"formulas/{nm}.csv", await formulas.read(limit + 1)))
        if qc is not None:
            items.append((f"qc/{nm}.json", await qc.read(limit + 1)))
    if not items:
        raise HTTPException(400, "нет файлов")
    if any(len(d) > limit for _, d in items):
        raise HTTPException(413, f"файл больше {config.MAX_UPLOAD_MB} МБ")
    res = ingest_files(db, items, project or None)
    ok = [r for r in res if r["status"] != "error"]
    return JSONResponse({"results": res, "ok": len(ok), "errors": len(res) - len(ok)},
                        status_code=200 if ok or not res else 422)


# ---------- API: пробы ----------
def _404(msg):
    raise HTTPException(404, msg)


def _sample(db: Session, code: str) -> Sample:
    s = db.scalar(select(Sample).where(Sample.code == code)
                  .options(selectinload(Sample.project), selectinload(Sample.spectra)))
    return s or _404(f"проба {code} не найдена")


def sample_json(s: Sample) -> dict:
    sp = s.current
    return an.clean({
        "code": s.code, "project": s.project.name if s.project else "", "project_id": s.project_id,
        "group": s.group_label, "sample_type": s.sample_type, "location": s.location,
        "sampling_date": s.sampling_date.isoformat() if s.sampling_date else None, "extraction": s.extraction,
        "measured_at": s.measured_at.isoformat() if s.measured_at else None, "operator": s.operator,
        "description": s.description, "notes": s.notes,
        "uploaded_at": sp.uploaded_at.isoformat() if sp else None, "n_formulas": sp.n_formulas if sp else None,
        "quality": sp.quality if sp else None, "assign_tol_ppm": sp.assign_tol_ppm if sp else None,
        "err_rms_ppm": sp.final_err_rms_ppm if sp else None, "n_uploads": len(s.spectra),
    })


@app.get("/api/samples", tags=["пробы"])
def api_samples(project: Optional[str] = None, db: Session = Depends(get_db)):
    out = [sample_json(s) for s in _registry(db)]
    return [r for r in out if not project or r["project"] == project]


@app.get("/api/samples/{code}", tags=["пробы"])
def api_sample(code: str, db: Session = Depends(get_db)):
    s = _sample(db, code)
    d = sample_json(s)
    d["spectra"] = [an.clean({"id": x.id, "uploaded_at": x.uploaded_at.isoformat(), "is_current": x.is_current,
                              "n_formulas": x.n_formulas, "quality": x.quality, "source_name": x.source_name})
                    for x in s.spectra]
    d["descriptors"] = s.current.descriptors if s.current else {}
    d["qc"] = s.current.qc if s.current else {}
    return d


@app.post("/api/samples", tags=["пробы"])
def api_create_sample(data: dict = Body(...), db: Session = Depends(get_db)):
    code = str(data.get("code") or "").strip()
    if not code:
        raise HTTPException(400, "нужен шифр пробы")
    if db.scalar(select(Sample).where(Sample.code == code)):
        raise HTTPException(409, f"проба {code} уже есть")
    s = Sample(code=code)
    db.add(s)
    try:
        journal.apply_fields(db, s, data)
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.commit()
    return sample_json(_sample(db, code))


@app.patch("/api/samples/{code}", tags=["пробы"])
def api_update_sample(code: str, data: dict = Body(...), db: Session = Depends(get_db)):
    s = _sample(db, code)
    new_code = str(data.get("code") or code).strip()
    if new_code != code:
        if db.scalar(select(Sample).where(Sample.code == new_code)):
            raise HTTPException(409, f"проба {new_code} уже есть")
        s.code = new_code
    try:
        journal.apply_fields(db, s, data)
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.commit()
    return sample_json(_sample(db, new_code))


@app.delete("/api/samples/{code}", tags=["пробы"])
def api_delete_sample(code: str, db: Session = Depends(get_db)):
    s = _sample(db, code)
    db.delete(s)
    db.commit()
    return {"deleted": code}


@app.delete("/api/spectra/{sid}", tags=["пробы"])
def api_delete_spectrum(sid: int, db: Session = Depends(get_db)):
    sp = db.get(Spectrum, sid) or _404("загрузка не найдена")
    sample_id, was_current = sp.sample_id, sp.is_current
    db.delete(sp)
    db.flush()
    if was_current:
        nxt = db.scalar(select(Spectrum).where(Spectrum.sample_id == sample_id).order_by(Spectrum.uploaded_at.desc()))
        if nxt:
            nxt.is_current = True
    db.commit()
    return {"deleted": sid}


@app.post("/api/spectra/{sid}/current", tags=["пробы"])
def api_make_current(sid: int, db: Session = Depends(get_db)):
    sp = db.get(Spectrum, sid) or _404("загрузка не найдена")
    for x in db.scalars(select(Spectrum).where(Spectrum.sample_id == sp.sample_id)):
        x.is_current = x.id == sid
    db.commit()
    return {"current": sid}


@app.get("/api/samples/{code}/chart-data", tags=["графики"])
def api_chart_data(code: str, db: Session = Depends(get_db)):
    s = _sample(db, code)
    if not s.current:
        raise HTTPException(404, "у пробы нет загруженного спектра")
    return an.sample_chart_data(db, s.current)


@app.get("/api/samples/{code}/formulas.csv", tags=["графики"])
def api_formulas_csv(code: str, db: Session = Depends(get_db)):
    s = _sample(db, code)
    if not s.current:
        raise HTTPException(404, "у пробы нет загруженного спектра")
    F = an.formulas_df(db, s.current.id)
    return _csv(F, f"{code}_formulas.csv")


def _csv(df, filename):
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return Response(buf.getvalue().encode("utf-8-sig"), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"})


# ---------- API: проекты ----------
@app.get("/api/projects", tags=["проекты"])
def api_projects(db: Session = Depends(get_db)):
    rows = db.execute(select(Project, func.count(Sample.id)).outerjoin(Sample).group_by(Project.id)
                      .order_by(Project.name)).all()
    return [{"id": p.id, "name": p.name, "description": p.description, "lead": p.lead, "samples": n} for p, n in rows]


@app.post("/api/projects", tags=["проекты"])
def api_create_project(data: dict = Body(...), db: Session = Depends(get_db)):
    name = str(data.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "нужно название проекта")
    p = get_or_create_project(db, name)
    p.description = data.get("description", p.description) or ""
    p.lead = data.get("lead", p.lead) or ""
    db.commit()
    return {"id": p.id, "name": p.name}


@app.patch("/api/projects/{pid}", tags=["проекты"])
def api_update_project(pid: int, data: dict = Body(...), db: Session = Depends(get_db)):
    p = db.get(Project, pid) or _404("проект не найден")
    for k in ("name", "description", "lead"):
        if k in data:
            setattr(p, k, str(data[k] or "").strip())
    if not p.name:
        raise HTTPException(400, "пустое название")
    db.commit()
    return {"id": p.id, "name": p.name}


@app.delete("/api/projects/{pid}", tags=["проекты"])
def api_delete_project(pid: int, db: Session = Depends(get_db)):
    p = db.get(Project, pid) or _404("проект не найден")
    for s in p.samples:
        s.project_id = None
    db.delete(p)
    db.commit()
    return {"deleted": pid}


# ---------- API: анализ ----------
def _select_spectra(db: Session, body: dict) -> list[Spectrum]:
    codes = body.get("samples")
    sp = an.current_spectra(db, codes=codes if codes else None, project_id=body.get("project_id"))
    if not sp:
        raise HTTPException(400, "нет проб с загруженными спектрами")
    return sp


@app.get("/api/descriptors", tags=["анализ"])
def api_descriptors(samples: Optional[str] = None, project_id: Optional[int] = None, format: str = "json",
                    db: Session = Depends(get_db)):
    sp = an.current_spectra(db, codes=samples.split(",") if samples else None, project_id=project_id)
    D = an.descriptor_table(sp)
    if format == "csv":
        return _csv(D, f"descriptors_{datetime.now():%Y%m%d}.csv")
    return an.clean({"columns": list(D.columns), "rows": D.to_dict("records")})


@app.post("/api/analysis/compare", tags=["анализ"])
def api_compare(body: dict = Body(...), db: Session = Depends(get_db)):
    sp = _select_spectra(db, body)
    groups = an.assign_groups(sp, body.get("by", "group"), body.get("patterns"), body.get("manual"))
    if len(groups) < 2:
        raise HTTPException(400, f"получилось групп: {len(groups)} — нужно минимум две")
    D = an.descriptor_table(sp)
    try:
        res = an.compare(D, groups, bool(body.get("exclude_poor")))
    except ValueError as e:
        raise HTTPException(400, str(e))
    sel = [c for lst in groups.values() for c in lst]
    Dsel = D[D["sample"].isin(sel)]
    res["membership"] = groups
    res["table"] = an.clean(Dsel.to_dict("records"))
    return res


@app.post("/api/analysis/pca", tags=["анализ"])
def api_pca(body: dict = Body(...), db: Session = Depends(get_db)):
    sp = _select_spectra(db, body)
    D = an.descriptor_table(sp)
    try:
        res = an.pca(D, body.get("columns"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    groups = an.assign_groups(sp, body.get("by", "group"), body.get("patterns"), body.get("manual"))
    g_of = {c: g for g, lst in groups.items() for c in lst}
    res["group"] = [g_of.get(c, "") for c in res["samples"]]
    return res


@app.post("/api/analysis/overlap", tags=["анализ"])
def api_overlap(body: dict = Body(...), db: Session = Depends(get_db)):
    sp = _select_spectra(db, body)
    groups = an.assign_groups(sp, body.get("by", "group"), body.get("patterns"), body.get("manual"))
    if not groups:
        raise HTTPException(400, "нет групп")
    try:
        return an.overlap(db, groups, float(body.get("min_presence", 0.5)))
    except ValueError as e:
        raise HTTPException(400, str(e))


# ---------- API: журнал ----------
@app.get("/journal/export.xlsx", include_in_schema=False)
def journal_export(db: Session = Depends(get_db)):
    data = journal.export_journal(db)
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f"attachment; filename=lab_journal_{datetime.now():%Y%m%d}.xlsx"})


@app.get("/journal/template.xlsx", include_in_schema=False)
def journal_template(db: Session = Depends(get_db)):
    data = journal.build_workbook([], list(db.scalars(select(Project).order_by(Project.name)).all()))
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": "attachment; filename=lab_journal_template.xlsx"})


@app.post("/api/journal/import", tags=["журнал"])
async def journal_import(file: UploadFile = File(...), db: Session = Depends(get_db)):
    try:
        return journal.import_journal(db, await file.read())
    except Exception as e:  # noqa: BLE001
        db.rollback()
        raise HTTPException(400, f"не удалось импортировать: {e}")


@app.get("/api/health", tags=["служебное"])
def health(db: Session = Depends(get_db)):
    return {"status": "ok", "samples": db.scalar(select(func.count()).select_from(Sample)),
            "spectra": db.scalar(select(func.count()).select_from(Spectrum)),
            "formulas": db.scalar(select(func.count()).select_from(Formula)),
            "humspectra_pipeline": str(humspectra.pipeline_dir())}
