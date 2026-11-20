#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Загрузка пакета «КНП 2026», собранного knp_export.py, в MassSpectrumWeb.

Что делает
----------
1. Импортирует журнал `<пакет>/journal.xlsx` через `/api/journal/import` — шифры, группы,
   даты отбора и даты съёмки. Для этого нужен пароль сайта (HTTP Basic), потому что
   ключ X-API-Key открывает только загрузку спектров.
2. Загружает по одной съёмке `formulas/*.csv` + `qc/*.json` в `/api/upload` с ключом
   X-API-Key. Сервер сопоставляет пробу по шифру и пересчитывает дескрипторы сам.
   Повторная съёмка той же пробы (BC6-9, ВС1-2, К2-3, К4-1, К4-12) добавляется в историю,
   актуальной становится последняя по дате.
3. Пишет `<пакет>/upload_log.csv`; повторный запуск безопасен: тот же CSV даёт
   «без изменений».

Адрес и ключ
------------
По умолчанию — `secret_uploader.json` ({"API_URL": ".../api/upload", "API_KEY": "..."}),
путь можно задать `--secret` или переменной MSWEB_SECRET. Логин/пароль сайта —
`--web-user/--web-password`, переменные MSWEB_WEB_USER/MSWEB_WEB_PASSWORD или `.env` репозитория.

Примеры
-------
    python scripts/knp_upload.py --dry-run
    python scripts/knp_upload.py --web-password "…"                    # локальный сервер
    python scripts/knp_upload.py --url https://ms.example.ru/api/upload --key … --web-password …
    python scripts/knp_upload.py --skip-journal --only BC6-9 K4-12
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import knp_common as kc  # noqa: E402

DEFAULT_SECRET = Path(os.getenv("MSWEB_SECRET", r"C:\Users\Kirill\Desktop\Lab\secret_uploader.json"))


def _dotenv(path: Path) -> dict:
    out = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _base_url(api_url: str) -> str:
    """https://host/api/upload → https://host"""
    u = api_url.rstrip("/")
    return u[:-len("/api/upload")] if u.endswith("/api/upload") else u


