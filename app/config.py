"""Настройки из переменных окружения (см. .env.example)."""
import os
from pathlib import Path

DATA_PATH = Path(os.getenv("DATA_PATH", Path(__file__).resolve().parents[1] / "data"))
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DATA_PATH / 'msweb.sqlite'}")
# Ключ для загрузки результатов скриптом (заголовок X-API-Key). Пустой — загрузка по API закрыта.
API_KEY = os.getenv("API_KEY", "")
# Логин/пароль на весь интерфейс (HTTP Basic). Пустой пароль — интерфейс открыт (только для локальной сети!).
WEB_USER = os.getenv("WEB_USER", "lab")
WEB_PASSWORD = os.getenv("WEB_PASSWORD", "")
# Папка подпакета HumSpectra.mass_spectra.pipeline (descriptors.py, statistics.py)
HUMSPECTRA_PIPELINE_DIR = os.getenv("HUMSPECTRA_PIPELINE_DIR", "")
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "200"))
