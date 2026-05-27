"""
report.py — генерация PDF-отчёта по текущему прогнозу.

Делает компактный отчёт на 1-2 страницы:
- Шапка: дата, текущая цена, режим Markov
- Таблица прогнозов на 5 горизонтов (ансамбль)
- ТОП-3 предстоящих события с consensus
- Сравнение COMEX/LME и премия
- Footer с дисклеймером
"""
from __future__ import annotations

import datetime as dt
import io
from typing import Dict, List, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER

LB_PER_TON = 2204.62262

COL_NAVY = colors.HexColor("#1E2761")
COL_COPPER = colors.HexColor("#B87333")
COL_GREEN = colors.HexColor("#0F9D58")
COL_RED = colors.HexColor("#D93025")
COL_GRAY = colors.HexColor("#666666")
COL_LIGHT = colors.HexColor("#F7F8FB")


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("title", parent=base["Title"],
                                  fontSize=20, textColor=COL_NAVY,
                                  spaceAfter=6, alignment=TA_LEFT),
        "h2": ParagraphStyle("h2", parent=base["Heading2"],
                              fontSize=13, textColor=COL_COPPER,
                              spaceAfter=4, spaceBefore=8),
        "body": ParagraphStyle("body", parent=base["BodyText"],
                                fontSize=10, leading=13),
        "small": ParagraphStyle("small", parent=base["BodyText"],
                                  fontSize=8, leading=10, textColor=COL_GRAY),
        "metric_label": ParagraphStyle("ml", parent=base["BodyText"],
                                         fontSize=9, textColor=COL_GRAY,
                                         alignment=TA_CENTER),
        "metric_value": ParagraphStyle("mv", parent=base["BodyText"],
                                         fontSize=14, textColor=COL_NAVY,
                                         alignment=TA_CENTER, leading=18),
    }


