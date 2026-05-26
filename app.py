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
from models import (
    forecast_all_horizons, forecasts_to_dataframe, HORIZONS,
    ensemble_forecast, forecast_at_point, actuals_after_point,
)
from events import EVENTS, events_in_range, events_to_dataframe

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
    results = forecast_all_horizons(raw, use_xgb=use_xgb, use_mlp=use_mlp,
                                    use_arima=use_arima, use_gbm=use_gbm)
    df = forecasts_to_dataframe(results)
    return raw, results, df


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
    as_of = pd.Timestamp(as_of_iso)
    results = forecast_at_point(raw, as_of, use_xgb=use_xgb, use_mlp=use_mlp,
                                use_arima=use_arima, use_gbm=use_gbm)
    actuals = actuals_after_point(raw, as_of)
    df = forecasts_to_dataframe(results)
    return raw, results, df, actuals, as_of


@st.cache_data(ttl=3600, show_spinner="Загружаю новости…")
def cached_news():
    from news import fetch_all_news
    return fetch_all_news(max_per_query=30, cache_ttl_min=60)


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


@st.cache_data(ttl=3600, show_spinner="Запускаю back-test (это медленно)…")
def cached_backtest(years: int, train_min_days: int, step_days: int,
                    use_xgb: bool, use_arima: bool):
    from backtest import walk_forward
    start = (dt.date.today() - dt.timedelta(days=years * 365 + 30)).strftime("%Y-%m-%d")
    raw = load_all(start=start)
    return walk_forward(raw, train_min_days=train_min_days, step_days=step_days,
                        include_xgb=use_xgb, include_arima=use_arima,
                        include_gbm=True, verbose=False)


# ============================================================
#  Side panel
# ============================================================

st.set_page_config(page_title="Copper Forecast MVP",
                   page_icon="🟫", layout="wide")

st.sidebar.title("⚙️ Параметры")
years = st.sidebar.slider("Глубина истории, лет", 3, 10, 5, step=1)
use_xgb = st.sidebar.checkbox("XGBoost", value=True)
use_mlp = st.sidebar.checkbox("MLP (нейронная сеть)", value=True)
use_arima = st.sidebar.checkbox("ARIMA(1,1,1)", value=True)
use_gbm = st.sidebar.checkbox("GBM (статистический baseline)", value=True)

st.sidebar.markdown("### Веса ансамбля")
w_xgb = st.sidebar.slider("XGBoost", 0.0, 1.0, 0.4, step=0.05)
w_mlp = st.sidebar.slider("MLP", 0.0, 1.0, 0.2, step=0.05)
w_arima = st.sidebar.slider("ARIMA", 0.0, 1.0, 0.25, step=0.05)
w_gbm = st.sidebar.slider("GBM", 0.0, 1.0, 0.15, step=0.05)

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
    # Слайдер выбора даты (в основной части main page, до прогноза)
    min_date = raw.index.min().date() + dt.timedelta(days=210)   # минимум ~год обучения
    max_date = raw.index.max().date() - dt.timedelta(days=10)     # хотя бы 10 дней «будущего»
    default_date = max_date - dt.timedelta(days=150)              # по умолчанию полгода назад

    st.warning(
        f"🕰️ **Режим исторической проверки.** Модели обучаются на данных до выбранной "
        f"даты и не знают, что было дальше. Допустимый диапазон: {min_date} … {max_date}."
    )
    as_of_choice = st.slider(
        "Точка прогнозирования (выберите дату из прошлого):",
        min_value=min_date, max_value=max_date,
        value=default_date,
        format="YYYY-MM-DD",
        help="Слайдер двигает «настоящее время» — модели видят только данные слева, "
             "прогноз рисуется на 3д/10д/1м/3м/6м вперёд, а фактическое продолжение "
             "цены — справа.",
    )
    sig = (f"{raw.index.max().date()}_{len(raw)}_{years}_"
            f"{use_xgb}_{use_mlp}_{use_arima}_{use_gbm}_AT_{as_of_choice}")
    raw, results, df_fc, historical_actuals, historical_as_of = cached_forecast_at_point(
        sig, years, as_of_choice.isoformat(),
        use_xgb, use_mlp, use_arima, use_gbm,
    )
else:
    sig = f"{raw.index.max().date()}_{len(raw)}_{years}_{use_xgb}_{use_mlp}_{use_arima}_{use_gbm}"
    raw, results, df_fc = cached_forecast(sig, years, use_xgb, use_mlp, use_arima, use_gbm)

