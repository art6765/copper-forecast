# Deploy — выложить систему в интернет

Этот документ — пошаговая инструкция для деплоя дашборда в публичный интернет, чтобы любой человек мог зайти по ссылке и работать с системой.

## Рекомендуемый путь — Streamlit Community Cloud

**Почему:**
- Бесплатно, официальная платформа от создателей Streamlit.
- Один публичный app на бесплатном тарифе (для второго — попросить инвайт).
- Поддерживает все наши библиотеки (xgboost, statsmodels, plotly).
- Автодеплой при пуше в GitHub: коммит → через 2 минуты ссылка обновилась.
- 1 ГБ RAM — для нашей системы хватает.

**Что потребуется** (бесплатно, 5 минут регистрации каждое):
1. Аккаунт GitHub — https://github.com/signup
2. Аккаунт Streamlit Cloud — https://share.streamlit.io (войти через GitHub)

---

## Шаг 1. Создать репозиторий на GitHub

1. Зайти на https://github.com/new
2. Repository name: `copper-forecast` (или любое другое латинскими буквами)
3. **Public** — обязательно для бесплатного тарифа Streamlit Cloud
4. **Не** добавляйте README/`.gitignore`/license — они уже есть в проекте
5. Нажать **Create repository**
6. Скопировать URL, например: `https://github.com/ВАШ-ЛОГИН/copper-forecast.git`

## Шаг 2. Запушить локальный проект в GitHub

В терминале из папки проекта:

```bash
cd "/Users/arturhismatullin/Documents/Claude/Projects/Покупка меди/copper_forecast_mvp"

# Если git ещё не инициализирован
git init
git add .
git commit -m "Initial commit: Copper Forecast MVP"

# Подключаем удалённый репозиторий (подставьте свой URL)
git branch -M main
git remote add origin https://github.com/ВАШ-ЛОГИН/copper-forecast.git
git push -u origin main
```

При первом пуше GitHub попросит залогиниться — лучше через **personal access token**:
- https://github.com/settings/tokens/new
- Поставить галочку `repo`
- Сгенерировать и использовать вместо пароля.

## Шаг 3. Деплой в Streamlit Cloud

1. Зайти на https://share.streamlit.io и войти через GitHub.
2. Нажать **New app** (правый верхний угол).
3. Заполнить форму:
   - **Repository:** `ВАШ-ЛОГИН/copper-forecast`
   - **Branch:** `main`
   - **Main file path:** `app.py`
   - **App URL** (внизу): `copper-forecast` → получится `https://copper-forecast.streamlit.app`
4. (Опционально) **Advanced settings → Secrets** — если у вас есть FRED API key:
   ```toml
   FRED_API_KEY = "ваш_ключ_сюда"
   ```
5. Нажать **Deploy!**

**Первый деплой займёт 3-5 минут** — установка xgboost, scikit-learn, pandas.

После завершения автоматически откроется приложение по ссылке вида:
```
https://copper-forecast.streamlit.app
```

Этой ссылкой можно делиться с заказчиком.

---

## Альтернатива — Hugging Face Spaces

Если не хочется заводить GitHub:

1. Зайти на https://huggingface.co/spaces (бесплатная регистрация).
2. **Create new Space**.
3. **SDK: Streamlit**, **Hardware: free CPU basic**.
4. Загрузить через web (или `git push huggingface_url`):
   - все `.py` файлы
   - `requirements.txt`
   - `.streamlit/config.toml`
5. Через 2-3 минуты — доступно по `https://huggingface.co/spaces/ВАШ-ЛОГИН/copper-forecast`.

Преимущества: проще без отдельного GitHub.
Недостатки: меньше документации на русском, медленнее сборка.

---

## Альтернатива — VPS (если нужен полный контроль)

Покупка любого VPS от 200 ₽/мес (Timeweb, Reg.ru, Selectel):

```bash
# На сервере (Ubuntu 22.04)
sudo apt update && sudo apt install python3-pip git nginx -y
git clone https://github.com/ВАШ-ЛОГИН/copper-forecast.git
cd copper-forecast
pip3 install -r requirements.txt

# Запуск в фоне
nohup streamlit run app.py --server.port 8501 --server.address 0.0.0.0 > app.log 2>&1 &

# Настроить nginx как reverse proxy на ваш домен (опционально)
```

Минусы: ручное обновление при изменениях кода, поднимать SSL самостоятельно.
Плюсы: можно подключить свой домен, полная приватность.

---

## Что нужно знать перед деплоем

### Лимиты Streamlit Community Cloud

| Параметр | Лимит |
|---|---|
| RAM | 1 ГБ |
| Disk | ~50 МБ кэша (data/cache_*.csv в .gitignore — не пушим) |
| CPU | ~1 vCPU, разделяемый |
| Время бездействия | 7 дней без посетителей → app засыпает (просыпается за 30 сек) |
| Лимит публичных app | 1 на бесплатном тарифе |

### Что НЕ попадёт в публичный repo

В `.gitignore` уже исключены:
- `data/cache_*.csv` — кэши источников (создадутся заново)
- `outputs/*` — результаты прогноза (генерируются на лету)
- `.streamlit/secrets.toml` — секреты (задаются через UI Cloud)
- `presentation/node_modules/` — npm-зависимости презентации

### Производительность в Cloud

- **Первый посетитель** ждёт ~1-2 минуты — модели обучаются с нуля.
- **Последующие** получают кэшированный результат за 1-3 секунды (TTL 1 час).
- **Back-test** (1-3 минуты) запускайте только при необходимости — он расходует CPU.
- При нехватке RAM в Cloud — отключите MLP в сайдбаре (нейросеть тяжелее остальных моделей).

### Обновление приложения

После push в `main` ветку GitHub:
- Streamlit Cloud автоматически перестроит app за 2-3 минуты.
- В UI Cloud: **Manage app → Reboot** — принудительный рестарт.

```bash
# Локально внёс изменения
git add .
git commit -m "Update: ..."
git push

# Через 2-3 минуты ссылка покажет новую версию
```

---

## Безопасность

- **FRED API key** — в `.streamlit/secrets.toml` (локально) или **App settings → Secrets** в Cloud UI. Никогда не коммитьте `secrets.toml` в Git.
- **Yahoo Finance, CFTC, Westmetall** — публичные данные, ключи не нужны.
- **Никаких персональных данных** в проекте — только публичные котировки и новости.

---

## Чек-лист перед деплоем

- [ ] `requirements.txt` — версии зафиксированы
- [ ] `.streamlit/config.toml` — тема и настройки сервера
- [ ] `.gitignore` — исключены кэш и временные файлы
- [ ] `app.py` — открывается локально без ошибок (`streamlit run app.py`)
- [ ] GitHub repo создан, проект запушен
- [ ] (Опционально) FRED API key добавлен в Streamlit Secrets

После Deploy! — поделиться ссылкой с заказчиком.