def _post(session: requests.Session, url: str, *, retries: int, timeout: int, **kwargs):
    last = None
    for n in range(1, retries + 1):
        try:
            r = session.post(url, timeout=timeout, **kwargs)
            if r.status_code >= 500 and n < retries:
                last = r
                time.sleep(2 * n)
                continue
            return r, n
        except (requests.ConnectionError, requests.Timeout) as e:
            last = e
            if n < retries:
                time.sleep(2 * n)
    if isinstance(last, requests.Response):
        return last, retries
    raise last  # type: ignore[misc]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("package", nargs="?", default=str(kc.DEFAULT_EXPORT), help="папка пакета (с manifest.csv)")
    ap.add_argument("--url", default="", help="адрес /api/upload")
    ap.add_argument("--key", default="", help="X-API-Key")
    ap.add_argument("--secret", default=str(DEFAULT_SECRET), help="JSON с API_URL и API_KEY")
    ap.add_argument("--web-user", default="", help="логин сайта для импорта журнала (HTTP Basic)")
    ap.add_argument("--web-password", default="", help="пароль сайта для импорта журнала")
    ap.add_argument("--skip-journal", action="store_true", help="не импортировать журнал, только спектры")
    ap.add_argument("--project", default="", help="проект для проб без проекта (по умолчанию из manifest)")
    ap.add_argument("--only", nargs="*", default=[], help="загрузить только эти шифры (например BC6-9 K4-12)")
    ap.add_argument("--limit", type=int, default=0, help="не больше N съёмок (для проверки)")
    ap.add_argument("--dry-run", action="store_true", help="показать, что будет загружено, ничего не отправляя")
    ap.add_argument("--retries", type=int, default=3)
    ap.add_argument("--timeout", type=int, default=300)
    args = ap.parse_args(argv)

    package = Path(args.package)
    manifest_path = package / "manifest.csv"
    if not manifest_path.exists():
        print(f"ОШИБКА: нет {manifest_path} — сначала выполните knp_export.py")
        return 2
    M = pd.read_csv(manifest_path, encoding="utf-8-sig", dtype=str).fillna("")
    if args.only:
        keep = {kc.web_code(c) for c in args.only}
        M = M[M["code"].isin(keep)]
    if args.limit:
        M = M.head(args.limit)
    if M.empty:
        print("ОШИБКА: под фильтр не подошла ни одна съёмка")
        return 2

    env = _dotenv(kc.REPO / ".env")
    url = args.url or ""
    key = args.key or ""
    if not (url and key):
        try:
            sec = json.loads(Path(args.secret).read_text(encoding="utf-8"))
            url = url or sec.get("API_URL", "")
            key = key or sec.get("API_KEY", "")
        except Exception:  # noqa: BLE001
            pass
    url = url or "http://127.0.0.1:8080/api/upload"
    key = key or env.get("API_KEY", "")
    user = args.web_user or os.getenv("MSWEB_WEB_USER") or env.get("WEB_USER", "")
    password = args.web_password or os.getenv("MSWEB_WEB_PASSWORD") or env.get("WEB_PASSWORD", "")
    if not key:
        print("ОШИБКА: нет API_KEY (--key, secret_uploader.json или .env)")
        return 2

    base = _base_url(url)
    project = args.project or kc.PROJECT
    print(f"Сервер: {base}")
    print(f"Проб в пакете: {len(M)} ({M['code'].nunique()} шифров); проект: {project}")
    if args.dry_run:
        for r in M.itertuples():
            print(f"  {r.code} ({r.date}): {r.formulas} + {r.qc}, формул {r.n_formulas}, quality {r.quality}")
        print(f"  журнал: {package / 'journal.xlsx'}")
        return 0

    session = requests.Session()
    session.headers["X-API-Key"] = key
    auth = (user, password) if (user and password) else None

    # --- журнал --------------------------------------------------------------------------
    if not args.skip_journal:
        jpath = package / "journal.xlsx"
        if not jpath.exists():
            print("ВНИМАНИЕ: нет journal.xlsx — журнал не импортируется")
        else:
            try:
                r, n = _post(session, f"{base}/api/journal/import", retries=args.retries, timeout=args.timeout,
                             files={"file": (jpath.name, jpath.read_bytes(),
                                             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                             auth=auth)
                if r.ok:
                    rep = r.json()
                    print(f"Журнал: создано {rep.get('created')}, обновлено {rep.get('updated')}, "
                          f"проектов {rep.get('projects')}"
                          + (f", ошибок {len(rep['errors'])}" if rep.get("errors") else ""))
                    for e in (rep.get("errors") or [])[:5]:
                        print(f"  ! {e}")
                elif r.status_code == 401:
                    print("ВНИМАНИЕ: журнал не импортирован — сайт требует пароль (--web-password). "
                          "Спектры загрузятся; журнал внесите через «Журнал → Импорт из Excel».")
                else:
                    print(f"ВНИМАНИЕ: журнал не импортирован: {r.status_code} {r.text[:200]}")
            except Exception as e:  # noqa: BLE001
                print(f"ВНИМАНИЕ: журнал не импортирован: {e}")

    # --- спектры -------------------------------------------------------------------------
    log, ok, err = [], 0, 0
    for i, r in enumerate(M.itertuples(), 1):
        fpath, qpath = package / r.formulas, package / r.qc
        if not fpath.exists():
            print(f"  ❌ {r.code} ({r.date}): нет {fpath}")
            log.append({"code": r.code, "date": r.date, "status": "error", "http": "",
                        "n_formulas": 0, "message": f"нет {fpath.name}"})
            err += 1
            continue
        files = {"formulas": (f"{r.code}__{r.date}.csv", fpath.read_bytes(), "text/csv")}
        if qpath.exists():
            files["qc"] = (f"{r.code}__{r.date}.json", qpath.read_bytes(), "application/json")
        data = {"sample": r.code}
        if project:
            data["project"] = project
        try:
            resp, attempts = _post(session, url, retries=args.retries, timeout=args.timeout,
                                   files=files, data=data)
            body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            res = (body.get("results") or [{}])[0]
            status = res.get("status", "error")
            msg = res.get("error") or res.get("quality") or ""
            if resp.ok and status != "error":
                st = {"created": "загружено", "unchanged": "без изменений"}.get(status, status)
                print(f"  ✅ {res.get('sample', r.code)} ({r.date}): {st}, формул {res.get('n_formulas')}")
                ok += 1
            else:
                print(f"  ❌ {r.code} ({r.date}): {resp.status_code} {msg or resp.text[:200]}")
                status, err = "error", err + 1
            log.append({"code": r.code, "date": r.date, "status": status, "http": resp.status_code,
                        "n_formulas": res.get("n_formulas", ""), "message": msg})
        except Exception as e:  # noqa: BLE001
            print(f"  ❌ {r.code} ({r.date}): {e}")
            log.append({"code": r.code, "date": r.date, "status": "error", "http": "",
                        "n_formulas": "", "message": str(e)})
            err += 1
        if i % 10 == 0:
            print(f"  … {i}/{len(M)}")

    pd.DataFrame(log).to_csv(package / "upload_log.csv", index=False, encoding="utf-8-sig")
    print(f"\nГотово: успешно {ok}, ошибок {err}; журнал загрузки — {package / 'upload_log.csv'}")

    # --- проверка итогов ----------------------------------------------------------------
    try:
        h = requests.get(f"{base}/api/health", timeout=30)
        if h.ok:
            d = h.json()
            print(f"На сервере: проб {d.get('samples')}, загрузок {d.get('spectra')}, "
                  f"формул {d.get('formulas')}")
    except Exception:  # noqa: BLE001
        pass
    return 1 if err else 0


if __name__ == "__main__":
    sys.exit(main())
