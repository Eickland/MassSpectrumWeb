"""
Мост к HumSpectra.mass_spectra.pipeline.

Сервер считает дескрипторы и статистику тем же кодом, что и конвейер на рабочем компьютере:
descriptors.py (formula_metrics, sample_descriptors) и statistics.py (compare_groups, benjamini_hochberg, cliffs_delta).
Модули загружаются по пути к файлу, минуя __init__ пакета: тот тянет калибровку, pyopenms, matplotlib и
statsmodels, которые на сервере не нужны (спектры обрабатываются на рабочем компьютере).

Где искать подпакет (первое найденное):
  1. HUMSPECTRA_PIPELINE_DIR — папка pipeline (в Docker-образе — /opt/humspectra/pipeline);
  2. ../HumSpectra/HumSpectra/mass_spectra/pipeline рядом с репозиторием MassSpectrumWeb (локальный запуск).
"""
import importlib.util
import sys
from pathlib import Path

from . import config

_REPO = Path(__file__).resolve().parents[1]
_CANDIDATES = [p for p in (config.HUMSPECTRA_PIPELINE_DIR,) if p] + [
    "/opt/humspectra/pipeline",
    str(_REPO.parent / "HumSpectra" / "HumSpectra" / "mass_spectra" / "pipeline"),
]


def pipeline_dir() -> Path:
    for c in _CANDIDATES:
        p = Path(c)
        if (p / "descriptors.py").exists() and (p / "statistics.py").exists():
            return p
    raise RuntimeError("Не найден HumSpectra/mass_spectra/pipeline (descriptors.py, statistics.py). "
                       "Укажите HUMSPECTRA_PIPELINE_DIR. Искали: " + "; ".join(_CANDIDATES))


def _load(name: str):
    mod_name = f"humspectra_pipeline_{name}"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(mod_name, pipeline_dir() / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


descriptors = _load("descriptors")
statistics = _load("statistics")

formula_metrics = descriptors.formula_metrics
sample_descriptors = descriptors.sample_descriptors
LASZAKOVITS = descriptors.LASZAKOVITS
HC_BINS, OC_BINS, STANDARD_SQUARES = descriptors.HC_BINS, descriptors.OC_BINS, descriptors.STANDARD_SQUARES
compare_groups = statistics.compare_groups
benjamini_hochberg = statistics.benjamini_hochberg
cliffs_delta = statistics.cliffs_delta
