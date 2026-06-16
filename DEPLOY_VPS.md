# Деплой на VPS (Ubuntu 26.04, 2 ГБ RAM, 1 ядро) — надёжный вариант

Пошаговая инструкция: GitHub → VPS, с автозапуском (systemd) и доступом через браузер (nginx).
Код уже лежит на GitHub (`github.com/art6765/copper-forecast`, публичный) и актуален — с компьютера ничего копировать не нужно.

Все команды выполняются **в терминале сервера**, по порядку. Каждый блок можно копировать целиком.
Инструкция написана для пользователя **root** (типично для свежего VPS). Если заходишь не под root — добавляй `sudo` перед командами.

Примерное время: ~15 минут (основное — установка библиотек на 1 ядре).

---

## Шаг 0. Подключиться к серверу

С твоего компьютера (Terminal на Mac):

```bash
ssh root@IP_АДРЕС_СЕРВЕРА
```

`IP_АДРЕС_СЕРВЕРА` — адрес из панели хостинга. При первом входе спросит про fingerprint — ответить `yes`.

---

## Шаг 1. Подготовка системы + swap (страховка памяти для 2 ГБ)

```bash
apt update && apt upgrade -y
apt install -y git curl nginx

# Файл подкачки 2 ГБ — страховка от нехватки RAM при установке и обучении моделей.
# Если swap уже есть (проверка: команда `swapon --show` что-то выводит) — этот блок пропусти.
fallocate -l 2G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
```

Проверка, что swap включился:

```bash
free -h
```

В строке `Swap:` должно быть `2.0Gi`.

---

## Шаг 2. Установить uv (он сам поставит правильный Python 3.12)

> Зачем uv: в Ubuntu 26.04 системный Python слишком новый для зафиксированных в проекте версий
> `numpy`/`pandas` (готовых сборок под него нет — установка падала бы или долго компилировала).
> `uv` ставит изолированный Python 3.12, под который все библиотеки есть в готовом виде. Плюс он
> ставит зависимости в разы быстрее обычного pip — это важно на 1 ядре.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env
```

Проверка:

```bash
uv --version
```

Должна показаться версия (например `uv 0.x.x`).

---

## Шаг 3. Скачать проект с GitHub

```bash
cd /opt
git clone https://github.com/art6765/copper-forecast.git
cd copper-forecast
```

---

## Шаг 4. Создать окружение Python 3.12 и поставить библиотеки

```bash
uv venv --python 3.12
uv pip install -r requirements.txt
```

Первый запуск скачает Python 3.12 и все библиотеки (pandas, xgboost, streamlit и т.д.). На 1 ядре это
займёт несколько минут — это нормально.

---

## Шаг 5. Разовая проверка, что приложение запускается

```bash
.venv/bin/streamlit run app.py --server.port 8501 --server.address 0.0.0.0
```

Открой в браузере `http://IP_АДРЕС_СЕРВЕРА:8501`. Если дашборд открылся — всё работает.
Первый заход может «думать» 1–2 минуты (модели обучаются с нуля), дальше — быстро.

Останови проверку: нажми **Ctrl+C** в терминале. Дальше настроим автозапуск, чтобы не запускать руками.

> Если порт 8501 не открывается — скорее всего его блокирует сетевой экран. См. Шаг 8.

---

## Шаг 6. Автозапуск через systemd (чтобы работало постоянно)

Создаём сервис — скопируй блок целиком (он сам запишет файл):

```bash
cat > /etc/systemd/system/copper.service <<'EOF'
[Unit]
Description=Copper Forecast (Streamlit)
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/copper-forecast
ExecStart=/opt/copper-forecast/.venv/bin/streamlit run app.py \
  --server.port 8501 \
  --server.address 127.0.0.1 \
  --server.headless true \
  --server.enableCORS false \
  --server.enableXsrfProtection false
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
```

> Адрес `127.0.0.1` — приложение слушает только локально, наружу его отдаёт nginx (Шаг 7).
> Флаги `enableCORS/enableXsrfProtection false` нужны для корректной работы Streamlit за nginx.

Включаем и запускаем:

```bash
systemctl daemon-reload
systemctl enable --now copper
systemctl status copper --no-pager
```

В статусе должно быть зелёное `active (running)`. Сервис теперь сам поднимется после перезагрузки сервера и перезапустится, если упадёт.

---

## Шаг 7. nginx — доступ по обычному адресу (порт 80)

```bash
cat > /etc/nginx/sites-available/copper <<'EOF'
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:8501;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket — обязательно для Streamlit, иначе бесконечная загрузка
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400;
    }
}
EOF
```

Включаем конфиг и убираем стандартную заглушку nginx:

```bash
ln -sf /etc/nginx/sites-available/copper /etc/nginx/sites-enabled/copper
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl restart nginx
```

`nginx -t` должен сказать `syntax is ok` / `test is successful`.
Теперь приложение открывается просто по `http://IP_АДРЕС_СЕРВЕРА` (без `:8501`).

---

## Шаг 8. Сетевой экран (если порт не открывается)

У многих хостеров firewall настраивается **в веб-панели** — проверь, что там открыты порты **80** и **443**.

Если на самом сервере включён `ufw`, открой порты (важно: сначала SSH, иначе можно потерять доступ):

```bash
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
```

---

## Шаг 9 (опционально). Свой домен + HTTPS

Если есть домен — в панели регистратора домена создай **A-запись**, указывающую на IP сервера.
Дождись, пока домен начнёт открывать сайт по `http://`, затем:

```bash
# Вписать домен в конфиг nginx вместо "_"
sed -i 's/server_name _;/server_name ТВОЙ-ДОМЕН.РУ;/' /etc/nginx/sites-available/copper
nginx -t && systemctl restart nginx

# Выпустить бесплатный SSL-сертификат
apt install -y certbot python3-certbot-nginx
certbot --nginx -d ТВОЙ-ДОМЕН.РУ
```

Certbot сам настроит HTTPS и автопродление. После этого сайт работает по `https://ТВОЙ-ДОМЕН.РУ`.

---

## Обновление приложения в будущем

Когда внесёшь изменения в код и запушишь в GitHub — на сервере достаточно:

```bash
cd /opt/copper-forecast
git pull
uv pip install -r requirements.txt   # только если менялись библиотеки
systemctl restart copper
```

---

## Полезные команды

```bash
systemctl status copper --no-pager   # статус приложения
journalctl -u copper -n 50 --no-pager # последние 50 строк логов (если что-то не так)
systemctl restart copper             # перезапустить приложение
systemctl restart nginx              # перезапустить nginx
```

---

## Важно про безопасность

Приложение **открыто без пароля** — любой, кто знает адрес, увидит дашборд. Персональных данных в проекте
нет (только публичные котировки и новости), но если доступ нужно ограничить — самый простой способ
добавить логин/пароль через nginx (basic auth). Скажи — добавлю отдельный блок.
