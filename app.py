"""
app.py — Streamlit-дашборд MVP по прогнозу цены меди.

Запуск:
    streamlit run app.py

Структура:
- Sidebar: параметры (глубина истории, выбор моделей, веса ансамбля).
- Header: текущая цена (USD/lb и USD/t), последняя дата.
- Tab 1 «Прогноз»: таблица + Plotly график с веером коридоров.
- Tab 2 «История и макро»: цена + скользящие корреляции с DXY/WTI/Gold/SP500.
- Tab 3 «Back-test»: walk-forward метрики (если запущен).
- Tab 4 «Сырые данные»: исходники для проверки.
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Dict, Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from data_loader import load_all, LB_PER_TON
from features import describe_feature
from models import (
    forecast_all_horizons, forecasts_to_dataframe, HORIZONS,
    ensemble_forecast, forecast_at_point, actuals_after_point,
    adaptive_weights_from_regime,
)
from events import EVENTS, events_in_range, events_to_dataframe
from seasonality import (
    monthly_avg, monthly_heatmap, dow_avg, best_worst_months,
    stl_decompose, event_study, event_study_by_type,
    current_seasonal_forecast, MONTH_NAMES,
)
from upcoming_events import (
    get_upcoming_events, get_top_events,
    events_to_dataframe as upcoming_to_dataframe,
)
from buyer_logic import (
    compute_verdict, all_verdicts, buyer_factors, VERDICT_META,
)
import history_db
import brief
import lme_forecast as lf

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


# ============================================================
#  Кэширование тяжёлых операций
# ============================================================

@st.cache_data(ttl=3600, show_spinner="Загружаю рыночные данные…")
def cached_load(years: int, refresh: bool = False) -> pd.DataFrame:
    start = (dt.date.today() - dt.timedelta(days=years * 365 + 30)).strftime("%Y-%m-%d")
    return load_all(start=start, refresh=refresh)


@st.cache_data(ttl=3600, show_spinner="Обучаю модели…")
def cached_forecast(_raw_signature: str, years: int,
                    use_xgb: bool, use_mlp: bool, use_arima: bool, use_gbm: bool):
    """raw_signature — служебная строка для invalidate кэша при изменении входов."""
    start = (dt.date.today() - dt.timedelta(days=years * 365 + 30)).strftime("%Y-%m-%d")
    raw = load_all(start=start)
    xgb_models, xgb_x_now = {}, {}
    results = forecast_all_horizons(raw, use_xgb=use_xgb, use_mlp=use_mlp,
                                    use_arima=use_arima, use_gbm=use_gbm,
                                    xgb_models_out=xgb_models,
                                    xgb_x_now_out=xgb_x_now)
    df = forecasts_to_dataframe(results)
    # Префектим SHAP-объяснение для каждого горизонта (быстро, миллисекунды)
    explanations = {}
    for hk, m in xgb_models.items():
        if hk in xgb_x_now:
            try:
                contrib_df, meta = m.explain(xgb_x_now[hk], top_n=10)
                explanations[hk] = {"df": contrib_df, "meta": meta}
            except Exception:
                pass
    return raw, results, df, explanations


@st.cache_data(ttl=3600, show_spinner="Идентифицирую режимы…")
def cached_regimes(_raw_signature: str, k_regimes: int = 2):
    from regimes import fit_markov_regimes
    start_date = dt.date.today() - dt.timedelta(days=5 * 365 + 30)
    raw = load_all(start=start_date.strftime("%Y-%m-%d"),
                    include_cot=False, include_lme_stocks=False,
                    include_fred=False)
    return fit_markov_regimes(raw["copper"], k_regimes=k_regimes), raw


@st.cache_data(ttl=3600, show_spinner="Прогнозирую из исторической точки…")
def cached_forecast_at_point(_signature: str, years: int, as_of_iso: str,
                              use_xgb: bool, use_mlp: bool,
                              use_arima: bool, use_gbm: bool):
    start = (dt.date.today() - dt.timedelta(days=years * 365 + 30)).strftime("%Y-%m-%d")
    raw = load_all(start=start)
    as_of_requested = pd.Timestamp(as_of_iso)

    valid_dates = raw.index[raw.index <= as_of_requested]
    if len(valid_dates) == 0:
        raise ValueError(f"Нет торговых дней до {as_of_requested.date()}")
    as_of = valid_dates.max()

    results = forecast_at_point(raw, as_of, use_xgb=use_xgb, use_mlp=use_mlp,
                                use_arima=use_arima, use_gbm=use_gbm)
    actuals = actuals_after_point(raw, as_of)
    df = forecasts_to_dataframe(results)
    return raw, results, df, actuals, as_of, {}  # пустые объяснения для is режима


@st.cache_data(ttl=3600, show_spinner="Загружаю новости…")
def cached_news():
    from news import fetch_all_news
    return fetch_all_news(max_per_query=30, cache_ttl_min=60)


@st.cache_data(ttl=3600, show_spinner="Анализирую сезонность…")
def cached_seasonality(_raw_signature: str, years: int):
    """Считает сезонные метрики на копии цен меди."""
    start = (dt.date.today() - dt.timedelta(days=years * 365 + 30)).strftime("%Y-%m-%d")
    raw = load_all(start=start, include_cot=False, include_lme_stocks=False,
                    include_lme_price=False, include_fred=False)
    prices = raw["copper"].dropna()
    return {
        "prices": prices,
        "monthly_avg": monthly_avg(prices),
        "monthly_heatmap": monthly_heatmap(prices),
        "dow_avg": dow_avg(prices),
        "best_worst": best_worst_months(prices),
        "stl": stl_decompose(prices, period=252),
        "seasonal_forecast": current_seasonal_forecast(prices),
    }


def _safe_vline(fig, x, color="gray", dash="solid", width=1.0,
                opacity=1.0, annotation_text=None, annotation_y=None,
                hovertext=None, row=None, col=None):
    """Замена add_vline для plotly 6.x + pandas 2.3 (где add_vline ломается
    на Timestamp из-за вычисления среднего точки аннотации).

    Использует add_shape (без shape annotation API), и при необходимости
    отдельный add_annotation. Аннотация позиционируется по y_value явно.
    """
    shape_kwargs = dict(
        type="line", x0=x, x1=x, y0=0, y1=1, yref="paper",
        line=dict(color=color, dash=dash, width=width),
        opacity=opacity,
    )
    if row is not None and col is not None:
        fig.add_shape(**shape_kwargs, row=row, col=col)
    else:
        fig.add_shape(**shape_kwargs)
    if annotation_text:
        ann_kwargs = dict(
            x=x, y=annotation_y if annotation_y is not None else 1.0,
            yref="paper" if annotation_y is None else "y",
            text=annotation_text, showarrow=False,
            font=dict(size=10, color=color),
            xanchor="left", yanchor="top",
        )
        if hovertext:
            ann_kwargs["hovertext"] = hovertext
        if row is not None and col is not None:
            fig.add_annotation(**ann_kwargs, row=row, col=col)
        else:
            fig.add_annotation(**ann_kwargs)


@st.cache_data(ttl=3600, show_spinner="Запускаю back-test… (~30-90 сек)")
def cached_backtest(years: int, train_min_days: int, step_days: int,
                    use_xgb: bool, use_arima: bool):
    from backtest import walk_forward
    start = (dt.date.today() - dt.timedelta(days=years * 365 + 30)).strftime("%Y-%m-%d")
    raw = load_all(start=start)
    return walk_forward(
        raw, train_min_days=train_min_days, step_days=step_days,
        include_xgb=use_xgb, include_arima=use_arima,
        include_gbm=True, verbose=False,
    )


# ============================================================
#  Side panel
# ============================================================

st.set_page_config(page_title="CopperCast — прогноз цены меди",
                   page_icon="🟫", layout="wide")


# ============================================================
#  Авторизация. Активна, ТОЛЬКО если в .env/окружении задан AKRON_PASSWORD.
#  Пароль в коде не хранится — здесь лишь сверка. Без пароля доступ открыт
#  (как раньше), чтобы случайно не заблокировать себя.
# ============================================================
def _auth_gate():
    exp_pass = brief.get_config("AKRON_PASSWORD")
    if not exp_pass:
        return  # авторизация выключена
    if st.session_state.get("auth_ok"):
        return
    exp_login = (brief.get_config("AKRON_LOGIN") or "akron").strip().lower()
    st.markdown("## 🔒 CopperCast — вход")
    st.caption("Доступ к дашборду ограничен. Введите логин и пароль.")
    with st.form("login_form"):
        u = st.text_input("Логин")
        p = st.text_input("Пароль", type="password")
        ok = st.form_submit_button("Войти")
    if ok:
        if u.strip().lower() == exp_login and p == exp_pass:
            st.session_state["auth_ok"] = True
            st.rerun()
        else:
            st.error("Неверный логин или пароль.")
    st.stop()


_auth_gate()

# ============================================================
#  Корпоративный стиль Акрон Холдинг (CSS-инъекция)
# ============================================================
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Golos+Text:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500;600;700&display=swap');

html, body, [class*="css"] { font-family: 'Golos Text', sans-serif; }

/* Карточка вердикта закупщика */
.verdict-card {
    border-radius: 16px; padding: 28px 32px; margin: 8px 0 18px;
    background: #FFFFFF; border: 1px solid #D5DBE0;
    box-shadow: 0 4px 12px rgba(0,24,41,.08);
    position: relative; overflow: hidden;
}
.verdict-card .rail {
    position: absolute; left: 0; top: 0; bottom: 0; width: 8px;
}
.verdict-eyebrow {
    font-size: 12px; font-weight: 700; letter-spacing: .08em;
    text-transform: uppercase; color: #7F8B93; margin-bottom: 6px;
}
.verdict-price {
    font-family: 'JetBrains Mono', monospace; font-size: 52px;
    font-weight: 800; line-height: 1.0; color: #001829;
}
.verdict-price .u { font-size: 22px; color: #7F8B93; font-weight: 600; }
.verdict-rub { font-size: 15px; color: #7F8B93; margin-top: 4px;
               font-family: 'JetBrains Mono', monospace; }
.verdict-tag {
    display: inline-flex; align-items: center; gap: 8px;
    font-size: 22px; font-weight: 800; margin: 16px 0 8px;
    padding: 8px 18px; border-radius: 999px;
}
.verdict-sub { font-size: 16px; color: #001829; line-height: 1.5; }

/* Светофор уверенности */
.conf-light { display: inline-flex; gap: 5px; align-items: center; }
.conf-dot { width: 11px; height: 11px; border-radius: 50%;
            background: #D5DBE0; }

/* Селектор горизонта — мини-карточки */
.hz-mini {
    border-radius: 12px; padding: 12px 14px; text-align: center;
    border: 2px solid #D5DBE0; background: #FFFFFF;
}
.hz-mini .d { font-size: 15px; font-weight: 800; color: #001829; }
.hz-mini .l { font-size: 11px; color: #7F8B93; margin-bottom: 6px; }

/* Чип фактора */
.factor-chip {
    display: inline-flex; align-items: center; gap: 6px;
    padding: 5px 12px; border-radius: 999px; background: #F2F5F7;
    font-size: 13px; margin: 3px 4px 3px 0; color: #001829;
}
.factor-chip .b { width: 9px; height: 9px; border-radius: 50%; }

/* Заголовок-бренд */
.brand-head { display:flex; align-items:baseline; gap: 12px; }
.brand-head .logo { font-size: 30px; font-weight: 900; color: #E00613; }
.brand-head .sub { font-size: 13px; color: #7F8B93; }
</style>
""", unsafe_allow_html=True)

st.sidebar.title("⚙️ Параметры")
years = st.sidebar.slider("Глубина истории, лет", 3, 10, 5, step=1)
use_xgb = st.sidebar.checkbox("XGBoost", value=True)
use_mlp = st.sidebar.checkbox("MLP (нейронная сеть)", value=True)
use_arima = st.sidebar.checkbox("ARIMA(1,1,1)", value=True)
use_gbm = st.sidebar.checkbox("GBM (статистический baseline)", value=True)

st.sidebar.markdown("### Веса ансамбля")
adaptive = st.sidebar.checkbox(
    "🎭 Адаптивные веса по режиму Markov",
    value=True,
    help="В Calm — больше веса XGBoost/MLP. В Turbulent — больше ARIMA/GBM. "
         "Веса линейно интерполируются по вероятности текущего режима.",
)
if adaptive:
    st.sidebar.caption("Слайдеры внизу игнорируются. Веса считаются автоматически из Markov-режима.")
w_xgb = st.sidebar.slider("XGBoost", 0.0, 1.0, 0.4, step=0.05, disabled=adaptive)
w_mlp = st.sidebar.slider("MLP", 0.0, 1.0, 0.2, step=0.05, disabled=adaptive)
w_arima = st.sidebar.slider("ARIMA", 0.0, 1.0, 0.25, step=0.05, disabled=adaptive)
w_gbm = st.sidebar.slider("GBM", 0.0, 1.0, 0.15, step=0.05, disabled=adaptive)

refresh_data = st.sidebar.button("🔄 Обновить котировки")

# --- Режим работы: real-time vs историческая точка ---
st.sidebar.markdown("---")
st.sidebar.markdown("### 🕰️ Режим времени")
time_mode = st.sidebar.radio(
    "Точка отсчёта прогноза",
    ["Сейчас (real-time)", "Историческая дата"],
    index=0,
    help="«Историческая дата» обучает модели только на данных до выбранной точки "
         "и сравнивает прогноз с фактическим продолжением.",
)

st.sidebar.markdown("---")
st.sidebar.caption("Источники: Yahoo Finance (HG=F, DXY, WTI, Gold, Silver, S&P500, US10Y), "
                    "CFTC Public Reporting (COT), Westmetall (LME stocks snapshot), "
                    "FRED (опционально).")
st.sidebar.caption("Прогноз — для исследовательских целей. Не торговая рекомендация.")


# ============================================================
#  Загрузка данных
# ============================================================

if refresh_data:
    cached_load.clear()
    cached_forecast.clear()

raw = cached_load(years=years, refresh=refresh_data)

# Выбор даты для исторического режима — нужен слайдер ПОСЛЕ загрузки raw,
# чтобы знать диапазон.
historical_mode = (time_mode == "Историческая дата")
historical_actuals: Dict[int, float] = {}
historical_as_of: Optional[pd.Timestamp] = None

