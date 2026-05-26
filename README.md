# Copper Forecast MVP

MVP по прогнозированию цены меди на горизонты **3 дня / 10 дней / 1 месяц / 3 месяца / 6 месяцев** на основе истории 5 лет, с поддержкой COT-позиций, LME stocks и режимной идентификации.

## Что внутри

| Файл | Назначение |
|---|---|
| `data_loader.py` | Загрузка дневных HG=F (медь COMEX), DXY, WTI, Gold, Silver, S&P 500, US10Y через yfinance. Интегрирует CFTC, LME, FRED. Кэш в `data/`. |
| `extra_sources.py` | **Доп. источники.** CFTC COT через Socrata API (без ключа). Westmetall LME stocks snapshot. FRED bundle (опционально, с ключом). HTTP-обёртка с TLS1.2-минимумом и curl-fallback для Anaconda macOS. |
| `features.py` | Feature engineering: лаги, SMA, RSI, MACD, Bollinger, ATR + COT-фичи (MM net long z-score, Δ4w/Δ12w, OI), LME stocks fields, FRED-aware. Авто-дроп фич с покрытием <50%. |
| `models.py` | Четыре модели: **GBM**, **ARIMA(1,1,1)**, **XGBoost**, **MLP** (sklearn) + взвешенный ансамбль. Точечный прогноз + квантили p10/p25/p75/p90. Защита от выбросов MLP (clip ±3σ). |
| `regimes.py` | **Markov-switching regime detection** на лог-доходностях меди. 2 или 3 режима, автолейблинг (Calm/Turbulent/Bull-volatile…), вероятности на каждую дату. |
| `events.py` | **Каталог 24 ключевых событий 2020-2026** (COVID, Cobre Panamá, Escondida, тарифы Трампа и т.д.) с типом, severity, описанием. Overlay на графики. |
| `news.py` | **RSS-парсер свежих новостей** из Google News (~117 статей по 6 запросам). Автоклассификация по тегам (`supply_shock`, `policy`, `china`, `price_move`, …). |
| `backtest.py` | Walk-forward валидация. MAE, RMSE, MAPE, HitRate, Coverage80 по моделям × горизонтам. |
| `forecast.py` | CLI: `python forecast.py [--backtest] [--with-mlp-backtest] [--no-mlp] [--no-xgb] [--years N] [--refresh]`. |
| `app.py` | Streamlit-дашборд: 6 вкладок (Прогноз, История и макро, COT и запасы, Режимы, Back-test, Сырые данные). Слайдеры весов ансамбля. |
| `update_data.py` | Скрипт для cron: ежедневный refresh всех источников. |

Все источники — **бесплатные**, без обязательных API-ключей (FRED опционален).

## Быстрый старт

```bash
# 1. Установить зависимости
pip install -r requirements.txt

# 2. Запустить CLI-прогноз (быстро, без back-test)
python forecast.py

# 3. Запустить веб-дашборд
streamlit run app.py
```

## Источники данных

| Источник | Покрытие | Частота | Ключ |
|---|---|---|---|
| **Yahoo Finance** (HG=F, DX-Y.NYB, CL=F, GC=F, SI=F, ^GSPC, ^TNX) | 5 лет | дневная | нет |
| **CFTC Public Reporting** (Disaggregated COT, copper 085692) | с 2006 | недельная (вт→пт) | нет |
| **Westmetall** (LME copper stocks snapshot) | snapshot + накопительно | дневная | нет |
| **FRED** (DTWEXBGS, DGS10, DFF, CPIAUCSL, INDPRO, PCOPPUSDM) | 1980+ | дневная/месячная | опционально (FRED_API_KEY) |

### Установка FRED-ключа (опционально)

```bash
# 1. Зарегистрируйтесь на https://fredaccount.stlouisfed.org/apikeys (бесплатно)
# 2. Установите переменную окружения:
export FRED_API_KEY=ваш_ключ_сюда
python forecast.py --refresh
```

