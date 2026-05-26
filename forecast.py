"""
forecast.py — главный CLI-скрипт MVP по прогнозу цены меди.

Что делает:
1. Загружает 5 лет дневных данных (медь HG=F + DXY + WTI + gold + silver + sp500 + us10y).
2. Строит фичи и обучает 3 модели на каждый горизонт (3д, 10д, 1м, 3м, 6м).
3. Считает ансамбль (0.5 XGB + 0.3 ARIMA + 0.2 GBM).
4. Сохраняет:
   - outputs/forecasts.csv — таблица прогнозов
   - outputs/plots/forecast.png — общий график с коридорами
   - outputs/history.csv — последние 90 дней истории
5. Опционально: запускает walk-forward back-test (--backtest).

Использование:
    python forecast.py                  # быстрый прогноз
    python forecast.py --backtest       # + back-test (медленно, ~2 мин)
    python forecast.py --years 5        # глубина истории
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from data_loader import load_all, LB_PER_TON, copper_usd_per_ton
from models import forecast_all_horizons, forecasts_to_dataframe, HORIZONS

logger = logging.getLogger(__name__)
OUT_DIR = Path(__file__).resolve().parent / "outputs"
OUT_DIR.mkdir(exist_ok=True)
(OUT_DIR / "plots").mkdir(exist_ok=True)


def _print_header(raw: pd.DataFrame):
    last_date = raw.index.max().date()
    p_lb = float(raw["copper"].iloc[-1])
    p_t = p_lb * LB_PER_TON
    print()
    print("=" * 78)
    print(f" Прогноз цены меди — MVP")
    print(f" Данные: {raw.index.min().date()} → {last_date}, {len(raw)} строк")
    print(f" Последняя цена: {p_lb:.4f} USD/lb = {p_t:,.2f} USD/t")
    print("=" * 78)


def _format_forecast_table(df: pd.DataFrame) -> pd.DataFrame:
    """Округление для красивого вывода + перевод в USD/t."""
    out = df.copy()
    for col in ["P0, USD/lb", "Точечный", "Медиана", "p10", "p25", "p75", "p90"]:
        out[f"{col}_t"] = out[col] * LB_PER_TON
    cols_order = ["Горизонт", "Дней", "Модель",
                  "P0, USD/lb", "Точечный", "p10", "p25", "Медиана", "p75", "p90",
                  "Δ, %", "P(↑), %", "σ_T"]
    return out[cols_order].round({"P0, USD/lb": 4, "Точечный": 4, "p10": 4,
                                   "p25": 4, "Медиана": 4, "p75": 4, "p90": 4,
                                   "Δ, %": 2, "P(↑), %": 1, "σ_T": 4})


def _plot_forecasts(raw: pd.DataFrame, df_fc: pd.DataFrame, out_path: Path,
                    model_to_plot: str = "Ensemble", history_days: int = 252):
    """График: история + прогнозные коридоры для выбранной модели."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(11, 6))
    hist = raw["copper"].tail(history_days)
    ax.plot(hist.index, hist.values, lw=1.5, color="black", label="История")

    sub = df_fc[df_fc["Модель"] == model_to_plot].copy()
    last_date = hist.index[-1]
    p0 = float(hist.iloc[-1])

    # Точки прогноза на будущей оси
    for _, row in sub.iterrows():
        future_date = last_date + pd.Timedelta(days=int(row["Дней"]) * 1.4)  # календарные дни ~ 1.4 * бизнес-дни
        ax.errorbar(future_date, row["Точечный"],
                    yerr=[[row["Точечный"] - row["p10"]], [row["p90"] - row["Точечный"]]],
                    fmt="o", color="C3", capsize=4, lw=1.2)
        ax.errorbar(future_date, row["Точечный"],
                    yerr=[[row["Точечный"] - row["p25"]], [row["p75"] - row["Точечный"]]],
                    fmt="o", color="C3", capsize=8, lw=2.4)
        ax.annotate(f"{row['Горизонт']}\n{row['Точечный']:.2f}\n({row['Δ, %']:+.1f}%)",
                    xy=(future_date, row["Точечный"]),
                    xytext=(6, 0), textcoords="offset points",
                    fontsize=8, va="center")

    # Текущая цена — горизонтальная пунктирная
    ax.axhline(p0, color="gray", ls="--", lw=0.8, alpha=0.7)
    ax.set_title(f"Прогноз цены меди (модель: {model_to_plot}), USD/lb\n"
                 f"Базовая дата: {last_date.date()}, P0 = {p0:.4f} USD/lb"
                 f" = {p0 * LB_PER_TON:,.0f} USD/t")
    ax.set_ylabel("USD/lb")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper left")

    # Правая шкала — USD/t
    ax2 = ax.twinx()
    ax2.set_ylim(ax.get_ylim()[0] * LB_PER_TON, ax.get_ylim()[1] * LB_PER_TON)
    ax2.set_ylabel("USD/t")

    fig.tight_layout()
    fig.savefig(out_path, dpi=140)
    plt.close(fig)
    logger.info("График сохранён: %s", out_path)