if historical_mode:
    min_date = raw.index.min().date() + dt.timedelta(days=210)
    max_date = raw.index.max().date() - dt.timedelta(days=10)
    default_date = max_date - dt.timedelta(days=150)

    st.warning(
        f"🕰️ **Режим исторической проверки.** Модели обучаются на данных до выбранной "
        f"даты и не знают, что было дальше. Допустимый диапазон: {min_date} … {max_date}."
    )
    as_of_choice = st.slider(
        "Точка прогнозирования (выберите дату из прошлого):",
        min_value=min_date, max_value=max_date,
        value=default_date,
        format="YYYY-MM-DD",
        help="Модели видят только данные слева, прогноз рисуется на 3д/10д/1м/3м/6м вперёд, "
             "фактическое продолжение цены — справа.",
    )
    sig = (f"{raw.index.max().date()}_{len(raw)}_{years}_"
            f"{use_xgb}_{use_mlp}_{use_arima}_{use_gbm}_AT_{as_of_choice}")
    (raw, results, df_fc, historical_actuals,
     historical_as_of, xgb_explanations) = cached_forecast_at_point(
        sig, years, as_of_choice.isoformat(),
        use_xgb, use_mlp, use_arima, use_gbm,
    )
    if historical_as_of.date() != as_of_choice:
        st.info(
            f"📅 {as_of_choice} — не торговый день. "
            f"Прогноз построен на ближайшую предыдущую торговую дату: "
            f"**{historical_as_of.date()}**."
        )
else:
    sig = f"{raw.index.max().date()}_{len(raw)}_{years}_{use_xgb}_{use_mlp}_{use_arima}_{use_gbm}"
    raw, results, df_fc, xgb_explanations = cached_forecast(
        sig, years, use_xgb, use_mlp, use_arima, use_gbm
    )


# ============================================================
#  Журнал реальных прогнозов (SQLite) — только в режиме «Сейчас».
#  В историческом режиме не пишем, чтобы не засорять журнал ретроспективой.
#  Запись идемпотентна (1 строка на дату×модель×горизонт), сбой журнала
#  не должен ломать приложение — оборачиваем в try/except.
# ============================================================
if not historical_mode:
    try:
        _jr = history_db.record_live_forecast(
            df_fc, as_of_date=raw.index.max(), price_series=raw["copper"]
        )
        if _jr.get("logged") or _jr.get("resolved"):
            logging.info("Журнал прогнозов: +%d записано, %d сверено с фактом",
                         _jr.get("logged", 0), _jr.get("resolved", 0))
    except Exception as _exc:
        logging.warning("Журнал прогнозов недоступен: %s", _exc)

# Применим пользовательские или адаптивные веса к ансамблю
def _get_active_weights() -> Dict[str, float]:
    """Возвращает текущий набор весов: адаптивный или пользовательский."""
    if adaptive:
        # Достаём текущий режим (k=2). Используем кэш regimes, не считаем дважды.
        try:
            sig_r = f"{raw.index.max().date()}_{years}_2"
            fit_quick, _ = cached_regimes(sig_r, k_regimes=2)
            # Идентифицируем «calm» — режим с меньшей сигмой
            sorted_by_sigma = fit_quick.params.sort_values("sigma")
            calm_idx = sorted_by_sigma.index[0]
            calm_prob = fit_quick.current_probs.get(calm_idx, 0.5)
            return adaptive_weights_from_regime(calm_prob)
        except Exception:
            return {"XGBoost": 0.4, "MLP": 0.2, "ARIMA": 0.25, "GBM": 0.15}
    return {"XGBoost": w_xgb, "MLP": w_mlp, "ARIMA": w_arima, "GBM": w_gbm}


active_weights = _get_active_weights()


def _custom_ensemble(results_local: Dict) -> Dict[str, dict]:
    """Пересчитать ансамбль с текущими весами."""
    weights = {k: v for k, v in active_weights.items() if v > 0}
    custom = {}
    for hk, models in results_local.items():
        models_present = {k: v for k, v in models.items() if k in weights}
        if len(models_present) >= 2:
            try:
                custom[hk] = ensemble_forecast(models_present, weights)
            except Exception:
                pass
    return custom


custom_ens = _custom_ensemble(results)


# ============================================================
#  Переключатель режима: Сокращённый ↔ Расширенный
# ============================================================

def _regime_calm_prob() -> Optional[float]:
    try:
        sig_r = f"{raw.index.max().date()}_{years}_2"
        fit_q, _ = cached_regimes(sig_r, k_regimes=2)
        sorted_by_sigma = fit_q.params.sort_values("sigma")
        calm_idx = sorted_by_sigma.index[0]
        return fit_q.current_probs.get(calm_idx, 0.5)
    except Exception:
        return None


hdr_l, hdr_r = st.columns([3, 2])
with hdr_l:
    st.markdown(
        "<div class='brand-head'><span class='logo'>CopperCast</span>"
        "<span class='sub'>медь · прогноз цены · COMEX HG=F</span></div>",
        unsafe_allow_html=True,
    )
with hdr_r:
    app_mode = st.radio(
        "Режим", ["🛒 Сокращённый", "📊 Расширенный"],
        horizontal=True, label_visibility="collapsed",
        help="Сокращённый — простой совет «покупать или ждать». "
             "Расширенный — все модели, метрики, графики.",
    )


# ============================================================
#  BUYER MODE — режим закупщика
# ============================================================

def _conf_light(conf: int, color: str) -> str:
    """HTML-светофор уверенности: 5 точек, закрашено пропорционально conf."""
    filled = round(conf / 20)
    dots = "".join(
        f"<span class='conf-dot' style='background:{color if i < filled else '#D5DBE0'}'></span>"
        for i in range(5)
    )
    return f"<span class='conf-light'>{dots}</span>"