## Архитектура моделей

### 1. GBM (Geometric Brownian Motion)
σ_d, μ_d из последних 60 дней лог-доходностей. На горизонте T:
P_T = P₀·exp(μ_d·T + ½σ_d²·T). Усадка drift в 0.5 раза.

### 2. ARIMA(1,1,1)
`statsmodels.tsa.arima.model.ARIMA` на лог-цене, окно 750 дней.

### 3. XGBoost (direct multi-step)
Отдельный регрессор на каждый горизонт H. Цель — `log(P_{t+H}) - log(P_t)`.
Validation = последние 15% точек → residual_std для σ_T (с нижней границей через GBM σ_d·√H).

### 4. MLP (sklearn)
`MLPRegressor(hidden_layer_sizes=(24,12), alpha=5e-2, early_stopping=True)`.
StandardScaler в пайплайне. Точечный прогноз клиппится в ±3·σ_floor, σ_T тоже зажат сверху.

### 5. Ансамбль
Веса по умолчанию: **0.4 XGBoost + 0.2 MLP + 0.25 ARIMA + 0.15 GBM** (настраиваются в Streamlit).

### 6. Markov-switching regimes
`MarkovRegression` с k=2 или k=3 режимами, switching variance.
Идентифицирует «Calm bull», «Correction», «Turbulent». Используется для подсветки текущего состояния рынка и (потенциально) для адаптивного перевзвешивания моделей.

## Что генерируется

```
outputs/
├── forecasts.csv          # все прогнозы (4 модели × 5 горизонтов = 20 строк + Ensemble)
├── history.csv            # последние 252 дня цен
├── backtest_metrics.csv   # если был запущен --backtest
└── plots/
    ├── forecast.png       # история + веер коридоров
    └── correlations.png   # скользящая корреляция Cu с DXY/WTI/Gold/SP500
```

## Метрики back-test (расширяющееся окно, 5 лет, шаг 20 дней, 30 точек)

| Горизонт | Лучшая модель | MAPE | HitRate | Coverage80 |
|---|---|---|---|---|
| 3 дня | ARIMA | 1.6% | 40% | 93% |
| 10 дней | ARIMA | 4.3% | 50% | 77% |
| 1 месяц | ARIMA | 5.5% | 53% | 73% |
| 3 месяца | ARIMA | 9.0% | 53% | 83% |
| 6 месяцев | ARIMA | 11.2% | 63% | 87% |

> **Замечание.** ARIMA(1,1,1) близка к чистому random walk на лог-цене — это эффективный baseline, который ML-модели должны уверенно обыгрывать. Для меди после COVID структурные сдвиги (Cobre Panamá, Escondida, тарифы Трампа 2025) делают ML-модели менее устойчивыми, поэтому ARIMA выигрывает по MAPE. **Ценность XGB/MLP — в направленческом сигнале (HitRate) и в обнаружении выбросов**, а не в точечном прогнозе.

## Streamlit-дашборд: 7 вкладок

1. **📈 Прогноз** — таблица + Plotly график с веером коридоров. Радио-кнопка выбора модели. **Overlay исторических событий** (вертикальные линии). В режиме «Историческая дата» — сравнение прогноз vs факт с таблицей оценки.
2. **🌐 История и макро** — цена + скользящие корреляции с DXY/WTI/Gold/SP500/Silver/US10Y. Слайдер окна корреляции. Overlay critical/high событий.
3. **📋 COT и запасы** — CFTC MM net long (с историей 5 лет) + текущий snapshot LME stocks.
4. **🎭 Режимы** — Markov-switching. Параметры режимов (μ_год, σ_год, persistence), эволюция вероятностей.
5. **📰 Новости и события** — лента из Google News RSS (~117 статей, фильтры по тегам и источникам) + каталог исторических событий с фильтрами.
6. **🔍 Back-test** — walk-forward с настраиваемыми параметрами. Графики MAPE и предсказание-vs-факт по выбранному горизонту.
7. **📊 Сырые данные** — последние 200 строк + кнопка скачивания полного CSV.