# Применим пользовательские веса к ансамблю
def _custom_ensemble(results_local: Dict) -> Dict[str, dict]:
    """Пересчитать ансамбль с пользовательскими весами."""
    weights = {"XGBoost": w_xgb, "MLP": w_mlp, "ARIMA": w_arima, "GBM": w_gbm}
    weights = {k: v for k, v in weights.items() if v > 0}
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
#  Header
# ============================================================

st.title("🟫 Прогноз цены меди — MVP")
last_date = raw.index.max().date()
p_lb = float(raw["copper"].iloc[-1])
p_t = p_lb * LB_PER_TON
prev_lb = float(raw["copper"].iloc[-2])
delta_pct = (p_lb / prev_lb - 1) * 100

c1, c2, c3, c4 = st.columns(4)
c1.metric("Цена меди (HG=F)", f"{p_lb:.4f} USD/lb", f"{delta_pct:+.2f}%")
c2.metric("В тоннах", f"{p_t:,.0f} USD/t")
c3.metric("Дата котировки", str(last_date))
c4.metric("Глубина истории", f"{len(raw)} дн.")

# Подсветка текущего режима + COT/stocks badges
c5, c6, c7 = st.columns([2, 1, 1])
try:
    fit_quick, _ = cached_regimes(f"{last_date}_{years}_2", k_regimes=2)
    label = fit_quick.label_map[fit_quick.current_regime]
    prob = fit_quick.current_probs[fit_quick.current_regime] * 100
    c5.info(f"🎭 Текущий режим (Markov, k=2): **{label}** — {prob:.1f}%")
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

st.markdown("---")


# ============================================================
#  Tabs
# ============================================================

tab_fc, tab_macro, tab_cot, tab_regimes, tab_news, tab_bt, tab_raw = st.tabs(
    ["📈 Прогноз", "🌐 История и макро", "📋 COT и запасы", "🎭 Режимы",
     "📰 Новости и события", "🔍 Back-test", "📊 Сырые данные"]
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

    # Опции overlay
    col_o1, col_o2 = st.columns([1, 1])
    show_events = col_o1.checkbox("📌 Показать важные события на графике",
                                   value=True)
    event_severity = col_o2.selectbox(
        "Минимальный уровень severity",
        ["low", "medium", "high", "critical"], index=1,
    )

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
    # Горизонтальная линия P0 (add_hline работает — не использует Timestamp)
    fig.add_hline(y=p0_for_plot, line=dict(color="gray", dash="dash", width=1),
                  annotation_text=f"P0 = {p0_for_plot:,.0f}", annotation_position="bottom right")
    # Вертикальная линия точки прогноза — через safe-helper
    _safe_vline(fig, x=last_d, color="gray", dash="dot", width=1,
                annotation_text=f"as of {last_d.date()}")

    # Overlay событий
    if show_events:
        # Диапазон графика
        left_d = hist.index.min().date()
        right_d = (last_d + pd.Timedelta(days=200)).date()
        evs = events_in_range(left_d, right_d, min_severity=event_severity)
        for ev in evs:
            _safe_vline(
                fig, x=pd.Timestamp(ev.date),
                color=ev.color, dash="solid", width=1.2, opacity=0.6,
                annotation_text=f"{ev.icon} {ev.severity[:1].upper()}",
                hovertext=f"<b>{ev.date}</b> {ev.title} · {ev.severity}",
            )

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


# ----- TAB: Новости и события -----
with tab_news:
    st.subheader("📰 Новости и события рынка меди")

    sub_news, sub_events = st.tabs(["📡 Свежие новости (RSS)", "🗂️ Каталог событий 2020-2026"])

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

    if run_bt:
        bt = cached_backtest(years, int(bt_train_days), int(bt_step),
                              use_xgb, use_arima)
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
            M_select = st.selectbox("Модель", all_models,
                                     index=all_models.index("Ensemble") if "Ensemble" in all_models else 0)
        with col_d2:
            available_H = sorted({H for m in bt["predictions"].values() for H in m.keys()})
            label_for_H = {3: "3 дня", 10: "10 дней", 21: "1 месяц",
                            63: "3 месяца", 126: "6 месяцев"}
            H_options = {label_for_H.get(H, f"{H} дн."): H for H in available_H}
            H_multi_labels = st.multiselect(
                "Горизонты прогноза (можно несколько)",
                list(H_options.keys()),
                default=[label_for_H[21]] if 21 in available_H else [list(H_options.keys())[0]],
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
