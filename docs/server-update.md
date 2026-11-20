# Обновление сервера MassSpectrumWeb

Памятка для боевого сервера `mass-spectrim-webinterface.ru` (80.66.65.119).
Сервер — Debian/Ubuntu, root, всё в `/root`. Актуально на 20.11.2026.

## Где что лежит

| Что | Путь / имя |
| --- | --- |
| Приложение | `/root/MassSpectrumWeb` (git, ветка `main`) |
| HumSpectra (нужен только `mass_spectra/pipeline/`) | `/root/HumSpectra` (git, ветка `main`) |
| Секреты | `/root/MassSpectrumWeb/.env` (`API_KEY`, `WEB_USER`, `WEB_PASSWORD`, `PORT`) |
| База и рабочие файлы | `/root/MassSpectrumWeb/data` (bind-mount в контейнер как `/data`) |
| Контейнер | `MassSpectrumWeb`, образ `massspectrumweb-msweb` |
| Nginx (хост) | порт 80/443 → `127.0.0.1:8080`, TLS от certbot |
| Приложение напрямую | `http://127.0.0.1:8080`, снаружи `https://mass-spectrim-webinterface.ru` |

Проверка версии и состояния:

```bash
cd /root/MassSpectrumWeb
git rev-parse --short HEAD
docker compose ps
curl -s http://127.0.0.1:8080/api/health
```

В `/api/health` должно быть `"status": "ok"` и `"humspectra_pipeline": "/opt/humspectra/pipeline"`.

## Обновление (обычный случай)

```bash
# 1. Бэкап БД (файл появится в data/, затем копируем из тома на хост)
cd /root/MassSpectrumWeb
docker exec MassSpectrumWeb python -c "import sqlite3; s=sqlite3.connect('/data/msweb.sqlite'); d=sqlite3.connect('/data/msweb.backup.sqlite'); s.backup(d); d.close(); s.close()"
cp data/msweb.backup.sqlite ~/msweb-backup-$(date +%F_%H%M).sqlite
rm -f data/msweb.backup.sqlite

# 2. Пометить текущий образ, чтобы был откат
docker tag massspectrumweb-msweb massspectrumweb-msweb:prev-$(date +%F)

# 3. Обновить код
git fetch origin
git pull --ff-only
git rev-parse --short HEAD          # сравнить с origin/main

# 4. Обновить HumSpectra, если менялся конвейер (дескрипторы/статистика)
cd /root/HumSpectra
git pull --ff-only
cd /root/MassSpectrumWeb

# 5. Пересобрать и перезапустить
docker compose up -d --build --remove-orphans

# 6. Проверить
docker compose ps
docker compose logs --tail=50 msweb
curl -s http://127.0.0.1:8080/api/health
```

Если менялись только файлы `scripts/` (выгрузка КНП), пересборка не обязательна — эти скрипты
работают с рабочего компьютера. Но пересборка не вредит и занимает ~3 минуты.

После обновления браузер может показать старую страницу — обновите с `Ctrl+F5`.

## Если обновляется только HumSpectra

```bash
cd /root/HumSpectra && git pull --ff-only
cd /root/MassSpectrumWeb && docker compose up -d --build
```

Pipeline копируется в образ на этапе сборки (`COPY --from=humspectra …`), поэтому простой
`docker compose restart` новые дескрипторы **не** применит. Старые загрузки в БД остаются
с прежними дескрипторами; чтобы пересчитать, нужно заново загрузить CSV формул (повторная
загрузка того же файла ничего не дублирует — см. ниже).

## Если HumSpectra ещё не клонирована

```bash
cd /root
git clone --depth 1 https://github.com/Eickland/HumSpectra.git HumSpectra
cd MassSpectrumWeb && docker compose up -d --build
```

Альтернатива без клона (нужна при каждой сборке):

```bash
HUMSPECTRA_CONTEXT='https://github.com/Eickland/HumSpectra.git#main' docker compose up -d --build
```

## Откат

```bash
cd /root/MassSpectrumWeb
git log --oneline -5
git checkout <нужный_коммит>
docker compose up -d --build
```