**Sidebar:**
- Глубина истории, чекбоксы моделей, веса ансамбля.
- **🕰️ Режим времени:** real-time или историческая дата (с time-slider'ом на главной).

На главной — плашка текущего режима, MM Net Long и LME stocks.

## Автоматическое ежедневное обновление

```bash
# Запускать вручную:
python update_data.py

# Или через crontab — ежедневно в 23:30:
crontab -e
# Добавить строку:
30 23 * * * cd /path/to/copper_forecast_mvp && /usr/bin/python3 update_data.py >> /tmp/copper_update.log 2>&1
```

Что делает:
- Дотягивает новые торговые дни yfinance.
- Запрашивает свежий CFTC COT (выходит вт→пт каждую неделю).
- Парсит сегодняшний snapshot LME stocks → копит в `data/cache_lme_stocks.csv`.
- (Опционально) подтягивает FRED, если задан ключ.

## Файловая структура

```
copper_forecast_mvp/
├── data/                       # CSV-кэш (cache_HG_F.csv, cache_cftc_cot.csv, …)
├── outputs/
│   ├── plots/                  # forecast.png, correlations.png
│   └── *.csv                   # forecasts, history, backtest_metrics
├── data_loader.py
├── extra_sources.py            # COT, LME stocks, FRED
├── features.py
├── models.py
├── regimes.py                  # Markov-switching
├── backtest.py
├── forecast.py                 # CLI
├── update_data.py              # cron-скрипт
├── app.py                      # Streamlit
├── requirements.txt
└── README.md
```

## Ограничения и направления развития

1. **LME stocks — только snapshot.** Историческая таблица за paywall на LME; через Westmetall — только текущее значение. Накапливается через ежедневный `update_data.py` (через несколько недель появляется минимально полезный ряд).
2. **CFTC — недельные данные**, лаг 3 дня (опубликовано в пятницу за вторник). На дневной сетке forward-fill.
3. **MLP клиппится в ±3σ**, чтобы избегать переобучения. При коротких рядах (<300 наблюдений) лучше отключать.
4. **FRED PMI** не входит напрямую (на FRED только индикаторы США). Caixin/NBS PMI требует ручного парсинга S&P Global PMI release-страниц.
5. **Геополитика и забастовки** не моделируются — нужна разметка событий через ACLED или NLP по Reuters/MINING.COM (см. раздел D в исходной аналитической записке).

### Roadmap

- [x] CFTC COT (Money Manager net long)
- [x] LME stocks (snapshot + накопление)
- [x] FRED bundle (опционально)
- [x] Markov-switching regimes
- [x] MLP как 4-я модель
- [x] Auto-refresh скрипт + cron инструкция
- [x] Time-slider для исторической проверки прогноза
- [x] Каталог критических событий 2020-2026 (overlay на графики)
- [x] RSS-новости из Google News (фильтры по тегам и источникам)
- [ ] LSTM/Temporal Fusion Transformer (требует torch)
- [ ] LME COTR (отдельная COT-таблица для LME, не CFTC)
- [ ] Yangshan premium (SMM, требует ручного парсинга)
- [ ] Адаптивные веса ансамбля по текущему режиму
- [ ] News sentiment scoring через NLP (BERT/RoBERTa)
- [ ] Автоматическое привязывание новостей к ценовым движениям (event study)

## Дисклеймер

Это **исследовательский прототип**, не торговая рекомендация. Прогноз основан на ценовых рядах и кросс-активных данных без учёта политических рисков, забастовок и фундаментальных балансов. Реальная волатильность меди >25% годовых; на горизонтах >3 мес большую роль играют шоки предложения, которые модель явно не предсказывает.
