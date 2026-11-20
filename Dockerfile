# MassSpectrumWeb: FastAPI + SQLite, расчёты — функциями HumSpectra.mass_spectra.pipeline
#
# Сборка требует второй контекст «humspectra» — репозиторий HumSpectra (см. docker-compose.yml):
#   docker compose build            # ../HumSpectra рядом с MassSpectrumWeb
# или без compose:
#   docker buildx build --build-context humspectra=../HumSpectra -t msweb .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    DATA_PATH=/data HUMSPECTRA_PIPELINE_DIR=/opt/humspectra/pipeline TZ=Europe/Moscow

WORKDIR /srv
COPY requirements.txt .
RUN pip install -r requirements.txt

# Из HumSpectra нужны только дескрипторы и статистика конвейера (numpy/pandas/scipy);
# остальной пакет (калибровка, pyopenms, графики) работает на рабочем компьютере.
COPY --from=humspectra HumSpectra/mass_spectra/pipeline/ /opt/humspectra/pipeline/

COPY app ./app
RUN mkdir -p /data && python -c "import os; os.environ['DATA_PATH']='/tmp/x'; import app.humspectra as h; print('HumSpectra pipeline:', h.pipeline_dir())"
VOLUME ["/data"]
EXPOSE 8080
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health')" || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*"]