Вернуть БД из бэкапа — см. раздел «База данных → Восстановление».

Вернуться на предыдущий образ, если он был помечен:

```bash
docker compose down
docker tag massspectrumweb-msweb:prev-<дата> massspectrumweb-msweb
docker compose up -d
```

## База данных

Живая копия одна: `/root/MassSpectrumWeb/data/msweb.sqlite` (в контейнере — `/data/msweb.sqlite`).
SQLite работает в режиме WAL, поэтому рядом лежат `msweb.sqlite-wal` и `msweb.sqlite-shm` — это часть
базы. Копировать файлы обычным `cp` при запущенном контейнере нельзя (получится битый или устаревший
слепок); для «горячего» бэкапа используйте SQLite backup API — команды ниже.

### Проверка

```bash
cd /root/MassSpectrumWeb
docker compose ps
curl -s http://127.0.0.1:8080/api/health
ls -lh data/msweb.sqlite*

docker exec -i MassSpectrumWeb python - <<'PY'
import sqlite3
con = sqlite3.connect('/data/msweb.sqlite')
q = lambda s: con.execute(s).fetchall()
print('integrity:', q('PRAGMA integrity_check')[0][0])          # ok
print('journal_mode:', q('PRAGMA journal_mode')[0][0])          # wal
for t in ('projects', 'samples', 'spectra', 'formulas'):
    print(t, q(f'select count(*) from {t}')[0][0])
pages, size = q('PRAGMA page_count')[0][0], q('PRAGMA page_size')[0][0]
print('размер, МБ:', round(pages * size / 1048576, 1))
print('последняя загрузка:', q('select max(uploaded_at) from spectra')[0][0])
print('несколько загрузок у пробы:', q('select s.code, count(*) c from samples s '
                                       'join spectra sp on sp.sample_id = s.id '
                                       'group by s.id having c > 1'))
con.close()
PY
```

`integrity_check` должен вернуть `ok`. Остальные цифры сверяйте с ожидаемыми: после полной загрузки
КНП — 165 проб, 80 загрузок, 163 418 формул; несколько загрузок — только у BC6-9, BC1-2, K2-3, K4-1, K4-12.

### Бэкап

Горячий бэкап (контейнер работает, база консистентна):

```bash
cd /root/MassSpectrumWeb
docker exec MassSpectrumWeb python -c "import sqlite3; s=sqlite3.connect('/data/msweb.sqlite'); d=sqlite3.connect('/data/msweb.backup.sqlite'); s.backup(d); d.close(); s.close()"
cp data/msweb.backup.sqlite ~/msweb-backup-$(date +%F_%H%M).sqlite
rm -f data/msweb.backup.sqlite
ls -lh ~/msweb-backup-*.sqlite
```

Если на хосте установлен `sqlite3`, то же самое одной командой:

```bash
sqlite3 data/msweb.sqlite ".backup '/root/msweb-backup-$(date +%F_%H%M).sqlite'"
```

Холодный бэкап (контейнер остановлен) — тогда можно копировать файлы как есть, вместе с WAL:

```bash
TS=$(date +%F_%H%M)
docker compose stop msweb
cp data/msweb.sqlite ~/msweb-backup-$TS.sqlite
[ -f data/msweb.sqlite-wal ] && cp data/msweb.sqlite-wal ~/msweb-backup-$TS.sqlite-wal
docker compose start msweb
```

Бэкапы держите вне `data/`: она смонтирована в контейнер и легко затирается при пересоздании.

### Восстановление

```bash
cd /root/MassSpectrumWeb
docker compose stop msweb
cp ~/msweb-backup-<дата_время>.sqlite data/msweb.sqlite
rm -f data/msweb.sqlite-wal data/msweb.sqlite-shm        # старый WAL несовместим с новым файлом
docker compose start msweb
curl -s http://127.0.0.1:8080/api/health
```

Если бэкап делался «холодным» и с `-wal`, положите рядом и его — SQLite подхватит при старте.

### Удаление

Отдельные пробы и загрузки лучше удалять через интерфейс или API — там каскадное удаление
формул и записей истории уже настроено:

```bash
# удалить пробу целиком (вместе с её загрузками и формулами)
curl -u lab:<WEB_PASSWORD> -X DELETE https://mass-spectrim-webinterface.ru/api/samples/BC1-2

# удалить одну (лишнюю) загрузку, не трогая пробу
curl -u lab:<WEB_PASSWORD> -X DELETE https://mass-spectrim-webinterface.ru/api/spectra/123
```

Массовое удаление SQL-запросом — только после бэкапа и с включёнными внешними ключами,
иначе останутся «сироты» в `formulas`:

```bash
docker exec -i MassSpectrumWeb python - <<'PY'
import sqlite3
con = sqlite3.connect('/data/msweb.sqlite')
con.execute('PRAGMA foreign_keys=ON')
codes = ['BC1-2', 'K4-12']                       # список шифров
con.executemany('delete from samples where code = ?', [(c,) for c in codes])
con.commit()
print('затронуто строк:', con.total_changes)
print('осталось проб:', con.execute('select count(*) from samples').fetchone()[0])
con.close()
PY
```

Полностью удалить базу (со схемой и всеми данными):

```bash
cd /root/MassSpectrumWeb
docker compose stop msweb
DIR=~/msweb-old-$(date +%F_%H%M)
mkdir -p "$DIR"
for f in msweb.sqlite msweb.sqlite-wal msweb.sqlite-shm; do
  [ -e "data/$f" ] && mv "data/$f" "$DIR/"
done
docker compose start msweb
```

Файлы не удаляем, а уносим в `~` — если что, базу можно вернуть.

### Пересоздание с нуля

Схему приложение создаёт само при старте (`CREATE TABLE IF NOT EXISTS`). Если таблица `samples`
пуста, при первом запуске автоматически импортируется `data/lab_journal.xlsx` (72 старые пробы).
Порядок полного пересоздания:

```bash
cd /root/MassSpectrumWeb
docker compose stop msweb

# 1. старую базу — в сторону (не rm)
DIR=~/msweb-old-$(date +%F_%H%M)
mkdir -p "$DIR"
for f in msweb.sqlite msweb.sqlite-wal msweb.sqlite-shm; do
  [ -e "data/$f" ] && mv "data/$f" "$DIR/"
done

# 2. если нужна СОВСЕМ пустая база — временно убрать затравочный журнал
# mv data/lab_journal.xlsx ~/lab_journal.xlsx.bak

# 3. поднять — схема создастся сама
docker compose up -d
curl -s http://127.0.0.1:8080/api/health
```

Если `lab_journal.xlsx` убирали, верните его на место (`mv ~/lab_journal.xlsx.bak data/lab_journal.xlsx`):
автоматически он больше не импортируется — журнал при необходимости загрузите через
«Журнал → Импорт из Excel».

Дальше данные загружаются заново с рабочего компьютера: сначала `knp_export.py`, затем
`knp_upload.py` (журнал КНП импортируется из `export/journal.xlsx`, повторная загрузка спектров
безопасна). Файлы `data/knp_2026/` и `.env` пересоздание БД не затрагивает.

## Nginx и сертификат

Конфиги: `/etc/nginx/sites-enabled/`, бэкап перед правкой:

```bash
cp -a /etc/nginx /root/nginx-backup-$(date +%F)
nginx -T | grep -nE 'server_name|listen|proxy_pass|client_max_body_size'
nginx -t && systemctl reload nginx
```

В server-блоке должны быть:

```nginx
client_max_body_size 25m;      # CSV формул бывают по ~800 КБ
proxy_read_timeout 300s;       # долгая загрузка/импорт
```

Сертификат Let's Encrypt (certbot + python3-certbot-nginx):

```bash
certbot certificates
certbot renew --dry-run
systemctl list-timers | grep certbot
```

Проверка снаружи (с рабочего компьютера, Python — потому что `curl.exe`/PowerShell на Windows
иногда падают на TLS с `SEC_E_NO_CREDENTIALS`, это проблема клиента, а не сервера):

```powershell
python -c "import requests; print(requests.get('https://mass-spectrim-webinterface.ru/api/health', timeout=15).text)"
```

## Загрузка новых данных (с рабочего компьютера)

