# MassSpectrumWeb

Веб-интерфейс лаборатории для результатов FT-ICR MS: реестр проб, лабораторный журнал, графики и статистика.

Спектры обрабатываются **на рабочем компьютере** конвейером `HumSpectra.mass_spectra.pipeline`
(`scripts/ftms_pipeline.py`), на сервер загружаются готовые таблицы формул (`formulas/<проба>.csv`) и отчёты
качества (`qc/<проба>.json`). Сервер пересчитывает дескрипторы и статистику **теми же функциями HumSpectra**
(`pipeline/descriptors.py`, `pipeline/statistics.py`), поэтому цифры на сайте совпадают с `summary_descriptors.csv`
и `statistics.csv` конвейера.

```
рабочий компьютер                                   сервер (Docker)
.d → ftms_pipeline.py → formulas/*.csv, qc/*.json ──upload_results.py──▶ /api/upload → БД (SQLite)
                                                                          │
                     браузер ◀── реестр проб, журнал, графики, статистика ┘
```

## Страницы

| Страница | Что там |
| --- | --- |
| **Пробы** (`/samples`) | реестр: шифр, проект, группа, дата отбора, дата загрузки, число формул, качество, RMS ошибки; поиск, фильтры, сортировка; выбор проб → сравнение |
| Проба (`/samples/<шифр>`) | метаданные журнала, QC спектра, ключевые дескрипторы; графики: Ван Кревелен (класс / Ласаковиц / Перминова / Kellerman / NOSC / интенсивность), реконструированный масс-спектр, классы CHO/CHON/CHOS/CHONS, классы Перминовой и Kellerman, квадраты D01–D20, DBE–C, дефект массы Кендрика, ошибка m/z; все дескрипторы; история загрузок |
| **Проекты** | список проектов со счётчиками; страница проекта — сводка дескрипторов, пробы, выгрузка масс-листов (ZIP: CSV на каждую пробу + общий `all_mass_lists.csv`) |
| **Анализ** | группы по полю «Группа», проекту, regex по шифру или вручную; Манн–Уитни + δ Клиффа + q (БХ) для двух групп, Краскел–Уоллис для трёх и более; распределения (box plot); PCA; общие/специфичные формулы групп и индекс Жаккара; выгрузка CSV |
| **Лаб. журнал** | все метаданные проб, редактирование, добавление, импорт/экспорт Excel |
| **Загрузка** | загрузка через браузер (CSV/JSON или zip папки результатов) и инструкция для скрипта |

API с описанием — `/api/docs`.

## База данных

`projects` → `samples` (метаданные журнала) → `spectra` (загрузки: QC, параметры конвейера, дескрипторы;
`is_current` — актуальная, прежние в истории) → `formulas` (формулы с H/C, O/C, DBE, AI_mod, NOSC, классами).
SQLite в `data/msweb.sqlite`; для PostgreSQL достаточно `DATABASE_URL`.

Проба сопоставляется по шифру: точное совпадение, затем без суффикса прибора (`ADOM-SLB-1_000001` → `ADOM-SLB-1`).
Если пробы нет в журнале, она создаётся автоматически; метаданные дописываются на сайте или через Excel.

## Лабораторный журнал (Excel)

Лист «Пробы»: Шифр пробы*, Проект, Группа, Тип пробы, Место отбора, Дата отбора, Выделение, Дата съёмки, Оператор,
Описание, Примечания. Лист «Проекты»: Проект, Описание, Руководитель. Шаблон и выгрузка — на странице журнала.
Импорт обновляет пробы по шифру и не стирает данные пустыми ячейками; старый формат (Samples: Name, Project,
Description, Notes) тоже читается. Прежний `data/lab_journal.xlsx` импортируется автоматически при первом запуске.

## Развёртывание на сервере

Нужны Docker с compose v2.17+ и оба репозитория рядом:

```bash
git clone https://github.com/Eickland/HumSpectra.git
git clone https://github.com/Eickland/MassSpectrumWeb.git
cd MassSpectrumWeb
cp .env.example .env        # задать API_KEY и WEB_PASSWORD
docker compose up -d --build
```

Из HumSpectra в образ копируется только `HumSpectra/mass_spectra/pipeline/`. Если HumSpectra лежит в другом месте:
`HUMSPECTRA_CONTEXT=/path/to/HumSpectra docker compose build` (можно git-адрес `https://github.com/Eickland/HumSpectra.git#main`).
После обновления HumSpectra — `docker compose up -d --build`.

Для доступа из интернета поставьте перед контейнером HTTPS-прокси (Caddy/nginx), иначе пароль и ключ идут открытым текстом.
Резервная копия — файл `data/msweb.sqlite` (при работающем сервере: `sqlite3 data/msweb.sqlite ".backup backup.sqlite"`).

Пошаговая памятка по обновлению боевого сервера (git pull → пересборка → проверка), откату,
HTTPS и типовым ошибкам — [docs/server-update.md](docs/server-update.md).

## Загрузка с рабочего компьютера

```bash
python scripts/ftms_pipeline.py D:/lab/raw D:/lab/final_spectra --blank … --group Baikal=SLB --group "Solzan=SL\d"
python scripts/upload_results.py D:/lab/final_spectra --project "Байкал-Солзан"
```

`upload_results.py` лежит в HumSpectra/scripts; адрес и ключ — в `secret_uploader.json`
(`{"API_URL": "https://сервер/api/upload", "API_KEY": "…"}`).

## Серия «КНП 2026» (Байкал, 2026)

Исходные папки .d — на диске `E:` (`E:\2026_08_19` … `E:\2026_10_22`, 8 дат съёмки).
Результаты прежнего прогона и сверка с журналом скопированы в `data/knp_2026/`
(`source_results/`, `inventory/`), чтобы пакет можно было собрать без старого компьютера.

```bash
# 1. пакет для сайта: formulas/<шифр>__<дата>.csv + qc/*.json + journal.xlsx + manifest.csv
python scripts/knp_export.py --raw E:/ --out data/knp_2026/export --overwrite

# 2. импорт журнала и загрузка спектров
python scripts/knp_upload.py --url https://сервер/api/upload --key … --web-password …
```

Шифры на сайте — журнальные, латиницей: `ВС1-2` → **BC1-2**, `К4-12` → **K4-12**.
80 съёмок ложатся на 75 проб: повторные съёмки BC6-9, BC1-2, K2-3, K4-1 и K4-12
остаются в истории пробы, актуальной становится последняя по дате (её и берёт статистика).
18 папок .d вне журнала (OSL/O5-SL, сентябрь–октябрь 2026) перечислены в
`export/raw_not_in_journal.csv` — их можно обработать конвейером отдельно.

Импорт журнала требует пароля сайта (HTTP Basic), загрузка спектров — только `X-API-Key`
из `secret_uploader.json`. Без пароля запускайте с `--skip-journal`: спектры загрузятся,
а `export/journal.xlsx` можно внести позже через «Журнал → Импорт из Excel».

После переобработки .d (`results/runs/<дата>/formulas|qc`) пакет собирается из свежих
результатов: `python scripts/knp_export.py --runs <results> --raw E:/`.

## Локальный запуск и тесты

```bash
pip install -r requirements.txt pytest httpx
DATA_PATH=./data uvicorn app.main:app --reload --port 8080   # HumSpectra ищется в ../HumSpectra
pytest tests
```
