# Деплой price.interalex.pro (сервер IAPRO, 91.98.11.27)

- Код: `/srv/price/app` (владелец root, сайт только читает), venv `/srv/price/venv`, Python 3.12 из `/opt/uv-python`.
- Данные: `/srv/price/data` (владелец `price`): SQLite, `secret_key`, `allowed.json`, `auth_events.jsonl`.
- Секреты: `/root/iapro/price-site.env` (вводит Alex скриптом `/root/iapro/set-price-secrets.sh`), systemd читает его как root.
- Сервисы: `price-web` (gunicorn 127.0.0.1:8020, MemoryMax 600M), `price-bot` (MemoryMax 250M).
- Список доступа: cron root `*/2` → `deploy/price_access_sync.py` → `allowed.json`; лог `/root/iapro/logs/price-access-sync.log`.
- nginx: `/etc/nginx/sites-available/price.interalex.pro` проксирует на 8020, `/static/` из `/srv/price/static`.

Обновление кода:
```
rsync -az --delete --exclude data --exclude .git --exclude __pycache__ ./ root@91.98.11.27:/srv/price/app/
ssh root@91.98.11.27 'cd /srv/price/app && /srv/price/venv/bin/pip install -q -r requirements.txt && sudo -u price env PRICE_DATA_DIR=/srv/price/data PRICE_STATIC_ROOT=/srv/price/static /srv/price/venv/bin/python manage.py migrate && PRICE_DATA_DIR=/srv/price/data PRICE_STATIC_ROOT=/srv/price/static /srv/price/venv/bin/python manage.py collectstatic --noinput && systemctl restart price-web price-bot'
```