def generate_pdf_report(
    raw_df,
    forecasts_df,
    regime_label: str,
    regime_prob: float,
    top_events: list,
    weights: Dict[str, float],
    out_path: Optional[str] = None,
) -> bytes:
    """Генерирует PDF-отчёт и возвращает как bytes.

    Параметры:
      raw_df          — DataFrame с колонкой 'copper' (USD/lb)
                        и опционально 'lme_3m' (USD/т).
      forecasts_df    — таблица прогнозов от forecasts_to_dataframe().
      regime_label    — текстовая метка текущего режима Markov.
      regime_prob     — вероятность этого режима в %.
      top_events      — список UpcomingEvent (топ-3).
      weights         — текущие веса ансамбля.
      out_path        — если задан, дополнительно сохранить в файл.

    Возвращает bytes — содержимое PDF (для st.download_button).
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=15*mm, rightMargin=15*mm,
        topMargin=15*mm, bottomMargin=15*mm,
        title="Прогноз цены меди — отчёт",
    )

    S = _styles()
    elements = []

    # --- Шапка ---
    today = dt.date.today().strftime("%d.%m.%Y")
    elements.append(Paragraph("Прогноз цены меди", S["title"]))
    elements.append(Paragraph(
        f"Отчёт от {today}. Автоматическая система прогнозирования.",
        S["small"],
    ))
    elements.append(Spacer(1, 8))

    # --- Метрики ---
    p_lb = float(raw_df["copper"].iloc[-1])
    p_t = p_lb * LB_PER_TON
    last_date = raw_df.index.max()
    lme_val = None
    if "lme_3m" in raw_df.columns and raw_df["lme_3m"].notna().any():
        lme_val = float(raw_df["lme_3m"].dropna().iloc[-1])
        premium = (p_t / lme_val - 1) * 100
    else:
        premium = None

    metric_data = [
        [Paragraph("COMEX HG=F", S["metric_label"]),
         Paragraph("LME Cu 3M", S["metric_label"]),
         Paragraph("Премия COMEX", S["metric_label"]),
         Paragraph("Режим Markov", S["metric_label"])],
        [Paragraph(f"<b>{p_t:,.0f}</b> USD/т", S["metric_value"]),
         Paragraph(f"<b>{lme_val:,.0f}</b> USD/т" if lme_val else "—",
                    S["metric_value"]),
         Paragraph(f"<b>{premium:+.2f}%</b>" if premium is not None else "—",
                    S["metric_value"]),
         Paragraph(f"<b>{regime_label}</b><br/><font size=9>{regime_prob:.1f}%</font>",
                    S["metric_value"])],
    ]
    metrics_table = Table(metric_data, colWidths=[45*mm, 45*mm, 35*mm, 55*mm])
    metrics_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), COL_LIGHT),
        ("BOX", (0, 0), (-1, -1), 0.5, COL_GRAY),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, COL_LIGHT),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(metrics_table)
    elements.append(Spacer(1, 12))

    # --- Прогнозы ансамбля ---
    elements.append(Paragraph("🎯 Прогноз цены меди по горизонтам (ансамбль)",
                                S["h2"]))
    if not forecasts_df.empty:
        ens = forecasts_df[forecasts_df["Модель"] == "Ensemble"].copy()
        if not ens.empty:
            rows = [["Горизонт", "p10 (USD/т)", "Точечный (USD/т)",
                     "p90 (USD/т)", "Δ vs P0", "P(↑) %"]]
            for _, r in ens.iterrows():
                rows.append([
                    str(r["Горизонт"]),
                    f"{int(round(r['p10']*LB_PER_TON)):,}",
                    f"{int(round(r['Точечный']*LB_PER_TON)):,}",
                    f"{int(round(r['p90']*LB_PER_TON)):,}",
                    f"{r['Δ, %']:+.2f}%",
                    f"{r['P(↑), %']:.1f}%",
                ])
            tbl = Table(rows, colWidths=[28*mm, 28*mm, 32*mm, 28*mm, 24*mm, 22*mm])
            tbl.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), COL_NAVY),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ALIGN", (1, 0), (-1, -1), "CENTER"),
                ("ALIGN", (0, 0), (0, -1), "LEFT"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, COL_LIGHT]),
                ("BOX", (0, 0), (-1, -1), 0.5, COL_GRAY),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, COL_GRAY),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            elements.append(tbl)

    elements.append(Spacer(1, 6))
    weights_str = ", ".join(f"{k}={int(v*100)}%" for k, v in weights.items())
    elements.append(Paragraph(
        f"<i>Веса ансамбля: {weights_str}</i>", S["small"],
    ))
    elements.append(Spacer(1, 12))

    # --- Топ-3 предстоящих события ---
    if top_events:
        elements.append(Paragraph("📅 Ближайшие ключевые события", S["h2"]))
        ev_rows = [["Дата", "Дней", "Событие", "Консенсус", "Влияние на Cu"]]
        for ev in top_events[:5]:
            days_str = (f"+{ev.days_until}" if ev.days_until > 0
                        else "сегодня" if ev.days_until == 0
                        else f"{ev.days_until}")
            impact = ev.impact_copper or "—"
            ev_rows.append([
                str(ev.date), days_str,
                f"{ev.region} {ev.title}",
                (ev.consensus or "—")[:50],
                f"{ev.impact_arrow} {impact}",
            ])
        ev_tbl = Table(ev_rows,
                        colWidths=[22*mm, 18*mm, 60*mm, 50*mm, 30*mm])
        ev_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), COL_COPPER),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BOX", (0, 0), (-1, -1), 0.5, COL_GRAY),
            ("INNERGRID", (0, 0), (-1, -1), 0.25, COL_GRAY),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, COL_LIGHT]),
        ]))
        elements.append(ev_tbl)
        elements.append(Spacer(1, 12))

    # --- Footer / дисклеймер ---
    elements.append(Spacer(1, 16))
    elements.append(Paragraph(
        "⚠️ <b>Дисклеймер:</b> Исследовательский прототип, не торговая рекомендация. "
        "Прогноз построен на ценовых рядах и кросс-активных данных без учёта "
        "политических рисков, забастовок и фундаментальных балансов. На горизонтах >3 мес "
        "большую роль играют шоки предложения, которые модель не предсказывает.",
        S["small"],
    ))
    elements.append(Spacer(1, 6))
    elements.append(Paragraph(
        f"Источники данных: Yahoo Finance, CFTC Public Reporting, Westmetall (LME), "
        f"Google News RSS. Сгенерировано {dt.datetime.now().strftime('%Y-%m-%d %H:%M')}.",
        S["small"],
    ))

    doc.build(elements)
    pdf_bytes = buf.getvalue()
    if out_path:
        with open(out_path, "wb") as f:
            f.write(pdf_bytes)
    return pdf_bytes