def _plot_correlations(raw: pd.DataFrame, out_path: Path):
    """Скользящие корреляции меди с DXY/WTI/Gold/SP500 (60-дневное окно)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ret = np.log(raw["copper"] / raw["copper"].shift(1))
    fig, ax = plt.subplots(figsize=(11, 5))
    for col in ["dxy", "wti", "gold", "sp500"]:
        if col not in raw.columns:
            continue
        ar = np.log(raw[col] / raw[col].shift(1))
        corr = ret.rolling(60).corr(ar)
        ax.plot(corr.index, corr.values, lw=1.2, label=f"corr(Cu, {col.upper()})")
    ax.axhline(0, color="black", lw=0.5)
    ax.set_title("Скользящая 60-дневная корреляция меди с макрофакторами")
    ax.set_ylabel("Корреляция")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_path, dpi=140)
    plt.close(fig)
    logger.info("График корреляций сохранён: %s", out_path)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Прогноз цены меди — MVP")
    parser.add_argument("--years", type=int, default=5,
                        help="Глубина истории в годах (по умолчанию 5)")
    parser.add_argument("--refresh", action="store_true",
                        help="Принудительно перезагрузить данные, игнорируя кэш")
    parser.add_argument("--backtest", action="store_true",
                        help="Запустить walk-forward back-test (медленно)")
    parser.add_argument("--no-arima", action="store_true",
                        help="Отключить ARIMA (для скорости)")
    parser.add_argument("--no-xgb", action="store_true",
                        help="Отключить XGBoost (для скорости)")
    parser.add_argument("--no-mlp", action="store_true",
                        help="Отключить MLP (по умолчанию включён)")
    parser.add_argument("--with-mlp-backtest", action="store_true",
                        help="Включить MLP в back-test (медленнее)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    start = (dt.date.today() - dt.timedelta(days=args.years * 365 + 30)).strftime("%Y-%m-%d")
    raw = load_all(start=start, refresh=args.refresh)
    _print_header(raw)

    # ---- 1. Прогнозы ----
    results = forecast_all_horizons(
        raw,
        use_xgb=not args.no_xgb,
        use_mlp=not args.no_mlp,
        use_arima=not args.no_arima,
        use_gbm=True,
    )
    df_fc = forecasts_to_dataframe(results)
    df_fc_pretty = _format_forecast_table(df_fc)

    print("\n--- Прогнозы по моделям (USD/lb) ---")
    print(df_fc_pretty.to_string(index=False))

    # Сводка по ансамблю в USD/t
    print("\n--- Ансамбль: коридоры в USD/t ---")
    ens = df_fc[df_fc["Модель"] == "Ensemble"].copy()
    if not ens.empty:
        ens_t = pd.DataFrame({
            "Горизонт": ens["Горизонт"],
            "P0, USD/t": (ens["P0, USD/lb"] * LB_PER_TON).round(0).astype(int),
            "p10, USD/t": (ens["p10"] * LB_PER_TON).round(0).astype(int),
            "Точечный, USD/t": (ens["Точечный"] * LB_PER_TON).round(0).astype(int),
            "p90, USD/t": (ens["p90"] * LB_PER_TON).round(0).astype(int),
            "Δ, %": ens["Δ, %"].round(2),
            "P(↑), %": ens["P(↑), %"].round(1),
        })
        print(ens_t.to_string(index=False))

    # ---- 2. Сохранение CSV ----
    df_fc.to_csv(OUT_DIR / "forecasts.csv", index=False)
    raw["copper"].tail(252).to_csv(OUT_DIR / "history.csv", header=True)
    logger.info("Прогнозы сохранены: %s", OUT_DIR / "forecasts.csv")

    # ---- 3. Графики ----
    try:
        _plot_forecasts(raw, df_fc, OUT_DIR / "plots" / "forecast.png", "Ensemble")
        _plot_correlations(raw, OUT_DIR / "plots" / "correlations.png")
    except Exception as exc:
        logger.warning("Не удалось построить графики: %s", exc)

    # ---- 4. Back-test (опционально) ----
    if args.backtest:
        from backtest import walk_forward, summarize_metrics
        print("\n--- Walk-forward back-test ---")
        bt = walk_forward(raw, train_min_days=600, step_days=20,
                          include_xgb=not args.no_xgb,
                          include_mlp=args.with_mlp_backtest,
                          include_arima=not args.no_arima)
        print(summarize_metrics(bt["metrics"]))
        bt["metrics"].to_csv(OUT_DIR / "backtest_metrics.csv", index=False)
        logger.info("Метрики back-test сохранены: %s", OUT_DIR / "backtest_metrics.csv")

    print("\n" + "=" * 78)
    print(f" Готово. Файлы — в {OUT_DIR}")
    print("=" * 78 + "\n")


if __name__ == "__main__":
    main(sys.argv[1:])