```powershell
cd C:\Users\Kirill\Desktop\Lab\MassSpectrumWeb
python scripts\knp_export.py --raw E:/ --out data/knp_2026/export --overwrite
python scripts\knp_upload.py --url https://mass-spectrim-webinterface.ru/api/upload `
  --key <API_KEY с сервера> --web-password <WEB_PASSWORD с сервера>
```

Ключ и пароль — из `/root/MassSpectrumWeb/.env`:

```bash
grep -E '^(API_KEY|WEB_USER|WEB_PASSWORD)=' /root/MassSpectrumWeb/.env
```

Повторный запуск безопасен: сервер сравнивает sha256 CSV формул со всеми прошлыми загрузками
пробы, одинаковый файл даёт «без изменений», новая запись в истории не создаётся. Новая версия
появляется только при другом CSV (другая съёмка или переобработка).

## Частые ошибки

| Симптом | Причина и решение |
| --- | --- |
| `failed to get build context humspectra: … no such file or directory` | нет `/root/HumSpectra` — клонировать (см. выше) или задать `HUMSPECTRA_CONTEXT` |
| `Conflict. The container name "/MassSpectrumWeb" is already in use` | старый контейнер: `docker rm -f MassSpectrumWeb`, затем `docker compose up -d --build --remove-orphans` |
| `Found orphan containers` | `docker compose up -d --remove-orphans` |
| Загрузка: `401 Unauthorized` | не совпал `X-API-Key` (`--key`) с серверным `API_KEY`; для журнала — неверный `WEB_PASSWORD` |
| Загрузка: `Connection refused` на 443 | не запущен nginx/сертификат: `nginx -t`, `ss -ltnp 'sport = :443'`, `ufw status` |
| `https` отвечает 301 на `http` | так настроен certbot (`--redirect`), это нормально |
| Windows `curl.exe`: `schannel: SEC_E_NO_CREDENTIALS` | клиентская проблема TLS в Windows; использовать Python/`requests` или браузер |
| Повторная загрузка создала ещё одну версию | CSV отличается (пересобран другим конвейером или изменились исходники); проверьте `sha256sum` файла |
| Пробы вида `B-6-9_000001` в реестре | загрузка шла не скриптом, а zip/браузером (имя файла вместо шифра); удалить такие пробы в интерфейсе |
| `database is locked` | параллельная запись или зависший процесс: `docker compose restart msweb`; не запускать второй контейнер на ту же БД |
| `database disk image is malformed` | базу скопировали на горячую обычным `cp` — восстановить из бэкапа (раздел «База данных») |

## Чего не делать

- `git add -A` / `git commit -a` на сервере — в репозиторий попадут PNG и рабочие файлы из `data/`.
- `docker compose down -v` и `docker system prune -a` — можно потерять тома/образы для отката.
- `git reset --hard` без бэкапа БД — единственная копия рабочей базы лежит в `data/msweb.sqlite`.
- `docker compose restart` после обновления HumSpectra — нужна пересборка образа.
- Копировать `msweb.sqlite` при работающем контейнере обычным `cp` — из-за WAL получится несогласованный слепок.
- Удалять `msweb.sqlite-wal` / `-shm` у работающей базы или делать массовый `DELETE` без `PRAGMA foreign_keys=ON`.
- Хранить бэкапы внутри `data/` — папка смонтирована в контейнер и затирается при пересоздании.

## Чек-лист обновления

- [ ] Бэкап БД сделан и скопирован из `data/` на хост
- [ ] `PRAGMA integrity_check` — `ok`
- [ ] Текущий образ помечен (`massspectrumweb-msweb:prev-<дата>`)
- [ ] `git pull --ff-only` в MassSpectrumWeb и (если нужно) в HumSpectra
- [ ] `docker compose up -d --build --remove-orphans`
- [ ] `docker compose ps` — контейнер `Up (healthy)`
- [ ] `/api/health` — `ok`, путь к pipeline `/opt/humspectra/pipeline`
- [ ] Сайт открывается по HTTPS, вход по паролю работает
- [ ] Новые данные загружены, в реестре ожидаемое число проб и формул
