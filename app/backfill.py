"""
Пересчёт дескрипторов уже загруженных спектров.

Нужен, когда в расчёт добавляются новые показатели (например, классы Перминовой и Kellerman):
старые загрузки в БД хранят готовый JSON дескрипторов, и без пересчёта новые колонки
не появятся ни на странице пробы, ни в анализе. Формулы при этом не меняются — дескрипторы
считаются заново из сохранённых C, H, O, N, S, интенсивности и m/z.

Запускается автоматически при старте, если у какой-то загрузки нет новых ключей,
и вручную:

    docker exec MassSpectrumWeb python -m app.backfill
"""
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import classes as cl
from . import humspectra as hs
from .analysis import formulas_df
from .db import SessionLocal
from .ingest import _clean_json
from .models import Spectrum

#: признак, что дескрипторы посчитаны с классами Перминовой
MARKER = "perm_undefinded"


def needs_backfill(db: Session) -> bool:
    for (desc,) in db.execute(select(Spectrum.descriptors)):
        if not desc or MARKER not in desc:
            return True
    return False


def recompute_descriptors(db: Session) -> int:
    """Пересчитывает descriptors у всех загрузок; возвращает число обновлённых спектров."""
    n = 0
    for sp in db.scalars(select(Spectrum)).all():
        F = formulas_df(db, sp.id)
        if F.empty:
            continue
        F = cl.add_formula_classes(hs.formula_metrics(F))
        desc = _clean_json(hs.sample_descriptors(F))
        desc.update(_clean_json(cl.descriptor_fractions(F)))
        sp.descriptors = desc
        n += 1
    db.commit()
    return n


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    with SessionLocal() as db:
        n = recompute_descriptors(db)
    print(f"Дескрипторы пересчитаны: {n} спектров")


if __name__ == "__main__":
    main()