def render_buyer():
    spot_lb = float(raw["copper"].iloc[-1])
    spot_t = spot_lb * LB_PER_TON
    calm = _regime_calm_prob()

    st.markdown(f"## Покупать или подождать?")
    st.caption(f"Медь · COMEX HG=F · спот **{spot_t:,.0f} USD/т** · данные на {raw.index.max().date()}")

    # --- Селектор горизонта ---
    # compute_verdict ждёт {hk: {model_name: HorizonForecast}}.
    # custom_ens[hk] — это один HorizonForecast (наш ансамбль с весами),
    # поэтому оборачиваем его под именем "Ensemble".
    verdict_input = {}
    for hk, models in results.items():
        if hk in custom_ens:
            verdict_input[hk] = {"Ensemble": custom_ens[hk]}
        else:
            verdict_input[hk] = models
    verdicts = all_verdicts(verdict_input, spot_lb, calm)
    if not verdicts:
        st.error("Не удалось построить вердикты — проверьте, что включён хотя бы "
                 "ансамбль из 2 моделей.")
        return

    hz_order = ["h_3d", "h_10d", "h_1m", "h_3m", "h_6m"]
    hz_avail = [h for h in hz_order if h in verdicts]
    hz_labels = {h: verdicts[h].horizon_label for h in hz_avail}

    chosen = st.radio(
        "Горизонт планирования",
        hz_avail, format_func=lambda h: hz_labels[h],
        horizontal=True, index=hz_avail.index("h_1m") if "h_1m" in hz_avail else 0,
    )
    v = verdicts[chosen]

    # --- Карточка вердикта ---
    tone_bg = {"ok": "rgba(25,135,84,.12)", "warn": "rgba(245,158,11,.14)",
               "wait": "rgba(224,6,19,.10)"}[v.tone]
    sub_label = {"h_3d": "ближайшая поставка", "h_10d": "спот-закупка",
                 "h_1m": "месячный контракт", "h_3m": "квартальный контракт",
                 "h_6m": "полугодовой контракт"}.get(chosen, "")

    st.markdown(f"""
<div class='verdict-card'>
  <div class='rail' style='background:{v.color}'></div>
  <div style='padding-left:14px'>
    <div class='verdict-eyebrow'>Цель на {v.horizon_label.lower()} · {sub_label}</div>
    <div class='verdict-price'>{v.median_usd_t:,.0f}<span class='u'> /т</span></div>
    <div class='verdict-rub'>p10–p90: {v.p10_usd_t:,.0f} – {v.p90_usd_t:,.0f} USD/т</div>
    <div class='verdict-tag' style='background:{tone_bg};color:{v.color}'>
      <span style='font-size:24px'>{v.icon}</span> {v.label}
      <span style='font-weight:600;color:#7F8B93'>· {v.ru}</span>
    </div>
    <div class='verdict-sub'>{v.headline}</div>
    <div style='margin-top:14px;display:flex;align-items:center;gap:10px'>
      <span style='font-size:12px;color:#7F8B93;text-transform:uppercase;letter-spacing:.06em'>Уверенность модели</span>
      {_conf_light(v.confidence, v.color)}
      <span style='font-family:JetBrains Mono,monospace;font-weight:700;color:{v.color}'>{v.confidence}%</span>
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

    # --- Метрики сравнения ---
    m1, m2, m3 = st.columns(3)
    m1.metric("Текущий спот", f"{spot_t:,.0f} USD/т")
    m2.metric("Прогноз к сроку", f"{v.median_usd_t:,.0f} USD/т",
              f"{v.change_pct:+.1f}%")
    band = (v.p90_usd_t - v.p10_usd_t) / 2 / v.median_usd_t * 100
    m3.metric("Размах коридора 80%", f"±{band:.1f}%")

    # --- Почему такой совет ---
    with st.expander("❓ Почему такой совет", expanded=True):
        st.write(v.why)
        factors = buyer_factors(raw)
        if factors:
            cmap = {"ok": "#198754", "warn": "#F59E0B", "wait": "#E00613"}
            chips = "".join(
                f"<span class='factor-chip'><span class='b' style='background:{cmap[f['tone']]}'></span>"
                f"{f['title']}: <b>&nbsp;{f['value']}</b></span>"
                for f in factors
            )
            st.markdown(chips, unsafe_allow_html=True)

    # --- Коридор + календарь рисков ---
    col_cor, col_risk = st.columns([1, 1])
    with col_cor:
        st.markdown("##### ⇆ Целевая цена и коридор")
        # Горизонтальная полоса коридора через plotly
        fig_b = go.Figure()
        fig_b.add_trace(go.Scatter(
            x=[v.p10_usd_t, v.p90_usd_t], y=[0, 0], mode="lines",
            line=dict(color=v.color, width=18), opacity=0.25, showlegend=False,
            hoverinfo="skip"))
        fig_b.add_trace(go.Scatter(
            x=[v.median_usd_t], y=[0], mode="markers",
            marker=dict(color=v.color, size=20, line=dict(color="white", width=2)),
            showlegend=False,
            hovertemplate="Прогноз: %{x:,.0f} USD/т<extra></extra>"))
        fig_b.add_trace(go.Scatter(
            x=[spot_t], y=[0], mode="markers",
            marker=dict(color="#001829", size=14, symbol="line-ns",
                        line=dict(color="#001829", width=3)),
            showlegend=False,
            hovertemplate="Сейчас: %{x:,.0f} USD/т<extra></extra>"))
        fig_b.update_layout(
            height=120, margin=dict(l=10, r=10, t=10, b=30),
            yaxis=dict(visible=False, range=[-1, 1]),
            xaxis=dict(title="USD/т", showgrid=True),
        )
        st.plotly_chart(fig_b, use_container_width=True)
        st.caption(f"Синяя зона — где цена окажется в 8 из 10 случаев. "
                   f"Тёмная метка — текущий спот ({spot_t:,.0f}).")

    with col_risk:
        st.markdown("##### ◷ Календарь рисков")
        try:
            ups = get_upcoming_events(days_ahead=45, min_importance="medium")[:5]
            for ev in ups:
                arrow = ev.impact_arrow or ""
                color = {"high": "#E00613", "medium": "#F59E0B",
                         "low": "#7F8B93"}.get(ev.importance, "#7F8B93")
                st.markdown(
                    f"<div style='display:flex;gap:10px;padding:6px 0;border-bottom:1px solid #E1E5E9'>"
                    f"<span style='color:{color};font-weight:700;min-width:64px'>через {ev.days_until} дн.</span>"
                    f"<span style='color:#001829'>{ev.title} "
                    f"<span style='color:#7F8B93'>· {ev.impact_copper or ''} {arrow}</span></span></div>",
                    unsafe_allow_html=True,
                )
        except Exception:
            st.caption("Календарь временно недоступен.")

    st.caption("⚠️ Прогноз — ансамбль 4 моделей с квантильным коридором. "
               "Не является инвестиционной рекомендацией.")


if app_mode == "🛒 Сокращённый":
    render_buyer()
    st.stop()   # не рисуем расширенный интерфейс


# ============================================================
#  Header (расширенный режим)
# ============================================================

st.title("🟫 Прогноз цены меди — MVP")
last_date = raw.index.max().date()
p_lb = float(raw["copper"].iloc[-1])
p_t = p_lb * LB_PER_TON
prev_lb = float(raw["copper"].iloc[-2])
delta_pct = (p_lb / prev_lb - 1) * 100

c1, c2, c3, c4 = st.columns(4)
c1.metric("COMEX HG=F", f"{p_lb:.4f} USD/lb", f"{delta_pct:+.2f}%")
c2.metric("COMEX в тоннах", f"{p_t:,.0f} USD/т")

# LME 3M — глобальный baseline (если есть)
if "lme_3m" in raw.columns and raw["lme_3m"].notna().any():
    lme_3m_val = float(raw["lme_3m"].dropna().iloc[-1])
    premium = (p_t / lme_3m_val - 1) * 100
    c3.metric("LME Cu 3M (глобальный baseline)",
               f"{lme_3m_val:,.0f} USD/т",
               f"премия COMEX {premium:+.2f}%")
else:
    c3.metric("LME Cu 3M", "—", "источник недоступен")

c4.metric("Дата котировки", str(last_date))

# Подсветка текущего режима + COT/stocks badges
c5, c6, c7 = st.columns([2, 1, 1])
try:
    fit_quick, _ = cached_regimes(f"{last_date}_{years}_2", k_regimes=2)
    label = fit_quick.label_map[fit_quick.current_regime]
    prob = fit_quick.current_probs[fit_quick.current_regime] * 100
    weights_str = ""
    if adaptive:
        w_show = " · ".join(f"{k}={int(v*100)}%" for k, v in active_weights.items())
        weights_str = f"<br><small>⚙️ Веса ансамбля: {w_show}</small>"
    c5.markdown(
        f"<div style='background:#E7F0FE;padding:8px 12px;border-radius:4px;"
        f"border-left:4px solid #1E2761;'>🎭 Текущий режим (Markov, k=2): "
        f"<b>{label}</b> — {prob:.1f}%{weights_str}</div>",
        unsafe_allow_html=True,
    )
except Exception:
    pass
if "mm_net_long" in raw.columns and pd.notna(raw["mm_net_long"].iloc[-1]):
    c6.metric("CFTC MM net long",
               f"{int(raw['mm_net_long'].iloc[-1]):,}",
               f"{(raw['mm_net_long_pct'].iloc[-1] if 'mm_net_long_pct' in raw.columns else 0):.1f}% OI")
if "lme_stock_total" in raw.columns and raw["lme_stock_total"].notna().any():
    c7.metric("LME stocks",
               f"{int(raw['lme_stock_total'].dropna().iloc[-1]):,} т",
               f"{int(raw['lme_stock_change'].dropna().iloc[-1] if 'lme_stock_change' in raw.columns else 0):+,} т")

# Плашка ТОП-3 предстоящих событий с прогнозом и влиянием на медь
try:
    top_events = get_top_events(n=3, days_ahead=30)
    if top_events:
        st.markdown("**📅 Ближайшие ключевые события рынка:**")
        ev_cols = st.columns(len(top_events))
        for col, ev in zip(ev_cols, top_events):
            label = f"{ev.region} {ev.icon} {ev.title}"
            days_str = (f"через {ev.days_until} дн." if ev.days_until > 0
                          else "сегодня" if ev.days_until == 0
                          else f"{-ev.days_until} дн. назад")
            # Бейдж влияния на медь
            impact_badge = ""
            if ev.impact_copper:
                impact_badge = (
                    f"<span style='float:right; background:{ev.impact_color}; "
                    f"color:white; padding:1px 6px; border-radius:3px; "
                    f"font-size:11px; font-weight:bold'>"
                    f"Cu {ev.impact_arrow} {ev.impact_copper}</span>"
                )
            consensus_line = ""
            if ev.consensus:
                consensus_line = (f"<br><small style='color:#666'>"
                                  f"🎯 {ev.consensus}</small>")
            col.markdown(
                f"<div style='background:#F7F8FB;border-left:4px solid {ev.color};"
                f"padding:8px 12px;border-radius:4px;font-size:13px;'>"
                f"<b style='color:{ev.color}'>{ev.importance.upper()}</b> "
                f"{impact_badge}<br>"
                f"<span style='color:#555;font-size:11px'>{ev.date} · {days_str}</span><br>"
                f"<span style='color:#242938'>{label}</span>"
                f"{consensus_line}"
                f"</div>",
                unsafe_allow_html=True,
            )
        st.caption("Полный календарь с прогнозами — во вкладке «📰 Новости и события» → «📅 Календарь».")
except Exception:
    pass

st.markdown("---")


# ============================================================
#  Tabs
# ============================================================

(tab_fc, tab_macro, tab_cot, tab_regimes, tab_season, tab_news, tab_bt,
 tab_accuracy, tab_lme, tab_raw) = st.tabs(
    ["📈 Прогноз", "🌐 История и макро", "📋 COT и запасы", "🎭 Режимы",
     "🗓️ Сезонность", "📰 Новости и события", "🔍 Back-test",
     "📒 Точность", "🌍 LME (β)", "📊 Сырые данные"]
)


# ----- TAB 1: Прогноз -----
with tab_fc:
    st.subheader("Прогнозы по горизонтам")

    # Сводка ансамбля (с пользовательскими весами)
    rows = []
    label_map = {h["key"]: h["label"] for h in HORIZONS}
    for hk, h in [(hh["key"], hh) for hh in HORIZONS]:
        if hk not in custom_ens:
            continue
        f = custom_ens[hk]
        rows.append({
            "Горизонт": label_map[hk],
            "Дней": f.days,
            "P0, USD/t": int(round(f.p0 * LB_PER_TON)),
            "p10, USD/t": int(round(f.p10 * LB_PER_TON)),
            "Точечный, USD/t": int(round(f.point * LB_PER_TON)),
            "p90, USD/t": int(round(f.p90 * LB_PER_TON)),
            "Δ, %": round(f.change_pct, 2),
            "P(↑), %": round(f.prob_up * 100, 1),
            "σ_T": round(f.sigma_T, 4),
        })
    if rows:
        ens_df = pd.DataFrame(rows)
        st.markdown("**🎯 Сводный ансамбль (с вашими весами)**")
        st.dataframe(ens_df, use_container_width=True, hide_index=True)

        # === PDF + стресс-тесты + прогнозы инвестбанков ===
        col_pdf, col_stress = st.columns([1, 2])

        with col_pdf:
            if st.button("📄 Сгенерировать PDF-отчёт"):
                try:
                    from report import generate_pdf_report
                    from upcoming_events import get_top_events
                    top5 = get_top_events(5, 30)
                    try:
                        fit_quick_r, _ = cached_regimes(f"{last_date}_{years}_2", 2)
                        reg_label = fit_quick_r.label_map[fit_quick_r.current_regime]
                        reg_prob = fit_quick_r.current_probs[fit_quick_r.current_regime] * 100
                    except Exception:
                        reg_label, reg_prob = "—", 0
                    pdf_bytes = generate_pdf_report(
                        raw_df=raw, forecasts_df=df_fc,
                        regime_label=reg_label, regime_prob=reg_prob,
                        top_events=top5, weights=active_weights,
                    )
                    st.download_button(
                        "💾 Скачать PDF",
                        data=pdf_bytes,
                        file_name=f"copper_forecast_{dt.date.today()}.pdf",
                        mime="application/pdf",
                    )
                except Exception as exc:
                    st.error(f"Ошибка PDF: {exc}")

        with col_stress:
            with st.expander("🔥 Стресс-тесты и прогнозы инвестбанков"):
                st.markdown("**Прогнозы крупных инвестбанков** _(публичные оценки):_")
                ib_data = [
                    {"Банк": "Goldman Sachs",  "2026 average, USD/т": 11400, "2027 target, USD/т": 12500},
                    {"Банк": "Bank of America", "2026 average, USD/т": 11313, "2027 target, USD/т": 13501},
                    {"Банк": "Citi",            "2026 average, USD/т": 11000, "2027 target, USD/т": 12000},
                    {"Банк": "Morgan Stanley",  "2026 average, USD/т": 10800, "2027 target, USD/т": 11500},
                ]
                st.dataframe(pd.DataFrame(ib_data),
                              use_container_width=True, hide_index=True)
                avg_2026 = sum(b["2026 average, USD/т"] for b in ib_data) / len(ib_data)
                current_ens_6m = rows[-1]["Точечный, USD/t"] if rows else None
                if current_ens_6m:
                    delta = (current_ens_6m / avg_2026 - 1) * 100
                    st.caption(f"Средний прогноз банков на 2026: **{avg_2026:,.0f}** USD/т. "
                                f"Наш ансамбль на 6 мес: **{current_ens_6m:,}** ({delta:+.1f}% от среднего).")

                st.markdown("---")
                st.markdown("**Стресс-тесты — повторение известного шока:**")
                stress_scenarios = {
                    "Cobre Panamá (−330 кт)":            -8.0,
                    "Escondida-style strike":            -4.0,
                    "Тариф Трампа 30% (премия COMEX)":  +12.0,
                    "COVID-style demand shock":         -26.0,
                    "China stimulus / V-recovery":      +15.0,
                }
                base = current_ens_6m or p_t
                stress_rows = []
                for name, pct in stress_scenarios.items():
                    new_p = base * (1 + pct / 100)
                    stress_rows.append({
                        "Сценарий": name,
                        "Δ %": f"{pct:+.1f}",
                        "Новая цена, USD/т": int(round(new_p)),
                        "Vs базовый": f"{int(new_p - base):+,}",
                    })
                st.dataframe(pd.DataFrame(stress_rows),
                              use_container_width=True, hide_index=True)
                st.caption(
                    "Простые мультипликаторы из исторических аналогов. "
                    "Себестоимость 90% мин ≈ 5000 USD/т ограничивает падение."
                )

    # График: история + веер прогнозов
    st.markdown("**График прогноза**")

    # В историческом режиме базовая точка — это as_of_date, не сегодня
    if historical_mode and historical_as_of is not None:
        # Серия истории — до as_of_date; будущее (факт) — после
        base_d = historical_as_of
        hist_full = raw["copper"]
        idx_base = hist_full.index.get_loc(base_d) if base_d in hist_full.index else len(hist_full) - 1
    else:
        base_d = raw.index.max()
        hist_full = raw["copper"]
        idx_base = len(hist_full) - 1

    hist_days = st.slider("Показать дней истории до точки прогноза", 30, 750, 252, step=30)
    # История до базовой точки
    left_window = max(0, idx_base - hist_days)
    hist = hist_full.iloc[left_window : idx_base + 1]

    # Опции overlay событий
    st.markdown("**📌 События на графике**")
    col_o1, col_o2, col_o3 = st.columns([1, 1, 1.4])
    show_hist = col_o1.checkbox("Прошлые (сплошные)", value=True,
                                 help="Исторические события из каталога: "
                                      "Cobre Panamá, Escondida, тарифы и т.д.")
    show_upcoming = col_o2.checkbox("Предстоящие (пунктир)", value=True,
                                     help="Будущие события из календаря: "
                                          "FOMC, CPI, PMI, ICSG.")
    detail_level = col_o3.radio(
        "Детализация",
        ["Только ключевые", "Все события"],
        horizontal=True, index=0,
        help="«Только ключевые» = high/critical. «Все» = включая low/medium "
             "(CFTC COT каждую пятницу, ECB и т.п.).",
    )
    # Маппинг детализации в пороги фильтрации
    if detail_level == "Только ключевые":
        hist_min_severity = "high"     # high + critical
        upcoming_min_importance = "high"
    else:
        hist_min_severity = "low"      # все
        upcoming_min_importance = "low"

    fig = go.Figure()

    # 1) История до базовой точки
    fig.add_trace(go.Scatter(
        x=hist.index, y=hist.values * LB_PER_TON,
        mode="lines", name="История (известная модели)",
        line=dict(color="black", width=1.5),
    ))

    # 2) В историческом режиме — фактическое продолжение (то, что было после as_of)
    if historical_mode and historical_as_of is not None:
        # Покажем 1.4× от макс H календарных дней (≈ покрывает 6 месяцев)
        max_H_days_calendar = int(126 * 1.4)
        right_end = min(len(hist_full), idx_base + 130)
        future = hist_full.iloc[idx_base : right_end + 1]
        if len(future) > 1:
            fig.add_trace(go.Scatter(
                x=future.index, y=future.values * LB_PER_TON,
                mode="lines", name="ФАКТ (что было после)",
                line=dict(color="#2ca02c", width=2, dash="dash"),
            ))

    last_d = base_d
    color_map = {"GBM": "#1f77b4", "ARIMA": "#2ca02c",
                 "XGBoost": "#d62728", "MLP": "#9467bd", "Ensemble": "#8b3aa1"}

    selected_model = st.radio("Модель для коридора",
                              ["Ensemble", "XGBoost", "ARIMA", "GBM"],
                              horizontal=True, index=0)

    # Точки прогноза
    for hk in [h["key"] for h in HORIZONS]:
        if selected_model == "Ensemble" and hk in custom_ens:
            f = custom_ens[hk]
        elif hk in results and selected_model in results[hk]:
            f = results[hk][selected_model]
        else:
            continue
        future_d = last_d + pd.Timedelta(days=int(f.days * 1.4))
        col = color_map.get(selected_model, "#666666")
        # Веер: p10-p90 как прямоугольник
        fig.add_trace(go.Scatter(
            x=[future_d, future_d], y=[f.p10 * LB_PER_TON, f.p90 * LB_PER_TON],
            mode="lines", line=dict(color=col, width=10), opacity=0.25,
            showlegend=False, hoverinfo="skip",
        ))
        # p25-p75 — более плотный
        fig.add_trace(go.Scatter(
            x=[future_d, future_d], y=[f.p25 * LB_PER_TON, f.p75 * LB_PER_TON],
            mode="lines", line=dict(color=col, width=10), opacity=0.55,
            showlegend=False, hoverinfo="skip",
        ))
        # Точечный
        fig.add_trace(go.Scatter(
            x=[future_d], y=[f.point * LB_PER_TON],
            mode="markers+text", marker=dict(color=col, size=11),
            text=[f"{f.label}<br>{f.point * LB_PER_TON:,.0f}<br>({f.change_pct:+.1f}%)"],
            textposition="middle right",
            name=f"{selected_model} {f.label}",
            showlegend=False,
        ))

    # Горизонтальная линия P0 (точка прогноза)
    p0_for_plot = float(hist_full.iloc[idx_base]) * LB_PER_TON
    # Горизонтальная линия P0
    fig.add_hline(y=p0_for_plot, line=dict(color="gray", dash="dash", width=1),
                  annotation_text=f"P0 = {p0_for_plot:,.0f}", annotation_position="bottom right")
    # Mining cost — «пол» цены меди (Wood Mackenzie 2024: 90-percentile C1 cost)
    MINING_COST_90P = 5000   # USD/t, 90-percentile минимальная себестоимость
    MINING_COST_50P = 3800   # USD/t, медианная (incl. by-product credits)
    fig.add_hline(
        y=MINING_COST_90P,
        line=dict(color="#B85042", dash="dot", width=1.0),
        annotation_text=f"Себестоимость 90% мин ≈ {MINING_COST_90P:,} (Wood Mackenzie)",
        annotation_position="top left",
    )
    # Вертикальная линия точки прогноза — через safe-helper
    _safe_vline(fig, x=last_d, color="gray", dash="dot", width=1,
                annotation_text=f"as of {last_d.date()}")

    # Overlay событий — границы графика
    left_d = hist.index.min().date()
    right_d = (last_d + pd.Timedelta(days=200)).date()

    # 1) Исторические события (сплошные линии)
    if show_hist:
        evs = events_in_range(left_d, right_d, min_severity=hist_min_severity)
        for ev in evs:
            _safe_vline(
                fig, x=pd.Timestamp(ev.date),
                color=ev.color, dash="solid", width=1.2, opacity=0.6,
                annotation_text=f"{ev.icon} {ev.severity[:1].upper()}",
                hovertext=f"<b>{ev.date}</b> {ev.title} · {ev.severity}",
            )

    # 2) Предстоящие события (пунктирные линии) — попадают в зону прогноза
    if show_upcoming:
        try:
            days_ahead = max(10, (right_d - dt.date.today()).days)
            upcoming = get_upcoming_events(days_ahead=days_ahead,
                                           min_importance=upcoming_min_importance)
            for ev in upcoming:
                arrow = ev.impact_arrow or ""
                _safe_vline(
                    fig, x=pd.Timestamp(ev.date),
                    color=ev.color, dash="dot", width=1.4, opacity=0.7,
                    annotation_text=f"{ev.icon}{arrow}",
                    hovertext=(f"<b>{ev.date}</b> (предстоящее)<br>{ev.title}<br>"
                               f"Консенсус: {ev.consensus or '—'}<br>"
                               f"Влияние на Cu: {ev.impact_copper or '—'}"),
                )
        except Exception:
            pass

    fig.update_layout(
        height=560, hovermode="x unified",
        xaxis_title="Дата", yaxis_title="USD/t",
        margin=dict(l=10, r=10, t=30, b=10),
        title=f"Прогноз ({selected_model}). Веер: тёмный = p25-p75, светлый = p10-p90"
              + (" · Историческая дата прогноза" if historical_mode else ""),
    )
    st.plotly_chart(fig, use_container_width=True)

    # В историческом режиме — сравнение прогноз vs факт
    if historical_mode and historical_actuals:
        st.markdown("### 🎯 Сравнение прогноза с фактом")
        rows_cmp = []
        for h in HORIZONS:
            hk = h["key"]
            actual = historical_actuals.get(h["days"])
            if hk not in results or selected_model not in results[hk]:
                continue
            f = results[hk][selected_model] if selected_model in results[hk] else None
            if f is None:
                continue
            actual_t = (actual * LB_PER_TON) if actual is not None else None
            point_t = f.point * LB_PER_TON
            p0_t = f.p0 * LB_PER_TON
            row = {
                "Горизонт": h["label"],
                "P0, USD/t": int(round(p0_t)),
                "Прогноз, USD/t": int(round(point_t)),
                "Факт, USD/t": int(round(actual_t)) if actual_t else "—",
                "Ошибка, %": round((point_t - actual_t) / actual_t * 100, 2) if actual_t else "—",
                "В коридор p10-p90?": ("✅" if (actual_t and f.p10 * LB_PER_TON <= actual_t <= f.p90 * LB_PER_TON)
                                        else ("❌" if actual_t else "—")),
                "Направление": ("✅ верно" if actual_t and (
                    (point_t > p0_t and actual_t > p0_t) or
                    (point_t < p0_t and actual_t < p0_t)
                ) else ("❌ ошибка" if actual_t else "—")),
            }
            rows_cmp.append(row)
        if rows_cmp:
            st.dataframe(pd.DataFrame(rows_cmp), use_container_width=True,
                          hide_index=True)
            st.caption(f"Модель: **{selected_model}**. "
                        "Коридор p10-p90 ожидаемо покрывает ~80% случаев. "
                        "Направление — на сколько часто угадан рост/падение.")

    # ====== What-if analysis ======
    if xgb_explanations:
        st.markdown("---")
        st.markdown("### 🔮 What-if: что будет, если макрофакторы изменятся?")
        st.caption(
            "Сдвиньте слайдеры, чтобы смоделировать новые значения макрофакторов. "
            "Модель XGBoost мгновенно пересчитает прогноз на каждый горизонт."
        )

        # Берём первый доступный XGBoost-prediction для понимания фичей
        first_hk = next(iter(xgb_explanations))

        col_w1, col_w2, col_w3 = st.columns(3)
        with col_w1:
            wi_dxy = st.slider("DXY, % изменения за 5 дней", -3.0, 3.0, 0.0, 0.1,
                                help="+1.5% = типичная неделя укрепления доллара")
        with col_w2:
            wi_wti = st.slider("WTI, % изменения за 5 дней", -10.0, 10.0, 0.0, 0.5,
                                help="±5% = заметное движение нефти")
        with col_w3:
            wi_vix = st.slider("VIX, ± пунктов", -10.0, 20.0, 0.0, 1.0,
                                help="+10 = резкий risk-off")

        col_w4, col_w5, col_w6 = st.columns(3)
        with col_w4:
            wi_copx = st.slider("COPX (Mining ETF), % за 5 дней", -10.0, 10.0, 0.0, 0.5)
        with col_w5:
            wi_audusd = st.slider("AUD/USD, % изменения", -3.0, 3.0, 0.0, 0.1)
        with col_w6:
            wi_cot = st.slider("COT MM net long, изменение за 4 нед.",
                                -30000, 30000, 0, 5000)

        # Применяем what-if к ML-моделям: пересчитываем XGBoost для каждого
        # доступного горизонта с модифицированными фичами.
        if any(abs(v) > 1e-9 for v in [wi_dxy, wi_wti, wi_vix, wi_copx, wi_audusd, wi_cot]):
            from models import _quantiles, daily_volatility
            import math as _math

            st.markdown("**Сравнение: базовый прогноз vs What-if:**")
            whatif_rows = []
            for h in HORIZONS:
                hk = h["key"]
                if hk not in xgb_explanations:
                    continue
                # Делаем копию x_now с модификациями
                # (нужны xgb_models и xgb_x_now — но они не вернулись через кэш)
                # Поэтому используем простое линейное приближение на основе SHAP-вкладов:
                # find features with similar names, modify their values, multiply by their contributions
                exp = xgb_explanations[hk]
                base_pred = exp["meta"]["prediction"]

                # Простое приближение: delta_pred ≈ sum(feature_value_delta × contribution / current_value)
                # для топ-10 показательных фичей, которые мы умеем модифицировать
                shift = 0.0
                # Маппинг what-if слайдеров на возможные имена фич
                mods = {
                    "dxy_ret_5d": wi_dxy / 100,
                    "wti_ret_5d": wi_wti / 100,
                    "vix_ret_5d": wi_vix / 16.0,  # ~ относительный сдвиг
                    "copx_ret_5d": wi_copx / 100,
                    "audusd_ret_5d": wi_audusd / 100,
                    "cot_mm_net_long_chg_4w": wi_cot,
                }
                cdf = exp["df"]
                for feat, target_val in mods.items():
                    if feat in cdf["feature"].values:
                        row = cdf[cdf["feature"] == feat].iloc[0]
                        # «дельта вклада» ≈ contribution × (new_value - current_value) / max(|current_value|, 1e-6)
                        cur_val = row["value"]
                        contrib_per_unit = (row["contribution"] /
                                             max(abs(cur_val), 1e-6))
                        # знак сохраняется
                        shift += contrib_per_unit * (target_val - cur_val)

                new_pred = base_pred + shift
                P0 = (results[hk].get("XGBoost").p0
                      if "XGBoost" in results[hk] else 1.0)
                base_price = P0 * _math.exp(base_pred) * LB_PER_TON
                new_price = P0 * _math.exp(new_pred) * LB_PER_TON
                whatif_rows.append({
                    "Горизонт": h["label"],
                    "Базовый, USD/т": int(round(base_price)),
                    "What-if, USD/т": int(round(new_price)),
                    "Δ vs base, %": round((new_price / base_price - 1) * 100, 2),
                })
            if whatif_rows:
                st.dataframe(pd.DataFrame(whatif_rows),
                              use_container_width=True, hide_index=True)
                st.info(
                    "💡 What-if — линейное приближение на основе SHAP-вкладов "
                    "(быстро, но грубо). Для точного прогноза с новыми "
                    "значениями нужно полное переобучение."
                )

    # ====== SHAP-объяснение прогноза XGBoost ======
    if xgb_explanations:
        st.markdown("---")
        st.markdown("### 🔍 Почему такой прогноз? (XGBoost SHAP)")
        st.caption(
            "Какие факторы тянули прогноз вверх (зелёные) или вниз (красные). "
            "Значения — вклад каждой фичи в лог-доходность горизонта."
        )

        hk_options = {h["label"]: h["key"] for h in HORIZONS
                      if h["key"] in xgb_explanations}
        if hk_options:
            shap_h_label = st.selectbox(
                "Горизонт для объяснения",
                list(hk_options.keys()), index=2 if len(hk_options) > 2 else 0,
            )
            shap_hk = hk_options[shap_h_label]
            exp = xgb_explanations[shap_hk]
            cdf = exp["df"]
            meta = exp["meta"]

            # Человекочитаемые описания признаков
            cdf = cdf.copy()
            cdf["Что это"] = cdf["feature"].apply(describe_feature)

            col_s1, col_s2 = st.columns([2, 1])
            with col_s1:
                # Горизонтальный bar-chart вкладов
                colors = ["#0F9D58" if c > 0 else "#D93025"
                          for c in cdf["contribution"]]
                fig_shap = go.Figure(go.Bar(
                    y=cdf["feature"][::-1],
                    x=cdf["contribution"][::-1],
                    orientation="h",
                    marker=dict(color=colors[::-1]),
                    customdata=cdf[["value", "Что это"]][::-1].values,
                    hovertemplate=(
                        "<b>%{y}</b><br>"
                        "%{customdata[1]}<br>"
                        "Значение: %{customdata[0]:.4f}<br>"
                        "Вклад: %{x:.5f}<extra></extra>"
                    ),
                ))
                fig_shap.add_vline(x=0, line=dict(color="gray", width=1))
                fig_shap.update_layout(
                    height=380, margin=dict(l=10, r=10, t=20, b=10),
                    xaxis_title="Вклад в прогноз (лог-доходность)",
                    yaxis=dict(automargin=True),
                )
                st.plotly_chart(fig_shap, use_container_width=True)

            with col_s2:
                st.metric("Базовый прогноз", f"{meta['baseline']:.5f}")
                st.metric("Итог модели",
                          f"{meta['prediction']:.5f}",
                          delta=f"{(meta['prediction']-meta['baseline'])*100:.2f}% от baseline")
                st.caption(f"Всего признаков в модели: {meta['total_features']}")
                st.caption("Показано топ-10 по абсолютному вкладу.")

            # Таблица-расшифровка топ-10 признаков
            st.markdown("**📖 Расшифровка показанных признаков:**")
            decode_df = pd.DataFrame({
                "Признак": cdf["feature"],
                "Что это": cdf["Что это"],
                "Тек. значение": cdf["value"].round(4),
                "Вклад": cdf["contribution"].round(5),
                "Направление": ["↑ вверх" if c > 0 else "↓ вниз"
                                for c in cdf["contribution"]],
            })
            st.dataframe(decode_df, use_container_width=True, hide_index=True)

            with st.expander("💡 Как читать + где полный справочник признаков"):
                st.markdown(
                    "- **Зелёные** бары — фичи тянут прогноз **вверх** (рост цены).\n"
                    "- **Красные** — тянут **вниз** (снижение цены).\n"
                    "- Длина = сила влияния (в лог-пространстве доходности).\n"
                    "- Наведите мышь на бар — увидите описание признака и его значение.\n"
                    "- Сумма всех вкладов + baseline = итоговый прогноз модели.\n\n"
                    "**Полный справочник всех ~95 признаков** с формулами — в файле "
                    "`FEATURES.md` (или `FEATURES.docx`) в репозитории проекта."
                )

    # Раскрытие — детальная таблица по всем моделям
    with st.expander("📋 Детальные прогнозы всех моделей"):
        display_df = df_fc.copy()
        for c in ["P0, USD/lb", "Точечный", "p10", "p25", "Медиана", "p75", "p90"]:
            display_df[f"{c} t"] = (display_df[c] * LB_PER_TON).round(0).astype(int)
        st.dataframe(display_df.round({"Δ, %": 2, "P(↑), %": 1, "σ_T": 4}),
                     use_container_width=True, hide_index=True)


# ----- TAB 2: История и макро -----
with tab_macro:
    st.subheader("Цена меди и кросс-активные корреляции")
    col_a, col_b = st.columns([3, 1])

    with col_b:
        macro_window = st.slider("Окно корреляции, дн.", 30, 252, 60, step=10)
        show_assets = st.multiselect(
            "Активы", ["dxy", "wti", "gold", "silver", "sp500", "us10y"],
            default=["dxy", "wti", "gold", "sp500"],
        )

    with col_a:
        # Цена меди
        fig1 = make_subplots(rows=2, cols=1, shared_xaxes=True,
                             vertical_spacing=0.08,
                             subplot_titles=("Цена меди, USD/t",
                                             f"Скользящая корреляция (окно {macro_window} дн.)"))
        fig1.add_trace(
            go.Scatter(x=raw.index, y=raw["copper"] * LB_PER_TON,
                       mode="lines", line=dict(color="black"), name="Cu"),
            row=1, col=1,
        )
        ret = np.log(raw["copper"] / raw["copper"].shift(1))
        for asset in show_assets:
            if asset not in raw.columns:
                continue
            ar = np.log(raw[asset] / raw[asset].shift(1))
            corr = ret.rolling(macro_window).corr(ar)
            fig1.add_trace(
                go.Scatter(x=corr.index, y=corr.values,
                           mode="lines", name=f"corr(Cu, {asset.upper()})"),
                row=2, col=1,
            )
        fig1.add_hline(y=0, line=dict(color="gray", width=0.5), row=2, col=1)

        # Overlay событий (через safe-helper, без plotly add_vline)
        evs = events_in_range(raw.index.min().date(), raw.index.max().date(),
                               min_severity="high")
        for ev in evs:
            _safe_vline(
                fig1, x=pd.Timestamp(ev.date),
                color=ev.color, dash="solid", width=1, opacity=0.5,
                row=1, col=1,
            )

        fig1.update_layout(height=620, margin=dict(l=10, r=10, t=40, b=10),
                           hovermode="x unified")
        st.plotly_chart(fig1, use_container_width=True)
        st.caption("Вертикальные цветные линии — критические/высокие события "
                    "(severity ≥ high) из каталога. См. вкладку «📰 Новости и события».")

    # ====== Карта производства меди ======
    st.markdown("---")
    st.markdown("### 🌍 Производство меди по странам — карта горячих точек")
    st.caption("Источник: USGS Mineral Commodity Summaries 2026.")

    # Топ-15 стран по добыче меди (USGS 2026, тыс. т)
    production_data = {
        "country_iso": ["CHL", "PER", "COD", "CHN", "USA", "AUS", "RUS",
                         "ZMB", "MEX", "KAZ", "CAN", "IDN", "POL", "MNG", "ESP"],
        "country_name": ["Чили", "Перу", "ДРК", "Китай", "США", "Австралия",
                          "Россия", "Замбия", "Мексика", "Казахстан", "Канада",
                          "Индонезия", "Польша", "Монголия", "Испания"],
        "production_kt": [5300, 2700, 2400, 1900, 1100, 950, 920,
                           850, 700, 650, 560, 540, 390, 320, 290],
        "share_pct":    [22.4, 11.4, 10.1, 8.0, 4.6, 4.0, 3.9,
                          3.6, 3.0, 2.7, 2.4, 2.3, 1.6, 1.4, 1.2],
    }
    prod_df = pd.DataFrame(production_data)

    fig_map = go.Figure(go.Choropleth(
        locations=prod_df["country_iso"],
        z=prod_df["production_kt"],
        text=prod_df["country_name"] + ": " +
              prod_df["production_kt"].astype(str) + " кт (" +
              prod_df["share_pct"].astype(str) + "%)",
        colorscale=[
            [0, "#F7F8FB"], [0.3, "#E8A87C"],
            [0.6, "#B87333"], [1, "#1E2761"],
        ],
        colorbar=dict(title="кт/год"),
        hovertemplate="%{text}<extra></extra>",
    ))
    fig_map.update_layout(
        height=400, margin=dict(l=10, r=10, t=10, b=10),
        geo=dict(showframe=False, projection_type="natural earth"),
    )
    st.plotly_chart(fig_map, use_container_width=True)

    col_p1, col_p2 = st.columns([2, 1])
    with col_p1:
        st.markdown("**ТОП-10 стран-производителей**")
        st.dataframe(prod_df.head(10), use_container_width=True, hide_index=True)
    with col_p2:
        top5_total = prod_df.head(5)["share_pct"].sum()
        st.metric("Доля топ-5", f"{top5_total:.1f}%")
        st.metric("Чили + Перу", f"{prod_df.iloc[0:2]['share_pct'].sum():.1f}%")
        st.caption("Сильная концентрация: топ-5 стран дают больше половины мирового производства.")

    # ====== COMEX vs LME 3M (если есть данные) ======
    if "lme_3m" in raw.columns and raw["lme_3m"].notna().sum() > 5:
        st.markdown("---")
        st.markdown("### 🔁 COMEX vs LME 3M — премия и спред")
        st.caption(
            "COMEX HG=F отражает американский рынок (с тарифной премией к LME). "
            "LME 3M — глобальный baseline. Разница важна в эпоху тарифов 2025-2028."
        )

        comex_t = raw["copper"] * LB_PER_TON
        lme = raw["lme_3m"].dropna()
        # Совместный диапазон для визуальной чистоты
        common = comex_t.index.intersection(lme.index)
        if len(common) > 5:
            fig_cl = make_subplots(rows=2, cols=1, shared_xaxes=True,
                                    vertical_spacing=0.08,
                                    subplot_titles=(
                                        "Цены: COMEX (в USD/т) и LME 3M",
                                        "Премия COMEX над LME, %"))
            fig_cl.add_trace(
                go.Scatter(x=common, y=comex_t.loc[common], name="COMEX HG=F",
                            line=dict(color="#d62728", width=1.6)),
                row=1, col=1,
            )
            fig_cl.add_trace(
                go.Scatter(x=common, y=lme.loc[common], name="LME Cu 3M",
                            line=dict(color="#1f77b4", width=1.6, dash="solid")),
                row=1, col=1,
            )
            premium_series = (comex_t.loc[common] / lme.loc[common] - 1) * 100
            fig_cl.add_trace(
                go.Scatter(x=common, y=premium_series, name="Премия %",
                            line=dict(color="#2ca02c", width=1.4),
                            fill="tozeroy",
                            fillcolor="rgba(44,160,44,0.15)"),
                row=2, col=1,
            )
            fig_cl.add_hline(y=0, line=dict(color="gray", width=0.5),
                              row=2, col=1)
            fig_cl.update_layout(height=520, hovermode="x unified",
                                  margin=dict(l=10, r=10, t=40, b=10),
                                  legend=dict(orientation="h",
                                                yanchor="bottom", y=1.02,
                                                xanchor="right", x=1))
            fig_cl.update_yaxes(title_text="USD/т", row=1, col=1)
            fig_cl.update_yaxes(title_text="%", row=2, col=1)
            st.plotly_chart(fig_cl, use_container_width=True)

            # Текущая премия — статистики
            cur_prem = (comex_t.loc[common].iloc[-1] / lme.loc[common].iloc[-1] - 1) * 100
            avg_prem = premium_series.mean()
            max_prem = premium_series.max()
            min_prem = premium_series.min()
            colA, colB, colC, colD = st.columns(4)
            colA.metric("Премия сейчас", f"{cur_prem:+.2f}%")
            colB.metric("Средняя за период", f"{avg_prem:+.2f}%")
            colC.metric("Максимум", f"{max_prem:+.2f}%")
            colD.metric("Минимум", f"{min_prem:+.2f}%")

            with st.expander("ℹ️ Что значит премия COMEX/LME"):
                st.markdown(
                    "- **Норма (2000-2024):** 0–1 % — биржи отражают почти одну "
                    "цену с учётом логистики.\n"
                    "- **8 %** — short-squeeze на COMEX в мае 2024.\n"
                    "- **До 30 %** — анонс тарифов Трампа в июле 2025.\n"
                    "- **Сейчас выше 5 %** — есть смысл предпочесть LME 3M как "
                    "baseline в решениях.\n"
                    "- **Накопление истории:** парсер Westmetall работает ежедневно, "
                    "так что эта картина будет всё длиннее с каждым запуском "
                    "`update_data.py`."
                )

    # Дополнительно — статистика последних значений
    st.markdown("**Сводные параметры волатильности (на основе доходностей)**")
    stats_rows = []
    for col in ["copper"] + show_assets:
        if col not in raw.columns:
            continue
        ret_c = np.log(raw[col] / raw[col].shift(1)).dropna()
        ann_vol = ret_c.tail(60).std() * np.sqrt(252) * 100
        last_ret = ret_c.iloc[-1] * 100
        ytd_ret = (raw[col].iloc[-1] / raw[col].iloc[max(0, len(raw)-252)] - 1) * 100
        stats_rows.append({"Актив": col.upper(),
                           "Σ(60), %": round(ann_vol, 2),
                           "День, %": round(last_ret, 2),
                           "Год, %": round(ytd_ret, 1)})
    st.dataframe(pd.DataFrame(stats_rows), use_container_width=True, hide_index=True)


# ----- TAB 3: COT и запасы -----
with tab_cot:
    st.subheader("CFTC COT: Money Manager positions")
    st.caption("CFTC Commitments of Traders, COMEX copper #085692, Disaggregated Futures Only.")

    if "mm_net_long" not in raw.columns:
        st.info("Данные CFTC недоступны (источник может быть оффлайн). "
                "Перезапустите с кнопкой «🔄 Обновить котировки».")
    else:
        # График: цена + MM net long
        col_l, col_r = st.columns([1, 1])
        with col_l:
            st.metric("MM Net Long, последняя неделя",
                      f"{int(raw['mm_net_long'].iloc[-1]):,} конт.",
                      delta=f"{int(raw['mm_net_long'].iloc[-1] - raw['mm_net_long'].iloc[-21]):+,} за 4 нед")
        with col_r:
            st.metric("Open Interest",
                      f"{int(raw['open_interest'].iloc[-1]):,} конт.",
                      delta=f"{(raw['open_interest'].iloc[-1] / raw['open_interest'].iloc[-21] - 1) * 100:+.1f}% за 4 нед")

        fig_cot = make_subplots(rows=2, cols=1, shared_xaxes=True,
                                vertical_spacing=0.08,
                                subplot_titles=("Цена меди, USD/t",
                                                "CFTC: MM net long и Open Interest, контракты"))
        fig_cot.add_trace(
            go.Scatter(x=raw.index, y=raw["copper"] * LB_PER_TON,
                       mode="lines", line=dict(color="black"), name="Cu"),
            row=1, col=1,
        )
        fig_cot.add_trace(
            go.Scatter(x=raw.index, y=raw["mm_net_long"],
                       mode="lines", line=dict(color="#1f77b4"), name="MM Net Long"),
            row=2, col=1,
        )
        if "open_interest" in raw.columns:
            fig_cot.add_trace(
                go.Scatter(x=raw.index, y=raw["open_interest"],
                           mode="lines", line=dict(color="#ff7f0e", dash="dot"),
                           name="Open Interest"),
                row=2, col=1,
            )
        fig_cot.add_hline(y=0, line=dict(color="gray", width=0.5), row=2, col=1)
        fig_cot.update_layout(height=560, hovermode="x unified",
                              margin=dict(l=10, r=10, t=40, b=10))
        st.plotly_chart(fig_cot, use_container_width=True)

    st.markdown("---")
    st.subheader("LME copper warehouse stocks (Westmetall snapshot)")
    if "lme_stock_total" not in raw.columns or raw["lme_stock_total"].notna().sum() == 0:
        st.info("LME stocks недоступны или ещё не накоплены. "
                "Источник публикует только снапшот на сегодня; "
                "история формируется при ежедневном запуске update_data.py.")
    else:
        last_stk = raw["lme_stock_total"].dropna().iloc[-1]
        last_d = raw["lme_stock_total"].dropna().index[-1].date()
        last_chg = raw["lme_stock_change"].dropna().iloc[-1] if "lme_stock_change" in raw.columns else 0
        st.metric(f"Total LME stocks ({last_d})", f"{int(last_stk):,} т",
                  delta=f"{int(last_chg):+,} т")
        if raw["lme_stock_total"].notna().sum() > 5:
            fig_stk = go.Figure(go.Scatter(
                x=raw["lme_stock_total"].dropna().index,
                y=raw["lme_stock_total"].dropna().values,
                mode="lines+markers", line=dict(color="#1f77b4")))
            fig_stk.update_layout(height=320, title="LME copper stocks накопительно",
                                  yaxis_title="тонн",
                                  margin=dict(l=10, r=10, t=40, b=10))
            st.plotly_chart(fig_stk, use_container_width=True)


# ----- TAB 4: Режимы -----
with tab_regimes:
    st.subheader("Markov-switching: латентные режимы рынка")
    st.caption("Модель MarkovRegression на лог-доходностях меди. "
               "Идентифицирует k режимов с разными μ и σ.")

    k = st.radio("Число режимов", [2, 3], horizontal=True)
    sig_r = f"{raw.index.max().date()}_{years}_{k}"
    try:
        fit, raw_r = cached_regimes(sig_r, k_regimes=int(k))

        col1, col2 = st.columns([1, 2])
        with col1:
            st.markdown(f"**Log-likelihood:** {fit.log_likelihood:.1f}")
            st.markdown("**Параметры режимов**")
            p = fit.params.copy()
            p["μ_год_%"] = (p["mu"] * 252 * 100).round(2)
            p["σ_год_%"] = (p["sigma"] * np.sqrt(252) * 100).round(2)
            p["P(stay)"] = p["persistence"].round(3)
            p.index = [fit.label_map[i] for i in p.index]
            st.dataframe(p[["μ_год_%", "σ_год_%", "P(stay)"]])

        with col2:
            st.markdown("**Текущая (последняя) вероятность каждого режима**")
            for k_i, prob in fit.current_probs.items():
                label = fit.label_map[k_i]
                bar_emoji = "🟩" if k_i == fit.current_regime else "⬜"
                st.progress(prob, text=f"{bar_emoji} {label}: {prob * 100:.1f}%")

        # График вероятностей во времени
        st.markdown("**Эволюция вероятностей режимов**")
        fig_r = make_subplots(rows=2, cols=1, shared_xaxes=True,
                              vertical_spacing=0.08,
                              subplot_titles=("Цена меди, USD/t",
                                              f"Вероятности режимов (k={k})"))
        fig_r.add_trace(
            go.Scatter(x=raw_r.index, y=raw_r["copper"] * LB_PER_TON,
                       line=dict(color="black"), name="Cu"),
            row=1, col=1,
        )
        for col_i, regime_col in enumerate(fit.smoothed_probs.columns):
            label = fit.label_map[col_i]
            fig_r.add_trace(
                go.Scatter(x=fit.smoothed_probs.index, y=fit.smoothed_probs[regime_col],
                           mode="lines", name=label, stackgroup="probs"),
                row=2, col=1,
            )
        fig_r.update_layout(height=620, hovermode="x unified",
                            margin=dict(l=10, r=10, t=40, b=10))
        fig_r.update_yaxes(range=[0, 1], row=2, col=1)
        st.plotly_chart(fig_r, use_container_width=True)
    except Exception as exc:
        st.error(f"Не удалось обучить Markov-switching: {exc}")


# ----- TAB: Сезонность -----
with tab_season:
    st.subheader("🗓️ Сезонный анализ цены меди")
    st.caption(
        "Исторические паттерны: какие месяцы лучше/хуже, как ведёт себя цена "
        "вокруг типичных событий. Бесплатная альтернатива Seasonax — на наших же данных."
    )

    try:
        sig_seas = f"{raw.index.max().date()}_{years}_seasonality"
        seas = cached_seasonality(sig_seas, years)
    except Exception as exc:
        st.error(f"Сезонный анализ не удался: {exc}")
        seas = None

    if seas is not None:
        best, worst = seas["best_worst"]
        col_s1, col_s2, col_s3 = st.columns(3)
        col_s1.metric("Лучший месяц (среднее)", best)
        col_s2.metric("Худший месяц (среднее)", worst)
        col_s3.metric("Глубина истории", f"{years} лет")

        # --- 1. Heatmap годы × месяцы ---
        st.markdown("### 📅 Тепловая карта месячной доходности")
        st.caption("Зелёное — рост, красное — снижение. Видно повторяющиеся паттерны года в год.")
        hm = seas["monthly_heatmap"]
        import plotly.express as px
        fig_hm = px.imshow(
            hm.values, x=hm.columns, y=hm.index,
            color_continuous_scale=["#D93025", "#F5F5F5", "#0F9D58"],
            color_continuous_midpoint=0,
            aspect="auto",
            labels={"x": "Месяц", "y": "Год", "color": "Доходность, %"},
            text_auto=".1f",
        )
        fig_hm.update_layout(height=320, margin=dict(l=10, r=10, t=20, b=10))
        st.plotly_chart(fig_hm, use_container_width=True)

        # --- 2. Среднее по месяцам ---
        col_l, col_r = st.columns([2, 1])
        with col_l:
            st.markdown("### 📊 Средняя доходность по месяцам")
            mavg = seas["monthly_avg"].copy()
            colors = ["#0F9D58" if v > 0 else "#D93025" for v in mavg["Среднее, %"]]
            fig_m = go.Figure(go.Bar(
                x=mavg.index, y=mavg["Среднее, %"],
                marker_color=colors,
                text=[f"{v:+.1f}%" for v in mavg["Среднее, %"]],
                textposition="outside",
            ))
            fig_m.add_hline(y=0, line=dict(color="gray", width=0.5))
            fig_m.update_layout(height=350, margin=dict(l=10, r=10, t=20, b=10),
                                  yaxis_title="Среднее, %")
            st.plotly_chart(fig_m, use_container_width=True)
        with col_r:
            st.markdown("### 📋 По месяцам — таблица")
            st.dataframe(mavg.round(2), use_container_width=True)

        # --- 3. Day-of-week ---
        st.markdown("### 📆 Эффект дня недели")
        dow = seas["dow_avg"]
        col_dl, col_dr = st.columns([2, 1])
        with col_dl:
            colors_d = ["#0F9D58" if v > 0 else "#D93025" for v in dow["Среднее, %"]]
            fig_d = go.Figure(go.Bar(
                x=dow.index, y=dow["Среднее, %"],
                marker_color=colors_d,
                text=[f"{v:+.3f}%" for v in dow["Среднее, %"]],
                textposition="outside",
            ))
            fig_d.add_hline(y=0, line=dict(color="gray", width=0.5))
            fig_d.update_layout(height=280, margin=dict(l=10, r=10, t=20, b=10),
                                  yaxis_title="Среднее, %")
            st.plotly_chart(fig_d, use_container_width=True)
        with col_dr:
            st.dataframe(dow.round(3), use_container_width=True)
            st.caption("Это просто статистическое наблюдение, эффект мелкий "
                       "(на уровне шума). Не торговый сигнал.")

        # --- 4. STL декомпозиция ---
        st.markdown("### 🌊 STL-декомпозиция: тренд + сезонность + шум")
        st.caption(
            "Цена меди разложена на 3 компоненты. **Сезонная** компонента "
            "показывает, насколько текущая цена отклоняется от своего «нормального» "
            "значения для данного месяца года."
        )
        stl = seas["stl"]
        fig_stl = make_subplots(rows=3, cols=1, shared_xaxes=True,
                                  vertical_spacing=0.06,
                                  subplot_titles=("Тренд (log price)",
                                                  "Сезонная компонента (год)",
                                                  "Остаток (шум)"))
        fig_stl.add_trace(go.Scatter(x=stl.trend.index, y=stl.trend.values,
                                       line=dict(color="#1A1A1A"), name="Trend"),
                            row=1, col=1)
        fig_stl.add_trace(go.Scatter(x=stl.seasonal.index, y=stl.seasonal.values * 100,
                                       line=dict(color="#C8102E"), name="Seasonal %"),
                            row=2, col=1)
        fig_stl.add_hline(y=0, line=dict(color="gray", width=0.5), row=2, col=1)
        fig_stl.add_trace(go.Scatter(x=stl.residual.index, y=stl.residual.values * 100,
                                       line=dict(color="#5C5C5C"), name="Residual %"),
                            row=3, col=1)
        fig_stl.add_hline(y=0, line=dict(color="gray", width=0.5), row=3, col=1)
        fig_stl.update_layout(height=540, margin=dict(l=10, r=10, t=40, b=10),
                                showlegend=False, hovermode="x unified")
        st.plotly_chart(fig_stl, use_container_width=True)
        cur_seasonal = float(stl.seasonal.iloc[-1]) * 100
        st.markdown(
            f"**Текущая сезонная компонента: `{cur_seasonal:+.2f} %`**  "
            f"— это значит, что цена сейчас "
            + ("**выше**" if cur_seasonal > 0 else "**ниже**")
            + " своего «среднего сезонного» уровня на эту величину."
        )

        # --- 5. Сезонный прогноз ---
        st.markdown("### 🔮 Сезонный прогноз — что было в эти же дни в прошлом")
        st.caption(
            "Для каждого горизонта берём интервал (сегодня → +H дней) в прошлые "
            f"{years} лет и считаем среднюю доходность. Это **только** сезонная "
            "оценка, без учёта макро и фундаментала."
        )
        sf = seas["seasonal_forecast"]
        rows_sf = []
        p0 = float(seas["prices"].iloc[-1])
        for H, info in sf.items():
            if info is None:
                continue
            label = {3: "3 дня", 10: "10 дней", 21: "1 месяц",
                       63: "3 месяца", 126: "6 месяцев"}.get(H, f"{H}д")
            rows_sf.append({
                "Горизонт": label,
                "P0, USD/lb": f"{p0:.4f}",
                "Сезонный прогноз, USD/lb": f"{info['point_price']:.4f}",
                "Сезонная Δ, %": f"{info['change_pct']:+.2f}",
                "Лет в выборке": info["n_years"],
            })
        if rows_sf:
            st.dataframe(pd.DataFrame(rows_sf), use_container_width=True,
                          hide_index=True)
        st.caption(
            "**Как использовать:** сравните сезонный прогноз с прогнозом модели "
            "из вкладки «📈 Прогноз». Если оба указывают в одну сторону — "
            "уверенность выше. Если расходятся — модель учитывает уникальные "
            "факторы текущего момента."
        )

        # --- 6. Event study на каталоге событий ---
        st.markdown("### 📌 Event study — поведение цены вокруг событий из каталога")
        st.caption(
            "Усреднённое поведение цены меди в окне ±30 дней вокруг событий "
            "из нашего каталога. Группировка по типу события."
        )
        try:
            es_by_type = event_study_by_type(seas["prices"], EVENTS,
                                              before=15, after=45)
            type_labels = {
                "supply_shock": "⛏️ Шоки предложения",
                "demand_shock": "🏭 Шоки спроса",
                "policy": "📜 Политика и тарифы",
                "macro": "💱 Макро (ФРС, ставки)",
                "geopolitical": "🌍 Геополитика",
                "structural": "🔄 Структурные сдвиги",
            }
            fig_es = go.Figure()
            for t, df_es in es_by_type.items():
                if df_es.empty:
                    continue
                fig_es.add_trace(go.Scatter(
                    x=df_es["day"], y=(df_es["avg_price"] - 1) * 100,
                    mode="lines", name=f"{type_labels.get(t, t)} (n={int(df_es['n_events'].max())})",
                    line=dict(width=2),
                ))
            fig_es.add_vline(x=0, line=dict(color="gray", dash="dash"))
            fig_es.add_hline(y=0, line=dict(color="gray", width=0.5))
            fig_es.update_layout(
                height=420, hovermode="x unified",
                margin=dict(l=10, r=10, t=20, b=10),
                xaxis_title="Дней от события (день 0 = событие)",
                yaxis_title="Изменение цены от события, %",
                legend=dict(orientation="h", yanchor="bottom", y=-0.3),
            )
            st.plotly_chart(fig_es, use_container_width=True)
            st.caption(
                "**Чтение графика:** в день 0 произошло событие, цена нормирована = 0. "
                "Линия показывает, **в среднем по всем событиям данного типа**, как "
                "цена двигалась в последующие 45 дней. Например, после **шоков "
                "предложения** цена обычно растёт, после **макро-событий** — падает."
            )
        except Exception as exc:
            st.warning(f"Event study не построен: {exc}")


# ----- TAB: Новости и события -----
with tab_news:
    st.subheader("📰 Новости и события рынка меди")

    sub_brief, sub_calendar, sub_news, sub_events = st.tabs([
        "🤖 ИИ-брифинг",
        "📅 Календарь (предстоящие)",
        "📡 Свежие новости (RSS)",
        "🗂️ Каталог событий 2020-2026",
    ])

    # ---- ИИ-брифинг по рынку меди (LLM курирует свежие заголовки) ----
    with sub_brief:
        st.caption(
            "Ежедневная ИИ-сводка: модель отбирает значимое из свежих заголовков "
            "(лента RSS) и собирает краткий брифинг для отдела закупок. "
            "Обновляется автоматически по утрам на сервере."
        )
        _has_key = bool(brief.get_api_key())
        bc1, bc2 = st.columns([1, 2])
        with bc1:
            if st.button("🔄 Сгенерировать сейчас", disabled=not _has_key,
                         help=None if _has_key else "Не задан API-ключ на сервере"):
                try:
                    with st.spinner("Модель готовит брифинг…"):
                        _res = brief.generate_brief()
                        brief.save_brief(_res)
                    st.success(f"Готово (учтено новостей: {_res['n_news']})")
                    st.rerun()
                except Exception as _exc:
                    st.error(f"Ошибка генерации: {_exc}")
        with bc2:
            if not _has_key:
                st.warning(
                    "API-ключ не задан на сервере — кнопка и авто-генерация отключены. "
                    "Добавьте ключ в файл `.env` рядом с проектом (см. инструкцию).")

        _latest = brief.latest_brief()
        if _latest:
            st.caption(f"🕒 Обновлено: {_latest['generated']:%Y-%m-%d %H:%M}")
            st.markdown(_latest["markdown"])
            _briefs = brief.list_briefs()
            if len(_briefs) > 1:
                with st.expander("📚 Архив брифингов"):
                    _pick = st.selectbox("Дата брифинга",
                                         [b["date"] for b in _briefs], key="brief_pick")
                    _sel = next((b for b in _briefs if b["date"] == _pick), None)
                    if _sel:
                        st.markdown(brief.read_brief(_sel["path"]))
        else:
            st.info(
                "Брифинг ещё не сгенерирован. Если API-ключ задан — нажмите "
                "«Сгенерировать сейчас» или дождитесь утреннего автозапуска (cron).")

    # ---- Календарь предстоящих событий ----
    with sub_calendar:
        st.caption(
            "Курируемый календарь регулярных и специальных событий, способных "
            "повлиять на цену меди. Источник дат: расписания центробанков, "
            "BLS, ICSG, корпоративные релизы."
        )

        col_c1, col_c2, col_c3 = st.columns([1, 1, 1])
        with col_c1:
            cal_days = st.slider("Горизонт, дней", 7, 180, 60, step=7)
        with col_c2:
            cal_min_imp = st.selectbox("Минимальная важность",
                                         ["low", "medium", "high"], index=0)
        with col_c3:
            cal_types = st.multiselect(
                "Типы событий",
                ["rates", "data", "industry", "policy", "conference"],
                default=[],
            )

        upcoming = get_upcoming_events(
            days_ahead=int(cal_days),
            min_importance=cal_min_imp,
            types=cal_types if cal_types else None,
        )
        st.markdown(f"**Найдено: {len(upcoming)} событий**")

        if upcoming:
            # Таблица с прогнозами
            rows = []
            for ev in upcoming:
                days_label = (f"через {ev.days_until}"
                              if ev.days_until > 0
                              else "сегодня" if ev.days_until == 0
                              else f"{-ev.days_until} назад")
                impact_label = (f"{ev.impact_arrow} {ev.impact_copper}"
                                if ev.impact_copper else "—")
                rows.append({
                    "Дата": ev.date,
                    "Дней": days_label,
                    "Регион": ev.region,
                    "Тип": ev.icon + " " + ev.type,
                    "Важность": ev.importance,
                    "Событие": ev.title,
                    "Предыдущее": ev.previous or "—",
                    "Консенсус": ev.consensus or "—",
                    "Влияние на Cu": impact_label,
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True,
                          hide_index=True)

            st.caption(
                "**Прогнозы аналитиков** обновляются ежемесячно командой "
                "разработки на основе публичных источников (CME FedWatch, "
                "Reuters survey, корпоративные релизы). Для ежедневного "
                "уточнения — кликайте на ссылку «🔗 Источник» в каждой карточке ниже."
            )

            # Карточки для high-importance с подробными прогнозами
            high_imp = [e for e in upcoming if e.importance == "high"]
            if high_imp:
                st.markdown("---")
                st.markdown("### 🚨 События с высокой важностью — подробно")
                for ev in high_imp[:10]:
                    with st.container(border=True):
                        col_e1, col_e2 = st.columns([1, 5])
                        with col_e1:
                            st.markdown(f"### {ev.region} {ev.icon}")
                            st.markdown(f"<small><b>{ev.date}</b></small>",
                                          unsafe_allow_html=True)
                            days_label = (f"через {ev.days_until} дн."
                                          if ev.days_until > 0
                                          else "сегодня" if ev.days_until == 0
                                          else f"{-ev.days_until} дн. назад")
                            st.markdown(
                                f"<span style='color:{ev.color}; font-weight:bold'>"
                                f"{ev.importance.upper()}</span><br>"
                                f"<small>{days_label}</small>",
                                unsafe_allow_html=True,
                            )
                            # Бейдж влияния на медь
                            if ev.impact_copper:
                                st.markdown(
                                    f"<div style='margin-top:8px; padding:4px 8px; "
                                    f"background:{ev.impact_color}; color:white; "
                                    f"border-radius:4px; font-size:11px; text-align:center'>"
                                    f"Cu {ev.impact_arrow} <b>{ev.impact_copper}</b></div>",
                                    unsafe_allow_html=True,
                                )
                        with col_e2:
                            st.markdown(f"**{ev.title}**")
                            st.caption(f"`{ev.type}`")
                            st.write(ev.description)

                            # Блок с прогнозами аналитиков
                            if ev.previous or ev.consensus or ev.impact_note:
                                cols_fc = st.columns(2)
                                with cols_fc[0]:
                                    if ev.previous:
                                        st.markdown(
                                            f"📊 **Предыдущее значение**  \n{ev.previous}"
                                        )
                                with cols_fc[1]:
                                    if ev.consensus:
                                        st.markdown(
                                            f"🎯 **Консенсус аналитиков**  \n{ev.consensus}"
                                        )
                                if ev.impact_note:
                                    st.info(f"💡 {ev.impact_note}")

                            # Ссылки
                            links = []
                            if ev.source:
                                links.append(f"[📋 Источник]({ev.source})")
                            if ev.forecast_source:
                                links.append(f"[🔮 Свежие прогнозы]({ev.forecast_source})")
                            if links:
                                st.markdown(" · ".join(links))

    # ---- Свежие новости ----
    with sub_news:
        col_n1, col_n2 = st.columns([3, 1])
        with col_n2:
            if st.button("🔄 Обновить ленту"):
                cached_news.clear()

        try:
            news_df = cached_news()
        except Exception as exc:
            st.error(f"Не удалось загрузить новости: {exc}")
            news_df = pd.DataFrame()

        if news_df.empty:
            st.info("Новостей пока нет в кэше. Нажмите «Обновить ленту».")
        else:
            with col_n1:
                st.caption(
                    f"Источник: Google News RSS. Всего загружено: **{len(news_df)}** статей. "
                    f"Самая свежая: {news_df['published'].max().strftime('%Y-%m-%d %H:%M')}."
                )

            # Агрегированный сентимент по окнам
            try:
                from news import aggregate_sentiment_features
                agg = aggregate_sentiment_features(news_df)
                if agg:
                    st.markdown("**📈 Сентимент новостей о меди (агрегированный):**")
                    s_cols = st.columns(4)
                    def _sent_label(score):
                        if score > 0.2: return "↑ Bullish", "#0F9D58"
                        if score < -0.2: return "↓ Bearish", "#D93025"
                        return "↔ Neutral", "#666"
                    for col, hrs, lbl in zip(s_cols[:3], ["24h", "72h", "7d"],
                                              ["24 часа", "72 часа", "7 дней"]):
                        sc = agg.get(f"sentiment_{hrs}", 0.0)
                        cnt = agg.get(f"news_count_{hrs}", 0)
                        tag, color = _sent_label(sc)
                        col.markdown(
                            f"<div style='background:#F7F8FB;padding:8px;border-radius:4px;"
                            f"border-left:3px solid {color}'>"
                            f"<small>{lbl} ({cnt} статей)</small><br>"
                            f"<b style='color:{color};font-size:18px'>{sc:+.2f}</b> "
                            f"<small>{tag}</small></div>",
                            unsafe_allow_html=True,
                        )
                    s_cols[3].markdown(
                        f"<div style='background:#F7F8FB;padding:8px;border-radius:4px;"
                        f"border-left:3px solid #F4B400'>"
                        f"<small>Шоков предложения 7д</small><br>"
                        f"<b style='font-size:18px'>{agg.get('supply_shock_count_7d', 0)}</b> "
                        f"<small>статей</small></div>",
                        unsafe_allow_html=True,
                    )
                    st.caption("Шкала: −1 (резко bearish) … 0 (нейтрально) … +1 (резко bullish). "
                                "Считается VADER + доменные правила (supply_shock, rally, plunge и т.п.).")
            except Exception:
                pass

            # Фильтры
            all_tags = sorted({t for tags in news_df["tags"].dropna()
                               for t in str(tags).split(",") if t.strip()})
            col_f1, col_f2, col_f3 = st.columns([2, 2, 1])
            with col_f1:
                tag_filter = st.multiselect("Фильтр по тегам", all_tags, default=[])
            with col_f2:
                src_filter = st.multiselect("Фильтр по источнику",
                                             sorted(news_df["source"].dropna().unique().tolist()))
            with col_f3:
                limit = st.number_input("Показать первых", min_value=10, max_value=200,
                                          value=40, step=10)

            filtered = news_df.copy()
            if tag_filter:
                mask = filtered["tags"].fillna("").apply(
                    lambda t: any(tag in str(t).split(",") for tag in tag_filter))
                filtered = filtered[mask]
            if src_filter:
                filtered = filtered[filtered["source"].isin(src_filter)]

            st.markdown(f"**Найдено: {len(filtered)} статей**")

            for _, row in filtered.head(int(limit)).iterrows():
                try:
                    pub_str = pd.Timestamp(row["published"]).strftime("%Y-%m-%d %H:%M")
                except Exception:
                    pub_str = "?"
                tags_str = row.get("tags", "") or ""
                tag_badges = " ".join(f"`{t}`" for t in str(tags_str).split(",") if t.strip())
                with st.container(border=True):
                    st.markdown(
                        f"**[{row['title']}]({row['link']})**  \n"
                        f"_{pub_str}_ · *{row['source']}*  \n"
                        f"{tag_badges}"
                    )
                    if row.get("summary"):
                        st.caption(str(row["summary"])[:300] + ("…" if len(str(row["summary"])) > 300 else ""))

    # ---- Каталог исторических событий ----
    with sub_events:
        st.caption(
            f"Курируемый каталог из {len(EVENTS)} ключевых событий рынка меди "
            f"2020-2026. Источники: аналитическая записка, ICSG, CSIS, Reuters, MINING.COM."
        )

        col_e1, col_e2, col_e3 = st.columns([1, 1, 1])
        with col_e1:
            ev_min_sev = st.selectbox("Минимальный severity",
                                       ["low", "medium", "high", "critical"], index=0)
        with col_e2:
            ev_types = st.multiselect(
                "Типы событий",
                ["supply_shock", "demand_shock", "policy", "macro",
                 "geopolitical", "structural"], default=[],
            )
        with col_e3:
            ev_year_from = st.number_input("С года", min_value=2020, max_value=2026, value=2020)

        evs = events_in_range(
            dt.date(int(ev_year_from), 1, 1),
            dt.date(2026, 12, 31),
            min_severity=ev_min_sev,
            types=ev_types if ev_types else None,
        )
        st.markdown(f"**Найдено: {len(evs)} событий**")

        # Карточки
        for ev in evs:
            with st.container(border=True):
                col_a, col_b = st.columns([1, 5])
                with col_a:
                    st.markdown(f"### {ev.icon}")
                    st.markdown(f"<small>**{ev.date}**</small>", unsafe_allow_html=True)
                    st.markdown(
                        f"<span style='color:{ev.color}; font-weight:bold'>{ev.severity}</span>",
                        unsafe_allow_html=True,
                    )
                with col_b:
                    st.markdown(f"**{ev.title}**")
                    st.caption(f"`{ev.type}`")
                    st.write(ev.description)
                    metrics = []
                    if ev.price_impact_pct is not None:
                        metrics.append(f"Δ цены ≈ **{ev.price_impact_pct:+.1f}%**")
                    if ev.supply_impact_kt is not None:
                        metrics.append(f"Supply impact ≈ **{ev.supply_impact_kt:,.0f} кт**")
                    if metrics:
                        st.caption(" · ".join(metrics))


# ----- TAB: Back-test -----
with tab_bt:
    st.subheader("Walk-forward back-test")
    st.caption(
        "Метрики на исторических данных: каждые `step_days` бизнес-дней "
        "переобучаем модели и проверяем прогноз против факта. "
        "Coverage80 — доля случаев, когда фактическая цена попала в коридор p10-p90."
    )

    col_l, col_r = st.columns([1, 1])
    with col_l:
        bt_train_days = st.number_input("Минимальное окно тренировки, дн.",
                                        min_value=300, max_value=1500, value=600, step=50)
        bt_step = st.number_input("Шаг back-test, дн.", min_value=5, max_value=60, value=20)
    with col_r:
        run_bt = st.button("▶️ Запустить back-test")
        st.caption("⏱ ~1-3 минуты на типичных параметрах")

    # Сохраняем результат бэк-теста в session_state, чтобы он переживал
    # перезагрузку страницы при изменении виджетов «Модель» / «Горизонты».
    if run_bt:
        bt = cached_backtest(years, int(bt_train_days), int(bt_step),
                              use_xgb, use_arima)
        st.session_state["bt_result"] = bt
        st.session_state["bt_params"] = (years, int(bt_train_days), int(bt_step),
                                          use_xgb, use_arima)

    bt = st.session_state.get("bt_result")
    if bt is not None:
        # Если параметры (years, шаг, ...) изменились — подсказка, что нужно
        # перезапустить
        cur_params = (years, int(bt_train_days), int(bt_step), use_xgb, use_arima)
        if st.session_state.get("bt_params") != cur_params:
            st.warning("⚠️ Параметры поменялись после запуска. Нажмите "
                        "«Запустить back-test» снова, чтобы пересчитать.")

        st.success(f"Готово: {len(bt['metrics'])} строк метрик")
        st.dataframe(bt["metrics"].round(4),
                     use_container_width=True, hide_index=True)

        # Bar chart — MAPE по модели и горизонту
        fig_bt = go.Figure()
        for m in bt["metrics"]["Модель"].unique():
            sub = bt["metrics"][bt["metrics"]["Модель"] == m]
            fig_bt.add_trace(go.Bar(name=m, x=sub["Горизонт"],
                                    y=sub["MAPE_%"]))
        fig_bt.update_layout(barmode="group", title="MAPE по горизонту и модели",
                             height=380, margin=dict(l=10, r=10, t=40, b=10),
                             yaxis_title="MAPE, %")
        st.plotly_chart(fig_bt, use_container_width=True)

        # ============================================================
        # Detail: «Прогноз vs Факт» — на правильной календарной шкале
        # ============================================================
        st.markdown("---")
        st.subheader("🎯 Прогноз vs Факт во времени")
        st.caption(
            "Линия факта — реальная цена меди за период бэк-теста. "
            "Линия прогноза — то, что модель предсказывала бы из каждой точки в прошлом, "
            "нарисованная на дате (t + H бизнес-дней), куда модель целилась."
        )

        all_models = list(bt["predictions"].keys())
        col_d1, col_d2 = st.columns([1, 2])
        with col_d1:
            M_select = st.selectbox(
                "Модель", all_models,
                index=all_models.index("Ensemble") if "Ensemble" in all_models else 0,
                key="fvf_model",   # сохраняем выбор в session_state
            )
        with col_d2:
            available_H = sorted({H for m in bt["predictions"].values() for H in m.keys()})
            label_for_H = {3: "3 дня", 10: "10 дней", 21: "1 месяц",
                            63: "3 месяца", 126: "6 месяцев"}
            H_options = {label_for_H.get(H, f"{H} дн."): H for H in available_H}
            H_multi_labels = st.multiselect(
                "Горизонты прогноза (можно несколько)",
                list(H_options.keys()),
                default=[label_for_H[21]] if 21 in available_H else [list(H_options.keys())[0]],
                key="fvf_horizons",   # сохраняем выбор в session_state
            )

        if M_select and H_multi_labels:
            color_palette = ["#d62728", "#1f77b4", "#2ca02c", "#9467bd", "#ff7f0e"]

            fig_d = go.Figure()

            # 1. Чёрная линия — полная история цены меди
            #    (это даёт «фон», где факт виден непрерывно)
            fig_d.add_trace(go.Scatter(
                x=raw.index, y=raw["copper"] * LB_PER_TON,
                mode="lines", name="Факт (медь)",
                line=dict(color="black", width=1.6),
                hovertemplate="%{x|%Y-%m-%d}<br>%{y:,.0f} USD/т<extra>факт</extra>",
            ))

            # 2. Для каждого выбранного горизонта — линия прогноза
            #    Сдвигаем по X на H бизнес-дней вперёд (точка прогноза = t+H)
            for i, H_label in enumerate(H_multi_labels):
                H = H_options[H_label]
                if H not in bt["predictions"].get(M_select, {}):
                    continue
                d = bt["predictions"][M_select][H].copy()
                # Смещаем индекс на H бизнес-дней вперёд (Bday — стандарт pandas)
                shifted_index = d.index + pd.tseries.offsets.BDay(H)
                col_c = color_palette[i % len(color_palette)]

                # Затенение коридора p10-p90
                fig_d.add_trace(go.Scatter(
                    x=shifted_index, y=d["p90"] * LB_PER_TON,
                    mode="lines", line=dict(color=col_c, width=0),
                    showlegend=False, hoverinfo="skip",
                ))
                fig_d.add_trace(go.Scatter(
                    x=shifted_index, y=d["p10"] * LB_PER_TON,
                    mode="lines", line=dict(color=col_c, width=0),
                    fill="tonexty",
                    fillcolor=f"rgba({int(col_c[1:3],16)},{int(col_c[3:5],16)},{int(col_c[5:7],16)},0.10)",
                    name=f"Коридор {H_label}",
                    hoverinfo="skip",
                ))
                # Точечный прогноз — основная линия + маркеры
                fig_d.add_trace(go.Scatter(
                    x=shifted_index, y=d["point"] * LB_PER_TON,
                    mode="lines+markers",
                    name=f"Прогноз {H_label}",
                    line=dict(color=col_c, width=2, dash="dot"),
                    marker=dict(size=6, color=col_c, line=dict(color="white", width=1)),
                    hovertemplate=(
                        "Целевая дата: %{x|%Y-%m-%d}<br>"
                        "Прогноз: %{y:,.0f} USD/т<extra>" + H_label + "</extra>"
                    ),
                ))

            fig_d.update_layout(
                height=520, hovermode="x unified",
                title=f"Модель: {M_select}. Прогнозы на правильной календарной шкале (t + H).",
                margin=dict(l=10, r=10, t=50, b=10),
                xaxis_title="Дата",
                yaxis_title="Цена меди, USD/т",
                legend=dict(orientation="h", yanchor="bottom", y=1.02,
                             xanchor="right", x=1),
            )
            st.plotly_chart(fig_d, use_container_width=True)

            # Метрики для выбранной комбинации
            st.markdown("**Метрики для выбранных горизонтов:**")
            metrics_subset = bt["metrics"][
                (bt["metrics"]["Модель"] == M_select) &
                (bt["metrics"]["Дней"].isin([H_options[lbl] for lbl in H_multi_labels]))
            ].round(2)
            st.dataframe(metrics_subset, use_container_width=True, hide_index=True)

            with st.expander("💡 Как читать этот график"):
                st.markdown(
                    "- **Чёрная линия** — реальная цена меди.\n"
                    "- **Пунктирная цветная линия** — прогноз модели из разных точек прошлого, "
                    "нарисованный на дате, **куда** модель целилась (`t + H` бизнес-дней).\n"
                    "- **Затенённая лента** — коридор `p10-p90` вокруг прогноза.\n"
                    "- Если пунктир **идёт рядом с чёрной линией** — модель работала хорошо.\n"
                    "- Если пунктир **сильно расходится** — это эпизоды, где модель промахивалась "
                    "(обычно вокруг шоков: Cobre Panamá, Escondida, тарифы).\n"
                    "- Несколько горизонтов одновременно — видно, что **короткие горизонты** "
                    "обычно следуют за фактом плотнее, чем длинные."
                )


# ----- TAB 4: Сырые данные -----
with tab_raw:
    st.subheader("Сырые данные (последние 200 строк)")
    show = raw.tail(200).copy()
    show["copper_USDt"] = (show["copper"] * LB_PER_TON).round(2)
    st.dataframe(show, use_container_width=True)
    st.download_button(
        "📥 Скачать полный CSV",
        data=raw.to_csv(index_label="date").encode("utf-8"),
        file_name="copper_market_data.csv",
        mime="text/csv",
    )


# ----- TAB: Точность (реальный журнал прогнозов) -----
with tab_accuracy:
    st.subheader("📒 Точность прогнозов — реальный журнал")
    st.caption(
        "В отличие от Back-test (синтетическая проверка по требованию), здесь "
        "копится журнал **настоящих** прогнозов системы. Когда наступает целевая "
        "дата горизонта и становится известна фактическая цена, прогноз сверяется "
        "с фактом: угадано ли направление, попал ли факт в коридор p10-p90, какова ошибка."
    )

    try:
        _stats = history_db.get_stats()
    except Exception as exc:
        st.error(f"Журнал недоступен: {exc}")
        _stats = None

    if _stats is not None:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Всего прогнозов", _stats["total"])
        c2.metric("Сверено с фактом", _stats["resolved"])
        c3.metric("Ожидают факта", _stats["pending"])
        c4.metric("Период журнала",
                  f"{_stats['first_date']} … {_stats['last_date']}"
                  if _stats["first_date"] else "пусто")
        if _stats["backfill"]:
            st.caption(f"Источник: {_stats['live']} реальных (live) + "
                       f"{_stats['backfill']} исторических (backfill).")

        # --- Сервис: наполнение журнала из back-test ---
        with st.expander("⚙️ Наполнить журнал историческими прогнозами "
                         "(чтобы увидеть аналитику сразу)"):
            st.markdown(
                "Реальный журнал копится постепенно: прогноз на 3 дня сверится через "
                "3 торговых дня, на 6 месяцев — только через полгода. Чтобы увидеть "
                "аналитику точности **немедленно**, засейте журнал ретроспективными "
                "прогнозами из walk-forward back-test (они сразу сверены с фактом)."
            )
            cc1, cc2 = st.columns([1, 1])
            with cc1:
                if st.button("🔄 Наполнить из back-test"):
                    try:
                        _bt = st.session_state.get("bt_result")
                        if _bt is None:
                            with st.spinner("Запускаю back-test (~1-3 мин)…"):
                                _bt = cached_backtest(years, 600, 20, use_xgb, use_arima)
                        n_added = history_db.log_walkforward(_bt["predictions"])
                        st.success(f"Добавлено в журнал: {n_added} исторических прогнозов.")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Не удалось наполнить: {exc}")
            with cc2:
                if st.button("🗑️ Очистить backfill-записи"):
                    n = history_db.clear(source="backfill")
                    st.success(f"Удалено backfill-записей: {n}")
                    st.rerun()

        st.markdown("---")

        if _stats["resolved"] == 0:
            st.info(
                "Пока нет ни одного прогноза, сверенного с фактом. Либо журнал только "
                "начал копиться (вернитесь позже, когда наступят целевые даты), либо "
                "наполните его из back-test в блоке выше."
            )
        else:
            _log_all = history_db.load_log(resolved_only=True)
            models_avail = sorted(_log_all["model"].dropna().unique().tolist())
            default_model = ("Ensemble" if "Ensemble" in models_avail
                             else (models_avail[0] if models_avail else None))

            sub_summary, sub_vs, sub_log = st.tabs(
                ["📊 Сводка по горизонтам", "📈 Прогноз vs факт", "📒 Журнал"]
            )

            # ===== Сводка по горизонтам =====
            with sub_summary:
                summ = history_db.accuracy_summary()
                if summ.empty:
                    st.info("Недостаточно данных для сводки.")
                else:
                    disp = summ.copy()
                    disp["MAE, USD/т"] = (disp["mae"] * LB_PER_TON).round(0)
                    disp["Bias, USD/т"] = (disp["bias"] * LB_PER_TON).round(0)
                    disp = disp.rename(columns={
                        "model": "Модель", "horizon_label": "Горизонт", "n": "N",
                        "hit_rate": "Hit Rate, %", "coverage80": "Coverage80, %",
                        "mape": "MAPE, %",
                    })
                    disp["Hit Rate, %"] = disp["Hit Rate, %"].round(1)
                    disp["Coverage80, %"] = disp["Coverage80, %"].round(1)
                    disp["MAPE, %"] = disp["MAPE, %"].round(2)
                    cols = ["Модель", "Горизонт", "N", "Hit Rate, %",
                            "Coverage80, %", "MAPE, %", "MAE, USD/т", "Bias, USD/т"]
                    st.dataframe(disp[cols], use_container_width=True, hide_index=True)

                    msel = st.selectbox(
                        "Модель для графика", models_avail,
                        index=(models_avail.index(default_model)
                               if default_model in models_avail else 0))
                    sub = summ[summ["model"] == msel].sort_values("horizon_days")
                    if not sub.empty:
                        fig = go.Figure()
                        fig.add_bar(x=sub["horizon_label"], y=sub["hit_rate"],
                                    name="Hit Rate, %", marker_color="#E00613")
                        fig.add_bar(x=sub["horizon_label"], y=sub["coverage80"],
                                    name="Coverage80, %", marker_color="#001829")
                        fig.add_hline(y=50, line_dash="dash", line_color="gray",
                                      annotation_text="50% (случайность)")
                        fig.update_layout(
                            barmode="group", height=380,
                            title=f"Попадание по горизонтам — {msel}",
                            yaxis_title="%", margin=dict(l=10, r=10, t=50, b=10),
                            legend=dict(orientation="h", yanchor="bottom", y=1.02,
                                        xanchor="right", x=1))
                        st.plotly_chart(fig, use_container_width=True)
                        st.caption(
                            "**Hit Rate** — доля угаданных направлений (рост/падение); "
                            ">50% значит модель полезнее подбрасывания монеты. "
                            "**Coverage80** в идеале ≈80% (столько раз факт должен "
                            "попадать в заявленный коридор p10-p90). "
                            "**Bias** >0 — модель в среднем завышает цену."
                        )

            # ===== Прогноз vs факт =====
            with sub_vs:
                cvs1, cvs2 = st.columns([1, 1])
                with cvs1:
                    m_vs = st.selectbox(
                        "Модель", models_avail, key="vs_model",
                        index=(models_avail.index(default_model)
                               if default_model in models_avail else 0))
                with cvs2:
                    h_pick = st.selectbox("Горизонт", [h["label"] for h in HORIZONS],
                                          key="vs_horizon")
                h_days_pick = next(h["days"] for h in HORIZONS if h["label"] == h_pick)
                d = history_db.load_log(resolved_only=True, model=m_vs,
                                        horizon_days=h_days_pick)
                if d.empty:
                    st.info("Нет сверенных прогнозов для этой комбинации.")
                else:
                    d = d.sort_values("actual_date")
                    ad = pd.to_datetime(d["actual_date"])
                    fig = go.Figure()
                    fig.add_trace(go.Scatter(
                        x=ad, y=d["p90"] * LB_PER_TON, mode="lines",
                        line=dict(width=0), showlegend=False, hoverinfo="skip"))
                    fig.add_trace(go.Scatter(
                        x=ad, y=d["p10"] * LB_PER_TON, mode="lines", fill="tonexty",
                        fillcolor="rgba(224,6,19,0.12)", line=dict(width=0),
                        name="Коридор p10-p90"))
                    fig.add_trace(go.Scatter(
                        x=ad, y=d["point"] * LB_PER_TON, mode="lines+markers",
                        line=dict(color="#E00613", dash="dot"), name="Прогноз"))
                    fig.add_trace(go.Scatter(
                        x=ad, y=d["actual_price"] * LB_PER_TON, mode="lines+markers",
                        line=dict(color="#001829"), name="Факт"))
                    fig.update_layout(
                        height=420, title=f"{m_vs} · {h_pick}: прогноз vs факт",
                        xaxis_title="Дата исполнения", yaxis_title="Цена меди, USD/т",
                        margin=dict(l=10, r=10, t=50, b=10),
                        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                                    xanchor="right", x=1))
                    st.plotly_chart(fig, use_container_width=True)
                    mm1, mm2, mm3 = st.columns(3)
                    mm1.metric("Hit Rate", f"{d['direction_correct'].mean() * 100:.0f}%")
                    mm2.metric("Coverage80", f"{d['in_interval_80'].mean() * 100:.0f}%")
                    mm3.metric("MAPE", f"{d['pct_error'].mean():.2f}%")

            # ===== Журнал =====
            with sub_log:
                fc1, fc2, fc3 = st.columns(3)
                with fc1:
                    flt_model = st.selectbox("Модель", ["(все)"] + models_avail,
                                             key="log_model")
                with fc2:
                    flt_h = st.selectbox("Горизонт",
                                         ["(все)"] + [h["label"] for h in HORIZONS],
                                         key="log_h")
                with fc3:
                    only_res = st.checkbox("Только сверенные с фактом", value=True)
                m_arg = None if flt_model == "(все)" else flt_model
                hd_arg = (None if flt_h == "(все)"
                          else next(h["days"] for h in HORIZONS if h["label"] == flt_h))
                dlog = history_db.load_log(resolved_only=only_res, model=m_arg,
                                           horizon_days=hd_arg, limit=2000)
                if dlog.empty:
                    st.info("Журнал пуст для выбранных фильтров.")
                else:
                    view = pd.DataFrame({
                        "База": dlog["as_of_date"],
                        "Гориз.": dlog["horizon_label"],
                        "Модель": dlog["model"],
                        "Прогноз, USD/т": (dlog["point"] * LB_PER_TON).round(0),
                        "Факт, USD/т": (dlog["actual_price"] * LB_PER_TON).round(0),
                        "Напр.": dlog["direction_correct"].map({1: "✅", 0: "❌"}),
                        "В коридоре": dlog["in_interval_80"].map({1: "✅", 0: "❌"}),
                        "Ошибка, %": dlog["pct_error"].round(2),
                        "Источник": dlog["source"],
                    })
                    st.dataframe(view, use_container_width=True, hide_index=True)
                    st.download_button(
                        "📥 Скачать журнал CSV",
                        data=dlog.to_csv(index=False).encode("utf-8"),
                        file_name="forecast_history.csv", mime="text/csv",
                    )


# ----- TAB: LME 3M (бета) -----
with tab_lme:
    st.subheader("🌍 Прогноз LME 3M (бета)")
    st.caption(
        "LME 3M — глобальный бенчмарк меди (COMEX искажён тарифами США 2025). "
        "История LME копится с нуля через Westmetall, поэтому LME-модель «дозревает»: "
        "пока данных мало, прогноз строится через зрелую COMEX-модель + премию."
    )

    _lst = lf.data_status(raw)
    if _lst["n_days"] == 0:
        st.warning("Данные LME 3M ещё не накоплены (источник — Westmetall).")
    else:
        st.markdown(
            f"**Накоплено LME 3M:** {_lst['n_days']} дн. "
            f"({_lst['first']} … {_lst['last']})"
        )
        m1, m2, m3 = st.columns(3)
        m1.metric("GBM", "✅ доступен" if _lst["gbm_ok"] else "⏳ рано")
        m2.metric("ARIMA", "✅ доступен" if _lst["arima_ok"] else "⏳ с 150 дн.")
        m3.metric("ML (XGB/MLP)", "✅ доступен" if _lst["ml_ok"]
                  else f"⏳ ещё ~{_lst['ml_eta_days']} дн.")

        st.markdown("---")

        # 1) Основной прогноз — COMEX-модель, приведённая к LME
        st.markdown("### 🎯 Основной прогноз — COMEX-модель, приведённая к LME")
        _prem = lf.current_premium_pct(raw)
        if _prem is None:
            st.info("Премия COMEX–LME недоступна (нет данных Westmetall).")
        else:
            st.caption(
                f"Текущая премия COMEX над LME 3M: **{_prem:+.1f}%**. Прогноз зрелой "
                "COMEX-модели (ансамбль) переведён в LME-эквивалент. Допущение: "
                "премия сохранится на горизонте."
            )
            try:
                _ens = df_fc[df_fc["Модель"] == "Ensemble"]
                _lme_main = lf.comex_to_lme_df(_ens, _prem)
                _cols = [c for c in ["Горизонт", "P0, USD/т", "p10, USD/т",
                                     "Точечный, USD/т", "p90, USD/т", "Δ, %", "P(↑), %"]
                         if c in _lme_main.columns]
                st.dataframe(_lme_main[_cols], use_container_width=True, hide_index=True)
            except Exception as _exc:
                st.error(f"Не удалось пересчитать прогноз в LME: {_exc}")

        # 2) Прямой GBM на ряду LME 3M
        st.markdown("### 📐 Прямой GBM на ряду LME 3M (второе мнение)")
        _gbm_lme = lf.forecast_lme_gbm(raw)
        if _gbm_lme.empty:
            st.info(f"Недостаточно данных LME для GBM (нужно ≥{lf.GBM_MIN_DAYS} дн., "
                    f"есть {_lst['n_days']}).")
        else:
            st.caption("Считается напрямую по накопленному ряду LME 3M, без опоры на "
                       "COMEX. Надёжно для коротких горизонтов (3–10 дней), на длинных — "
                       "ориентировочно.")
            st.dataframe(_gbm_lme, use_container_width=True, hide_index=True)

        # 3) График COMEX vs LME 3M
        st.markdown("### 📈 COMEX vs LME 3M (накопленный период)")
        _cmp = lf.comex_lme_compare(raw, days=_lst["n_days"])
        if not _cmp.empty:
            _fig = go.Figure()
            for _col, _color in [("COMEX (USD/т)", "#E00613"),
                                 ("LME 3M (USD/т)", "#001829")]:
                if _col in _cmp.columns:
                    _fig.add_trace(go.Scatter(x=_cmp.index, y=_cmp[_col], mode="lines",
                                              name=_col, line=dict(color=_color)))
            _fig.update_layout(height=380, margin=dict(l=10, r=10, t=30, b=10),
                               yaxis_title="USD/т",
                               legend=dict(orientation="h", yanchor="bottom", y=1.02,
                                           xanchor="right", x=1))
            st.plotly_chart(_fig, use_container_width=True)
            st.caption("Расхождение линий = премия COMEX над LME (тарифное искажение 2025).")

        st.info("⚠️ Бета. По мере накопления истории LME автоматически подключатся "
                "ARIMA и ML (Этапы 3–4), а журнал точности будет отдельно отслеживать "
                "качество LME-прогноза.")
