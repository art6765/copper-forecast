// build_pitch.js — продающая презентация для заказчика
// Тема: Copper Forecast MVP — AI-система прогноза цены меди.

const pptxgen = require("pptxgenjs");

// --- Палитра «Midnight Executive» + медный акцент ---
const C = {
  navy:    "1E2761",     // primary
  ice:     "CADCFC",     // secondary
  copper:  "B87333",     // accent — медь (тематический)
  copperLight: "E8A87C", // hover
  charcoal: "242938",    // dark text
  slate:   "5A6378",     // muted text
  white:   "FFFFFF",
  cream:   "F7F8FB",     // soft bg
  green:   "0F9D58",     // success
  red:     "D93025",     // critical
  amber:   "F4B400",     // warning
};

const FONT_TITLE = "Calibri";
const FONT_BODY  = "Calibri";

const pres = new pptxgen();
pres.layout = "LAYOUT_16x9";    // 10" × 5.625"
pres.author = "Copper Forecast MVP";
pres.title  = "Прогноз цены меди — система поддержки решений";

const W = 10, H = 5.625;

// =====================================================================
//  Утилиты — общие элементы
// =====================================================================

function addPageTitle(slide, title, subtitle) {
  // Тонкая медная полоса слева (фирменный motif)
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 0.12, h: H,
    fill: { color: C.copper }, line: { color: C.copper },
  });
  slide.addText(title, {
    x: 0.5, y: 0.3, w: 9, h: 0.55,
    fontSize: 28, bold: true, color: C.navy,
    fontFace: FONT_TITLE, margin: 0,
  });
  if (subtitle) {
    slide.addText(subtitle, {
      x: 0.5, y: 0.85, w: 9, h: 0.35,
      fontSize: 14, color: C.slate, fontFace: FONT_BODY,
      margin: 0, italic: true,
    });
  }
}

function addFooter(slide, pageNum) {
  slide.addText("Copper Forecast MVP", {
    x: 0.5, y: 5.35, w: 4, h: 0.25,
    fontSize: 9, color: C.slate, fontFace: FONT_BODY,
  });
  slide.addText(`${pageNum}`, {
    x: 9.0, y: 5.35, w: 0.7, h: 0.25,
    fontSize: 9, color: C.slate, align: "right", fontFace: FONT_BODY,
  });
}

function addStatCard(slide, x, y, w, h, value, label, color) {
  slide.addShape(pres.shapes.RECTANGLE, {
    x, y, w, h,
    fill: { color: C.white },
    line: { color: C.ice, width: 1 },
  });
  // акцентная вертикальная полоска
  slide.addShape(pres.shapes.RECTANGLE, {
    x, y, w: 0.06, h,
    fill: { color: color || C.copper }, line: { color: color || C.copper },
  });
  slide.addText(value, {
    x: x + 0.15, y: y + 0.05, w: w - 0.2, h: h * 0.55,
    fontSize: 26, bold: true, color: color || C.navy,
    fontFace: FONT_TITLE, margin: 0, valign: "top",
  });
  slide.addText(label, {
    x: x + 0.15, y: y + h * 0.55, w: w - 0.2, h: h * 0.4,
    fontSize: 10, color: C.slate, fontFace: FONT_BODY, margin: 0,
    valign: "top",
  });
}

function addBulletList(slide, x, y, w, h, items, fontSize = 14) {
  const runs = items.map((t, i) => ({
    text: t,
    options: { bullet: { code: "25A0" }, breakLine: i < items.length - 1,
                paraSpaceAfter: 6, color: C.charcoal },
  }));
  slide.addText(runs, {
    x, y, w, h, fontSize, fontFace: FONT_BODY, color: C.charcoal,
    valign: "top", margin: 0,
  });
}

// =====================================================================
//  Slide 1 — Cover
// =====================================================================
{
  const s = pres.addSlide();
  s.background = { color: C.navy };

  // Медная диагональная полоса — фирменный motif
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 4.6, w: W, h: 0.08,
    fill: { color: C.copper }, line: { color: C.copper },
  });
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 0.18, h: H,
    fill: { color: C.copper }, line: { color: C.copper },
  });

  s.addText("Cu", {
    x: 0.6, y: 0.4, w: 1.2, h: 1.0,
    fontSize: 72, bold: true, color: C.copper,
    fontFace: "Georgia", margin: 0, valign: "middle",
  });
  s.addText("№ 29 · 63,55", {
    x: 0.6, y: 1.35, w: 2.2, h: 0.3,
    fontSize: 11, color: C.ice, fontFace: FONT_BODY, margin: 0,
  });

  s.addText("Прогноз цены меди", {
    x: 0.6, y: 2.0, w: 9, h: 0.7,
    fontSize: 38, bold: true, color: C.white,
    fontFace: FONT_TITLE, margin: 0,
  });
  s.addText("AI-система поддержки решений для закупок металла", {
    x: 0.6, y: 2.75, w: 9, h: 0.45,
    fontSize: 20, color: C.ice, fontFace: FONT_BODY, margin: 0,
  });

  s.addText([
    { text: "Прогноз на 5 горизонтов · 4 модели в ансамбле · 9 источников данных", options: { breakLine: true } },
    { text: "Markov-режимы · историческая верификация · мониторинг новостей", options: {} },
  ], {
    x: 0.6, y: 3.5, w: 9, h: 0.7,
    fontSize: 14, color: C.copperLight, fontFace: FONT_BODY,
    italic: true, margin: 0,
  });

  s.addText("MVP · версия 2.0 · май 2026", {
    x: 0.6, y: 4.85, w: 5, h: 0.3,
    fontSize: 11, color: C.ice, fontFace: FONT_BODY, margin: 0,
  });
}

// =====================================================================
//  Slide 2 — Проблема
// =====================================================================
{
  const s = pres.addSlide();
  s.background = { color: C.white };
  addPageTitle(s, "Почему прогнозировать медь сложно",
                 "Высокая волатильность, нелинейные шоки, разнородные данные");

  // Большие stat-карточки
  addStatCard(s, 0.5, 1.4, 2.15, 1.4, "25-30%",  "годовая волатильность LME 3M",       C.copper);
  addStatCard(s, 2.85, 1.4, 2.15, 1.4, "−26.2%", "обвал COVID·март 2020 за месяц",      C.red);
  addStatCard(s, 5.2, 1.4, 2.15, 1.4,  "+25%",   "пик после Cobre Panamá·май 2024",     C.green);
  addStatCard(s, 7.55, 1.4, 2.0, 1.4,  "30%",   "разрыв COMEX vs LME 2025 (тарифы)",    C.amber);

  s.addText("Главные источники неопределённости:", {
    x: 0.5, y: 3.1, w: 9, h: 0.35,
    fontSize: 16, bold: true, color: C.navy, fontFace: FONT_TITLE, margin: 0,
  });

  const items = [
    "Макрорежимы. Доллар (DXY) и ставка ФРС влияют на медь, но связь нестабильна — после 2020 года классическая корреляция Cu/DXY (−0.65…−0.82) ослабла",
    "Шоки предложения. Забастовка Escondida 2024, закрытие Cobre Panamá 2023 — ±1-5% мирового выпуска за день",
    "Политика. Тарифы Трампа 2025 расширили премию COMEX-LME до 30% против исторических 0.5%",
    "Китай. ~55-60% мирового спроса, но индикаторы (Caixin PMI, кризис недвижимости) меняют значимость",
  ];
  addBulletList(s, 0.6, 3.5, 8.9, 1.7, items, 13);

  addFooter(s, 2);
}

// =====================================================================
//  Slide 3 — Решение
// =====================================================================
{
  const s = pres.addSlide();
  s.background = { color: C.white };
  addPageTitle(s, "Что делает система",
                 "Прогноз цены на 5 горизонтов с количественной оценкой неопределённости");

  // Карточки горизонтов
  const horizons = [
    { h: "3 дня",     d: "тактика" },
    { h: "10 дней",   d: "неделя+" },
    { h: "1 месяц",   d: "оперативка" },
    { h: "3 месяца",  d: "квартал" },
    { h: "6 месяцев", d: "стратегия" },
  ];
  horizons.forEach((it, i) => {
    const x = 0.5 + i * 1.85, y = 1.45, w = 1.7, hi = 1.05;
    s.addShape(pres.shapes.RECTANGLE, {
      x, y, w, h: hi,
      fill: { color: C.cream }, line: { color: C.ice, width: 1 },
    });
    s.addShape(pres.shapes.RECTANGLE, {
      x, y, w, h: 0.04,
      fill: { color: C.copper }, line: { color: C.copper },
    });
    s.addText(it.h, {
      x, y: y + 0.1, w, h: 0.5,
      fontSize: 20, bold: true, color: C.navy,
      fontFace: FONT_TITLE, align: "center", margin: 0,
    });
    s.addText(it.d, {
      x, y: y + 0.55, w, h: 0.4,
      fontSize: 11, color: C.slate, italic: true,
      fontFace: FONT_BODY, align: "center", margin: 0,
    });
  });

  // Объяснение формата прогноза
  s.addText("Каждый прогноз — это диапазон, а не одно число:", {
    x: 0.5, y: 2.75, w: 9, h: 0.35,
    fontSize: 14, bold: true, color: C.navy, fontFace: FONT_TITLE, margin: 0,
  });

  // Визуализация коридора
  const yBar = 3.35, hBar = 0.5;
  // фон коридора (p10-p90)
  s.addShape(pres.shapes.RECTANGLE, {
    x: 1.0, y: yBar, w: 8.0, h: hBar,
    fill: { color: C.ice, transparency: 30 }, line: { color: C.ice },
  });
  // плотный коридор (p25-p75)
  s.addShape(pres.shapes.RECTANGLE, {
    x: 2.5, y: yBar, w: 5.0, h: hBar,
    fill: { color: C.copper, transparency: 50 }, line: { color: C.copper },
  });
  // точка-прогноз
  s.addShape(pres.shapes.OVAL, {
    x: 4.85, y: yBar + hBar / 2 - 0.13, w: 0.26, h: 0.26,
    fill: { color: C.navy }, line: { color: C.navy },
  });
  // подписи
  s.addText("p10\n11 382", {
    x: 0.7, y: yBar + 0.55, w: 0.7, h: 0.4,
    fontSize: 10, color: C.slate, align: "center", margin: 0,
  });
  s.addText("p90\n18 722", {
    x: 8.65, y: yBar + 0.55, w: 0.7, h: 0.4,
    fontSize: 10, color: C.slate, align: "center", margin: 0,
  });
  s.addText("Точечный\n14 876 USD/т", {
    x: 4.0, y: yBar - 0.55, w: 2.0, h: 0.45,
    fontSize: 12, bold: true, color: C.navy, align: "center", margin: 0,
  });
  s.addText("← с вероятностью 80 % факт попадёт сюда (прогноз на 6 месяцев) →", {
    x: 1.0, y: yBar + 0.95, w: 8.0, h: 0.3,
    fontSize: 11, color: C.slate, italic: true, align: "center", margin: 0,
  });

  s.addText("Дополнительно: вероятность роста P(↑), направление, режим рынка, текущие новости.", {
    x: 0.5, y: 4.7, w: 9, h: 0.3,
    fontSize: 12, color: C.charcoal, fontFace: FONT_BODY, margin: 0,
  });

  addFooter(s, 3);
}

// =====================================================================
//  Slide 4 — Архитектура
// =====================================================================
{
  const s = pres.addSlide();
  s.background = { color: C.white };
  addPageTitle(s, "Архитектура решения",
                 "От рыночных данных к решению по закупке за 30 секунд");

  // 5 блоков в один ряд
  const blocks = [
    { t: "Данные",         d: "9 бесплатных источников · 5 лет истории",
      bg: C.navy, fg: C.white },
    { t: "Признаки",       d: "~85 фич: цены, COT, запасы, корреляции",
      bg: C.ice,  fg: C.navy },
    { t: "Модели",         d: "GBM + ARIMA + XGBoost + MLP",
      bg: C.copper, fg: C.white },
    { t: "Ансамбль",       d: "Взвешенное среднее в лог-пространстве",
      bg: C.ice,  fg: C.navy },
    { t: "Решение",        d: "Прогноз · режим · новости · сравнение",
      bg: C.navy, fg: C.white },
  ];
  const bx = 0.4, by = 1.5, bw = 1.78, bh = 1.6, gap = 0.05;
  blocks.forEach((b, i) => {
    const x = bx + i * (bw + gap);
    s.addShape(pres.shapes.RECTANGLE, {
      x, y: by, w: bw, h: bh,
      fill: { color: b.bg }, line: { color: b.bg },
    });
    s.addText(b.t, {
      x: x + 0.1, y: by + 0.15, w: bw - 0.2, h: 0.5,
      fontSize: 16, bold: true, color: b.fg, fontFace: FONT_TITLE,
      align: "center", margin: 0,
    });
    s.addText(b.d, {
      x: x + 0.1, y: by + 0.7, w: bw - 0.2, h: 0.8,
      fontSize: 10, color: b.fg, fontFace: FONT_BODY,
      align: "center", margin: 0, valign: "top",
    });
    // стрелка между блоками
    if (i < blocks.length - 1) {
      s.addShape(pres.shapes.LINE, {
        x: x + bw, y: by + bh / 2, w: gap, h: 0,
        line: { color: C.slate, width: 1.5, endArrowType: "triangle" },
      });
    }
  });

  // Низ — ключевые принципы
  s.addText("Ключевые принципы:", {
    x: 0.5, y: 3.4, w: 9, h: 0.35,
    fontSize: 16, bold: true, color: C.navy, fontFace: FONT_TITLE, margin: 0,
  });
  const principles = [
    "Direct multi-step forecasting — отдельная модель для каждого горизонта (более точно, чем рекурсия)",
    "Point-in-time данные — при прогнозе на дату t используются только данные ≤ t (нет look-ahead bias)",
    "Калибровка коридоров через walk-forward — реальная вероятность p10-p90 ≈ 80 %, проверена на 30 точках за 5 лет",
    "Защита от переобучения — clip MLP в ±3σ, σ-floor через историческую волатильность, авто-дроп редких фич",
  ];
  addBulletList(s, 0.6, 3.8, 8.9, 1.5, principles, 12);

  addFooter(s, 4);
}

// =====================================================================
//  Slide 5 — Источники данных
// =====================================================================
{
  const s = pres.addSlide();
  s.background = { color: C.white };
  addPageTitle(s, "Откуда поступают данные",
                 "9 источников, все бесплатные · без обязательных API-ключей");

  // Таблица источников
  const rows = [
    [
      { text: "Источник", options: { bold: true, color: C.white, fill: { color: C.navy }, valign: "middle" } },
      { text: "Что даёт", options: { bold: true, color: C.white, fill: { color: C.navy }, valign: "middle" } },
      { text: "Частота", options: { bold: true, color: C.white, fill: { color: C.navy }, valign: "middle" } },
      { text: "Доступ", options: { bold: true, color: C.white, fill: { color: C.navy }, valign: "middle" } },
    ],
    ["Yahoo Finance — HG=F",         "Цена меди COMEX (целевой ряд)",                "ежедневно",      "без ключа"],
    ["Yahoo Finance — DXY, WTI, Gold, Silver, S&P 500, US10Y", "6 кросс-активных рядов (макроконтекст)",       "ежедневно",      "без ключа"],
    ["CFTC Socrata API",             "COT positions: MM net long, OI, P/M",         "еженедельно",   "без ключа"],
    ["Westmetall",                    "LME copper stocks (snapshot)",                "ежедневно",     "без ключа"],
    ["FRED API",                     "DXY broad, ставки, CPI, IPI, FRED copper",    "ежедневно",      "FRED_API_KEY (бесплатно)"],
    ["Google News RSS",              "117 свежих новостей в день, 8 авто-тегов",    "каждые 15 мин",  "без ключа"],
    ["Каталог событий",              "24 ключевых события 2020-2026 (курируется)",  "по обновлении",  "—"],
  ];
  s.addTable(rows, {
    x: 0.4, y: 1.35, w: 9.2,
    colW: [2.8, 3.4, 1.5, 1.5],
    fontSize: 10, fontFace: FONT_BODY,
    border: { type: "solid", pt: 0.5, color: C.ice },
    rowH: 0.42, valign: "middle",
    color: C.charcoal,
    fill: { color: C.white },
  });

  // Низ — два преимущества
  const yLow = 4.5;
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.5, y: yLow, w: 4.4, h: 0.7,
    fill: { color: C.cream }, line: { color: C.copper, width: 1 },
  });
  s.addText([
    { text: "0 ₽/мес", options: { fontSize: 22, bold: true, color: C.copper, breakLine: true } },
    { text: "стоимость данных",  options: { fontSize: 11, color: C.slate } },
  ], { x: 0.65, y: yLow + 0.05, w: 4.1, h: 0.6, margin: 0, valign: "middle" });

  s.addShape(pres.shapes.RECTANGLE, {
    x: 5.1, y: yLow, w: 4.4, h: 0.7,
    fill: { color: C.cream }, line: { color: C.navy, width: 1 },
  });
  s.addText([
    { text: "5 лет · 1 326 дней", options: { fontSize: 22, bold: true, color: C.navy, breakLine: true } },
    { text: "глубина истории по умолчанию", options: { fontSize: 11, color: C.slate } },
  ], { x: 5.25, y: yLow + 0.05, w: 4.1, h: 0.6, margin: 0, valign: "middle" });

  addFooter(s, 5);
}

// =====================================================================
//  Slide 6 — Математика: обзор
// =====================================================================
{
  const s = pres.addSlide();
  s.background = { color: C.white };
  addPageTitle(s, "Математика: ансамбль из 4 моделей",
                 "Каждая модель ловит свой класс закономерностей · итог — взвешенное среднее");

  // 4 карточки с моделями
  const models = [
    {
      name: "GBM", subtitle: "Geometric Brownian Motion",
      color: C.slate,
      desc: "Стохастический baseline — медь как случайное блуждание с дрейфом",
      formula: "P_T = P_0 · exp(μ·H + ½σ²·H)",
      weight: "15 %",
    },
    {
      name: "ARIMA", subtitle: "AutoRegressive Integrated MA",
      color: C.navy,
      desc: "Классическая статистика временных рядов · окно 750 дней",
      formula: "(1−φL)(1−L)·log P = (1+θL)·ε",
      weight: "25 %",
    },
    {
      name: "XGBoost", subtitle: "Gradient Boosting Trees",
      color: C.copper,
      desc: "Машинное обучение · 85 признаков · learning_rate 0.03",
      formula: "ŷ = Σ_k f_k(x), f_k ∈ дерев. ансамбль",
      weight: "40 %",
    },
    {
      name: "MLP", subtitle: "Multi-Layer Perceptron",
      color: C.copperLight,
      desc: "Нейросеть 24-12 нейронов · clip ±3σ от выбросов",
      formula: "ŷ = W₂·ReLU(W₁·x + b₁) + b₂",
      weight: "20 %",
    },
  ];

  models.forEach((m, i) => {
    const col = i % 2, row = Math.floor(i / 2);
    const x = 0.5 + col * 4.65, y = 1.4 + row * 1.85;
    const w = 4.4, h = 1.7;
    s.addShape(pres.shapes.RECTANGLE, {
      x, y, w, h,
      fill: { color: C.white }, line: { color: C.ice, width: 1 },
    });
    s.addShape(pres.shapes.RECTANGLE, {
      x, y, w: 0.08, h,
      fill: { color: m.color }, line: { color: m.color },
    });
    // Имя + вес
    s.addText(m.name, {
      x: x + 0.2, y: y + 0.08, w: 2.5, h: 0.4,
      fontSize: 20, bold: true, color: m.color,
      fontFace: FONT_TITLE, margin: 0,
    });
    s.addText("вес " + m.weight, {
      x: x + w - 1.1, y: y + 0.1, w: 1.0, h: 0.35,
      fontSize: 11, bold: true, color: m.color,
      fontFace: FONT_BODY, align: "right", margin: 0,
    });
    s.addText(m.subtitle, {
      x: x + 0.2, y: y + 0.45, w: w - 0.3, h: 0.3,
      fontSize: 11, italic: true, color: C.slate,
      fontFace: FONT_BODY, margin: 0,
    });
    s.addText(m.desc, {
      x: x + 0.2, y: y + 0.78, w: w - 0.3, h: 0.5,
      fontSize: 11, color: C.charcoal, fontFace: FONT_BODY, margin: 0,
    });
    // Формула на лёгком фоне
    s.addShape(pres.shapes.RECTANGLE, {
      x: x + 0.2, y: y + 1.32, w: w - 0.4, h: 0.32,
      fill: { color: C.cream }, line: { color: C.cream },
    });
    s.addText(m.formula, {
      x: x + 0.25, y: y + 1.33, w: w - 0.5, h: 0.3,
      fontSize: 10, color: C.navy, fontFace: "Consolas",
      italic: true, align: "center", margin: 0,
    });
  });

  // Финальная формула ансамбля
  s.addText("Ансамбль:  μ_ens = Σ wᵢ · μᵢ / Σ wᵢ,    σ_ens = Σ wᵢ · σᵢ / Σ wᵢ", {
    x: 0.5, y: 5.1, w: 9, h: 0.3,
    fontSize: 12, color: C.navy, fontFace: "Consolas",
    italic: true, align: "center", margin: 0,
  });

  addFooter(s, 6);
}

// =====================================================================
//  Slide 7 — GBM + ARIMA глубже
// =====================================================================
{
  const s = pres.addSlide();
  s.background = { color: C.white };
  addPageTitle(s, "Модели 1-2: статистические baselines",
                 "GBM ловит волатильность · ARIMA — рассмотрение как random walk");

  // Левая колонка — GBM
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.5, y: 1.4, w: 4.4, h: 3.6,
    fill: { color: C.cream }, line: { color: C.ice, width: 1 },
  });
  s.addText("GBM", {
    x: 0.7, y: 1.55, w: 4.0, h: 0.4,
    fontSize: 22, bold: true, color: C.slate, fontFace: FONT_TITLE, margin: 0,
  });
  s.addText("Геометрическое броуновское движение", {
    x: 0.7, y: 1.95, w: 4.0, h: 0.3,
    fontSize: 11, italic: true, color: C.slate, fontFace: FONT_BODY, margin: 0,
  });
  s.addText("Допущение:", {
    x: 0.7, y: 2.35, w: 4.0, h: 0.3,
    fontSize: 12, bold: true, color: C.navy, fontFace: FONT_TITLE, margin: 0,
  });
  s.addText("Дневная лог-доходность ~ N(μ, σ²) с μ, σ из последних 60 дней", {
    x: 0.7, y: 2.6, w: 4.0, h: 0.45,
    fontSize: 11, color: C.charcoal, fontFace: FONT_BODY, margin: 0,
  });
  s.addText("Прогноз цены на H дней:", {
    x: 0.7, y: 3.15, w: 4.0, h: 0.3,
    fontSize: 12, bold: true, color: C.navy, fontFace: FONT_TITLE, margin: 0,
  });
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.7, y: 3.45, w: 4.0, h: 0.45,
    fill: { color: C.white }, line: { color: C.ice },
  });
  s.addText("P̂_T = P_0 · exp(μ·H + ½σ²·H)", {
    x: 0.75, y: 3.5, w: 3.9, h: 0.4,
    fontSize: 13, color: C.copper, fontFace: "Consolas",
    align: "center", bold: true, margin: 0,
  });
  s.addText("Коридор: квантили log-нормального распределения через Φ⁻¹(α)",  {
    x: 0.7, y: 4.0, w: 4.0, h: 0.4,
    fontSize: 11, color: C.charcoal, fontFace: FONT_BODY, margin: 0,
    italic: true,
  });
  s.addText("➤ Зачем: «sanity check», нижняя граница σ для всех ML-моделей.", {
    x: 0.7, y: 4.5, w: 4.0, h: 0.4,
    fontSize: 11, color: C.navy, fontFace: FONT_BODY, margin: 0,
    bold: true,
  });

  // Правая колонка — ARIMA
  s.addShape(pres.shapes.RECTANGLE, {
    x: 5.1, y: 1.4, w: 4.4, h: 3.6,
    fill: { color: C.cream }, line: { color: C.ice, width: 1 },
  });
  s.addText("ARIMA(1,1,1)", {
    x: 5.3, y: 1.55, w: 4.0, h: 0.4,
    fontSize: 22, bold: true, color: C.navy, fontFace: FONT_TITLE, margin: 0,
  });
  s.addText("Auto-Regressive Integrated Moving Average", {
    x: 5.3, y: 1.95, w: 4.0, h: 0.3,
    fontSize: 11, italic: true, color: C.slate, fontFace: FONT_BODY, margin: 0,
  });
  s.addText("Модель:", {
    x: 5.3, y: 2.35, w: 4.0, h: 0.3,
    fontSize: 12, bold: true, color: C.navy, fontFace: FONT_TITLE, margin: 0,
  });
  s.addShape(pres.shapes.RECTANGLE, {
    x: 5.3, y: 2.65, w: 4.0, h: 0.45,
    fill: { color: C.white }, line: { color: C.ice },
  });
  s.addText("(1 − φL)(1 − L) log P_t = (1 + θL) ε_t", {
    x: 5.35, y: 2.7, w: 3.9, h: 0.4,
    fontSize: 11, color: C.copper, fontFace: "Consolas",
    align: "center", bold: true, margin: 0,
  });
  s.addText("• AR(1) — авторегрессия первого порядка", {
    x: 5.3, y: 3.2, w: 4.0, h: 0.3,
    fontSize: 11, color: C.charcoal, fontFace: FONT_BODY, margin: 0,
  });
  s.addText("• I(1) — интегрирование (разность log-цены)", {
    x: 5.3, y: 3.5, w: 4.0, h: 0.3,
    fontSize: 11, color: C.charcoal, fontFace: FONT_BODY, margin: 0,
  });
  s.addText("• MA(1) — скользящее среднее ошибок", {
    x: 5.3, y: 3.8, w: 4.0, h: 0.3,
    fontSize: 11, color: C.charcoal, fontFace: FONT_BODY, margin: 0,
  });
  s.addText("Обучение: maximum likelihood, окно 750 дней.", {
    x: 5.3, y: 4.15, w: 4.0, h: 0.3,
    fontSize: 11, italic: true, color: C.slate, fontFace: FONT_BODY, margin: 0,
  });
  s.addText("➤ Зачем: эффективный baseline. По бэк-тесту — лучшая MAPE.", {
    x: 5.3, y: 4.5, w: 4.0, h: 0.4,
    fontSize: 11, color: C.navy, fontFace: FONT_BODY, margin: 0,
    bold: true,
  });

  addFooter(s, 7);
}

// =====================================================================
//  Slide 8 — XGBoost + MLP глубже
// =====================================================================
{
  const s = pres.addSlide();
  s.background = { color: C.white };
  addPageTitle(s, "Модели 3-4: машинное обучение",
                 "XGBoost ловит нелинейности · MLP — плавные взаимодействия фич");

  // XGBoost
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.5, y: 1.4, w: 4.4, h: 3.6,
    fill: { color: C.cream }, line: { color: C.ice, width: 1 },
  });
  s.addText("XGBoost", {
    x: 0.7, y: 1.55, w: 4.0, h: 0.4,
    fontSize: 22, bold: true, color: C.copper, fontFace: FONT_TITLE, margin: 0,
  });
  s.addText("Direct Multi-Step Gradient Boosting", {
    x: 0.7, y: 1.95, w: 4.0, h: 0.3,
    fontSize: 11, italic: true, color: C.slate, fontFace: FONT_BODY, margin: 0,
  });
  s.addText("Цель — лог-доходность за H дней:", {
    x: 0.7, y: 2.35, w: 4.0, h: 0.3,
    fontSize: 12, bold: true, color: C.navy, fontFace: FONT_TITLE, margin: 0,
  });
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.7, y: 2.65, w: 4.0, h: 0.4,
    fill: { color: C.white }, line: { color: C.ice },
  });
  s.addText("y = log(P_{t+H}) − log(P_t)", {
    x: 0.75, y: 2.7, w: 3.9, h: 0.35,
    fontSize: 12, color: C.copper, fontFace: "Consolas",
    align: "center", bold: true, margin: 0,
  });
  s.addText("Гиперпараметры (фиксированы):", {
    x: 0.7, y: 3.15, w: 4.0, h: 0.3,
    fontSize: 11, bold: true, color: C.navy, fontFace: FONT_BODY, margin: 0,
  });
  s.addText([
    { text: "n_estimators = 400", options: { breakLine: true } },
    { text: "max_depth = 4 (защита от переобучения)", options: { breakLine: true } },
    { text: "learning_rate = 0.03, L2 = 1.0", options: { breakLine: true } },
    { text: "85 признаков: цена, тех. индикаторы, COT, корреляции",   options: {} },
  ], {
    x: 0.7, y: 3.4, w: 4.0, h: 1.3,
    fontSize: 10, color: C.charcoal, fontFace: FONT_BODY,
    margin: 0,
  });
  s.addText("➤ Лучше всего ловит нелинейные взаимодействия фич.", {
    x: 0.7, y: 4.65, w: 4.0, h: 0.3,
    fontSize: 11, color: C.navy, fontFace: FONT_BODY, margin: 0,
    bold: true,
  });

  // MLP
  s.addShape(pres.shapes.RECTANGLE, {
    x: 5.1, y: 1.4, w: 4.4, h: 3.6,
    fill: { color: C.cream }, line: { color: C.ice, width: 1 },
  });
  s.addText("MLP", {
    x: 5.3, y: 1.55, w: 4.0, h: 0.4,
    fontSize: 22, bold: true, color: C.copperLight, fontFace: FONT_TITLE, margin: 0,
  });
  s.addText("Multi-Layer Perceptron (нейронная сеть)", {
    x: 5.3, y: 1.95, w: 4.0, h: 0.3,
    fontSize: 11, italic: true, color: C.slate, fontFace: FONT_BODY, margin: 0,
  });
  s.addText("Архитектура:", {
    x: 5.3, y: 2.35, w: 4.0, h: 0.3,
    fontSize: 12, bold: true, color: C.navy, fontFace: FONT_TITLE, margin: 0,
  });
  s.addText("85 → 24 (ReLU) → 12 (ReLU) → 1", {
    x: 5.3, y: 2.65, w: 4.0, h: 0.35,
    fontSize: 11, color: C.charcoal, fontFace: "Consolas", margin: 0,
  });
  s.addText("Регуляризация:", {
    x: 5.3, y: 3.05, w: 4.0, h: 0.3,
    fontSize: 12, bold: true, color: C.navy, fontFace: FONT_TITLE, margin: 0,
  });
  s.addText([
    { text: "L2 alpha = 0.05 (сильная)",                            options: { breakLine: true } },
    { text: "Early stopping (15 % validation)",                     options: { breakLine: true } },
    { text: "Clip μ_T в ±3σ горизонта (защита от выбросов)",        options: { breakLine: true } },
    { text: "StandardScaler в пайплайне",                           options: {} },
  ], {
    x: 5.3, y: 3.32, w: 4.0, h: 1.3,
    fontSize: 10, color: C.charcoal, fontFace: FONT_BODY,
    margin: 0,
  });
  s.addText("➤ Ловит плавные зависимости, которые «упускают» деревья.", {
    x: 5.3, y: 4.65, w: 4.0, h: 0.3,
    fontSize: 11, color: C.navy, fontFace: FONT_BODY, margin: 0,
    bold: true,
  });

  addFooter(s, 8);
}

// =====================================================================
//  Slide 9 — Markov-switching режимы
// =====================================================================
{
  const s = pres.addSlide();
  s.background = { color: C.white };
  addPageTitle(s, "Бонус: Markov-switching режимы",
                 "Скрытая марковская модель распознаёт, в каком режиме сейчас рынок");

  // Левая колонка — описание
  s.addText("Идея:", {
    x: 0.5, y: 1.4, w: 4.0, h: 0.35,
    fontSize: 16, bold: true, color: C.navy, fontFace: FONT_TITLE, margin: 0,
  });
  s.addText(
    "Лог-доходность r_t подчиняется одному из k скрытых режимов с разными параметрами μ_k и σ_k. Переключения — цепь Маркова первого порядка.",
    { x: 0.5, y: 1.7, w: 4.4, h: 1.0,
      fontSize: 12, color: C.charcoal, fontFace: FONT_BODY, margin: 0 }
  );
  s.addText("Формально:", {
    x: 0.5, y: 2.75, w: 4.0, h: 0.3,
    fontSize: 13, bold: true, color: C.navy, fontFace: FONT_TITLE, margin: 0,
  });
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.5, y: 3.05, w: 4.4, h: 0.45,
    fill: { color: C.cream }, line: { color: C.ice },
  });
  s.addText("r_t | S_t = k  ~  N(μ_k, σ_k²)", {
    x: 0.55, y: 3.1, w: 4.3, h: 0.4,
    fontSize: 13, color: C.copper, fontFace: "Consolas",
    align: "center", bold: true, margin: 0,
  });
  s.addText("Применение в системе:", {
    x: 0.5, y: 3.65, w: 4.4, h: 0.3,
    fontSize: 13, bold: true, color: C.navy, fontFace: FONT_TITLE, margin: 0,
  });
  addBulletList(s, 0.5, 3.95, 4.4, 1.2,
    [
      "Подсветка текущего режима в дашборде",
      "Признак для ML-моделей",
      "Адаптивное взвешивание (roadmap)",
    ], 11);

  // Правая колонка — пример параметров режимов (взято из реальных результатов)
  s.addText("Пример: k=2 на 5 годах истории меди", {
    x: 5.0, y: 1.4, w: 4.5, h: 0.35,
    fontSize: 14, bold: true, color: C.navy, fontFace: FONT_TITLE, margin: 0,
  });

  const regimeRows = [
    [
      { text: "Режим",          options: { bold: true, color: C.white, fill: { color: C.navy } } },
      { text: "μ годовая",      options: { bold: true, color: C.white, fill: { color: C.navy } } },
      { text: "σ годовая",      options: { bold: true, color: C.white, fill: { color: C.navy } } },
      { text: "P(stay)",        options: { bold: true, color: C.white, fill: { color: C.navy } } },
    ],
    [
      { text: "Calm bull",       options: { color: C.green, bold: true } },
      "+16.8 %",  "22 %",   "0.98",
    ],
    [
      { text: "Turbulent",        options: { color: C.red, bold: true } },
      "−143 %",   "74 %",   "0.66",
    ],
  ];
  s.addTable(regimeRows, {
    x: 5.0, y: 1.8, w: 4.5,
    colW: [1.5, 1.0, 1.0, 1.0],
    fontSize: 11, fontFace: FONT_BODY,
    border: { type: "solid", pt: 0.5, color: C.ice },
    rowH: 0.45, valign: "middle", align: "center",
    color: C.charcoal,
  });

  // Текущее состояние
  s.addShape(pres.shapes.RECTANGLE, {
    x: 5.0, y: 3.45, w: 4.5, h: 1.5,
    fill: { color: C.cream }, line: { color: C.green, width: 2 },
  });
  s.addText("Сейчас на рынке", {
    x: 5.15, y: 3.55, w: 4.2, h: 0.3,
    fontSize: 11, italic: true, color: C.slate, fontFace: FONT_BODY, margin: 0,
  });
  s.addText("98.9 % Calm bull", {
    x: 5.15, y: 3.85, w: 4.2, h: 0.55,
    fontSize: 24, bold: true, color: C.green, fontFace: FONT_TITLE,
    margin: 0,
  });
  s.addText("умеренный рост, низкая турбулентность", {
    x: 5.15, y: 4.45, w: 4.2, h: 0.35,
    fontSize: 11, color: C.charcoal, fontFace: FONT_BODY, margin: 0,
  });

  addFooter(s, 9);
}

// =====================================================================
//  Slide 10 — Качество прогноза (метрики бэктеста)
// =====================================================================
{
  const s = pres.addSlide();
  s.background = { color: C.white };
  addPageTitle(s, "Качество прогноза",
                 "Walk-forward валидация: 30 точек, переобучение каждые 20 дней");

  // Таблица метрик
  const rows = [
    [
      { text: "Горизонт", options: { bold: true, color: C.white, fill: { color: C.navy } } },
      { text: "Лучшая MAPE", options: { bold: true, color: C.white, fill: { color: C.navy } } },
      { text: "HitRate Ensemble", options: { bold: true, color: C.white, fill: { color: C.navy } } },
      { text: "Coverage80 %", options: { bold: true, color: C.white, fill: { color: C.navy } } },
      { text: "Комментарий", options: { bold: true, color: C.white, fill: { color: C.navy } } },
    ],
    ["3 дня",   "1.6 %",  "57 %",  "93 %",  "Прогноз близок к шуму, но коридор калиброван"],
    ["10 дней", "4.3 %",  "53 %",  "77 %",  "Шум доминирует, направление лучше монетки"],
    ["1 месяц", "5.5 %",  "60 %",  "80 %",  "Целевая зона: коридор ровно 80 %"],
    ["3 месяца","9.0 %",  "53 %",  "83 %",  "ARIMA выигрывает по MAPE"],
    ["6 месяцев","11.2 %","63 %",  "87 %",  "Лучшая направленческая точность"],
  ];
  s.addTable(rows, {
    x: 0.5, y: 1.35, w: 9.0,
    colW: [1.3, 1.3, 1.8, 1.5, 3.1],
    fontSize: 10, fontFace: FONT_BODY,
    border: { type: "solid", pt: 0.5, color: C.ice },
    rowH: 0.4, valign: "middle",
    color: C.charcoal,
    fill: { color: C.white },
  });

  // Объяснение метрик
  s.addText("Метрики, на которые стоит смотреть:", {
    x: 0.5, y: 4.0, w: 9, h: 0.3,
    fontSize: 14, bold: true, color: C.navy, fontFace: FONT_TITLE, margin: 0,
  });
  addBulletList(s, 0.6, 4.35, 8.9, 0.95, [
    "Coverage80 ≈ 80 % — корректная калибровка коридора (наша система: 77–93 %)",
    "HitRate > 50 % — система угадывает направление, и это лучше случайного предсказания",
    "MAPE — точечная ошибка; ARIMA = эффективный baseline, ML добавляет ценность по направлению",
  ], 12);

  addFooter(s, 10);
}

// =====================================================================
//  Slide 11 — Интерфейс (7 вкладок)
// =====================================================================
{
  const s = pres.addSlide();
  s.background = { color: C.white };
  addPageTitle(s, "Интерфейс пользователя",
                 "Streamlit-дашборд: 7 вкладок, открывается в браузере одной командой");

  const tabs = [
    { i: "📈", t: "Прогноз",          d: "Веер коридоров, выбор модели" },
    { i: "🌐", t: "История и макро",  d: "Скользящие корреляции, события" },
    { i: "📋", t: "COT и запасы",     d: "MM net long, LME stocks" },
    { i: "🎭", t: "Режимы",            d: "Markov-switching, текущая фаза" },
    { i: "📰", t: "Новости",           d: "RSS + каталог событий" },
    { i: "🔍", t: "Back-test",         d: "Метрики на истории" },
    { i: "📊", t: "Сырые данные",      d: "Экспорт CSV" },
  ];

  // 4+3 сетка
  tabs.forEach((tab, i) => {
    const col = i % 4, row = Math.floor(i / 4);
    const x = 0.4 + col * 2.45, y = 1.4 + row * 1.5;
    const w = 2.25, h = 1.35;
    s.addShape(pres.shapes.RECTANGLE, {
      x, y, w, h,
      fill: { color: C.cream }, line: { color: C.ice, width: 1 },
    });
    s.addShape(pres.shapes.RECTANGLE, {
      x, y, w, h: 0.05,
      fill: { color: C.copper }, line: { color: C.copper },
    });
    s.addText(tab.i, {
      x, y: y + 0.15, w, h: 0.45,
      fontSize: 26, align: "center", margin: 0,
    });
    s.addText(tab.t, {
      x, y: y + 0.65, w, h: 0.3,
      fontSize: 13, bold: true, color: C.navy,
      fontFace: FONT_TITLE, align: "center", margin: 0,
    });
    s.addText(tab.d, {
      x: x + 0.1, y: y + 0.95, w: w - 0.2, h: 0.35,
      fontSize: 9, color: C.slate, fontFace: FONT_BODY,
      align: "center", margin: 0,
    });
  });

  // Внизу — sidebar и режимы
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.5, y: 4.6, w: 9.0, h: 0.7,
    fill: { color: C.navy }, line: { color: C.navy },
  });
  s.addText([
    { text: "Sidebar: ", options: { bold: true, color: C.copperLight } },
    { text: "глубина истории · веса моделей · ", options: { color: C.ice } },
    { text: "🕰 режим времени (Сейчас / Историческая дата) ", options: { bold: true, color: C.white } },
    { text: "— перемотать модели в любую точку 5-летней истории и сравнить прогноз с фактом.",
      options: { color: C.ice } },
  ], {
    x: 0.7, y: 4.7, w: 8.6, h: 0.5,
    fontSize: 12, fontFace: FONT_BODY, margin: 0, valign: "middle",
  });

  addFooter(s, 11);
}

// =====================================================================
//  Slide 12 — Уникальные фичи
// =====================================================================
{
  const s = pres.addSlide();
  s.background = { color: C.white };
  addPageTitle(s, "Уникальные возможности",
                 "Чего нет в типовых решениях для прогноза commodities");

  const features = [
    {
      title: "Time-slider истории",
      desc: "Перематывайте время на любую дату из прошлого. Модели переобучаются на данных только до этой точки, и вы видите, что они предсказывали бы — рядом с зелёным пунктиром реальной цены.",
      example: "Пример: 12.08.2024 (накануне Escondida) — модель дала +0.4 % за 3 дня, факт +2.07 %. Видно: ML не предсказывает забастовки.",
    },
    {
      title: "Каталог событий 2020-2026",
      desc: "24 курируемых события: COVID-обвал, Cobre Panamá, Escondida, тарифы Трампа. Каждое — с типом, severity, оценочным price impact и supply impact.",
      example: "На всех графиках — вертикальные цветные линии событий. Hover показывает детали и связь с движением цены.",
    },
    {
      title: "Новости из Google News",
      desc: "Авто-классификация ~117 свежих статей в день по 8 тегам: supply_shock, policy, china, smelter, macro, structural, inventory, price_move.",
      example: "Фильтр «supply_shock» — мгновенно увидите все свежие забастовки, закрытия, землетрясения. Контекст к прогнозу за 5 секунд.",
    },
  ];

  features.forEach((f, i) => {
    const y = 1.4 + i * 1.27;
    s.addShape(pres.shapes.RECTANGLE, {
      x: 0.5, y, w: 9.0, h: 1.15,
      fill: { color: C.white }, line: { color: C.ice, width: 1 },
    });
    s.addShape(pres.shapes.RECTANGLE, {
      x: 0.5, y, w: 0.08, h: 1.15,
      fill: { color: C.copper }, line: { color: C.copper },
    });
    s.addText(f.title, {
      x: 0.7, y: y + 0.08, w: 8.7, h: 0.35,
      fontSize: 16, bold: true, color: C.navy, fontFace: FONT_TITLE,
      margin: 0,
    });
    s.addText(f.desc, {
      x: 0.7, y: y + 0.42, w: 8.7, h: 0.4,
      fontSize: 11, color: C.charcoal, fontFace: FONT_BODY, margin: 0,
    });
    s.addText(f.example, {
      x: 0.7, y: y + 0.83, w: 8.7, h: 0.3,
      fontSize: 10, color: C.copper, italic: true, fontFace: FONT_BODY,
      margin: 0,
    });
  });

  addFooter(s, 12);
}

// =====================================================================
//  Slide 13 — Что система НЕ делает (честно)
// =====================================================================
{
  const s = pres.addSlide();
  s.background = { color: C.white };
  addPageTitle(s, "Что система не делает (честно)",
                 "Управление ожиданиями — ключ к доверию");

  // 2 колонки
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.5, y: 1.4, w: 4.4, h: 3.5,
    fill: { color: C.cream }, line: { color: C.ice, width: 1 },
  });
  s.addText("Не предсказывает шоки", {
    x: 0.7, y: 1.55, w: 4.0, h: 0.4,
    fontSize: 16, bold: true, color: C.red, fontFace: FONT_TITLE,
    margin: 0,
  });
  s.addText("Никакая статистическая модель не знает заранее о забастовках, авариях, тарифах и политических решениях.", {
    x: 0.7, y: 2.0, w: 4.0, h: 0.7,
    fontSize: 11, color: C.charcoal, fontFace: FONT_BODY, margin: 0,
  });
  s.addText("Что делаем:", {
    x: 0.7, y: 2.85, w: 4.0, h: 0.3,
    fontSize: 12, bold: true, color: C.navy, fontFace: FONT_TITLE, margin: 0,
  });
  addBulletList(s, 0.7, 3.15, 4.1, 1.6, [
    "Шире коридор для длинных горизонтов",
    "Markov-режимы предупреждают о росте турбулентности",
    "Новостная лента для ручной корректировки",
    "Каталог исторических событий — учиться на прошлом",
  ], 11);

  // Правая колонка
  s.addShape(pres.shapes.RECTANGLE, {
    x: 5.1, y: 1.4, w: 4.4, h: 3.5,
    fill: { color: C.cream }, line: { color: C.ice, width: 1 },
  });
  s.addText("Не заменяет аналитика", {
    x: 5.3, y: 1.55, w: 4.0, h: 0.4,
    fontSize: 16, bold: true, color: C.amber, fontFace: FONT_TITLE,
    margin: 0,
  });
  s.addText("Прогноз — это сигнал, а не приказ. Решение остаётся за человеком, понимающим контекст.", {
    x: 5.3, y: 2.0, w: 4.0, h: 0.7,
    fontSize: 11, color: C.charcoal, fontFace: FONT_BODY, margin: 0,
  });
  s.addText("Что делаем:", {
    x: 5.3, y: 2.85, w: 4.0, h: 0.3,
    fontSize: 12, bold: true, color: C.navy, fontFace: FONT_TITLE, margin: 0,
  });
  addBulletList(s, 5.3, 3.15, 4.1, 1.6, [
    "Прозрачные метрики качества (MAPE, Coverage)",
    "4 модели — видно, согласны ли они между собой",
    "Time-slider — проверка работы на любой исторической точке",
    "Открытый код, без чёрного ящика",
  ], 11);

  s.addText("Доверие к системе строится на честности об её границах.", {
    x: 0.5, y: 5.0, w: 9, h: 0.3,
    fontSize: 13, italic: true, color: C.navy, fontFace: FONT_BODY,
    align: "center", margin: 0,
  });

  addFooter(s, 13);
}

// =====================================================================
//  Slide 14 — Технологический стек + Roadmap
// =====================================================================
{
  const s = pres.addSlide();
  s.background = { color: C.white };
  addPageTitle(s, "Технологии и развитие",
                 "Современный стек · открытые библиотеки · понятный roadmap");

  // Технологии (левая колонка)
  s.addText("Технологический стек:", {
    x: 0.5, y: 1.4, w: 4.5, h: 0.35,
    fontSize: 15, bold: true, color: C.navy, fontFace: FONT_TITLE, margin: 0,
  });
  const techRows = [
    [{ text: "Слой",   options: { bold: true, color: C.white, fill: { color: C.navy } } },
     { text: "Технология", options: { bold: true, color: C.white, fill: { color: C.navy } } }],
    ["Язык",            "Python 3.10"],
    ["Данные",          "pandas, numpy, yfinance"],
    ["Статистика",     "statsmodels"],
    ["Машинное обучение","xgboost, scikit-learn"],
    ["Интерфейс",       "streamlit, plotly"],
    ["Кэширование",     "локальный CSV + cron"],
  ];
  s.addTable(techRows, {
    x: 0.5, y: 1.75, w: 4.4,
    colW: [1.7, 2.7],
    fontSize: 11, fontFace: FONT_BODY,
    border: { type: "solid", pt: 0.5, color: C.ice },
    rowH: 0.35, valign: "middle",
    color: C.charcoal,
  });

  // Roadmap (правая колонка)
  s.addText("Roadmap развития:", {
    x: 5.1, y: 1.4, w: 4.5, h: 0.35,
    fontSize: 15, bold: true, color: C.navy, fontFace: FONT_TITLE, margin: 0,
  });

  const phases = [
    { tag: "Готово", color: C.green, items: [
      "Ансамбль 4 моделей · ансамблируемые горизонты",
      "Markov-switching · COT, LME stocks, FRED",
      "Новости из RSS · каталог событий · time-slider",
    ] },
    { tag: "Q3 2026", color: C.copper, items: [
      "LSTM / Temporal Fusion Transformer",
      "Адаптивные веса по режиму рынка",
      "NLP-сентимент новостей через BERT",
    ] },
    { tag: "Q4+", color: C.slate, items: [
      "LME COTR (отдельный COT для LME)",
      "Yangshan premium · ICSG monthly bulletin",
      "Прогнозы цен в RUB через интеграцию с ЦБ",
    ] },
  ];

  let yPhase = 1.78;
  phases.forEach((p) => {
    s.addShape(pres.shapes.RECTANGLE, {
      x: 5.1, y: yPhase, w: 0.8, h: 0.3,
      fill: { color: p.color }, line: { color: p.color },
    });
    s.addText(p.tag, {
      x: 5.15, y: yPhase, w: 0.75, h: 0.3,
      fontSize: 10, bold: true, color: C.white, fontFace: FONT_BODY,
      align: "center", valign: "middle", margin: 0,
    });
    s.addText(p.items.map((t, i) => ({
      text: t,
      options: { bullet: { code: "25A0" }, breakLine: i < p.items.length - 1,
                  color: C.charcoal, paraSpaceAfter: 2 },
    })), {
      x: 6.0, y: yPhase - 0.05, w: 3.5, h: 1.0,
      fontSize: 10, fontFace: FONT_BODY, margin: 0,
    });
    yPhase += 1.05;
  });

  addFooter(s, 14);
}

// =====================================================================
//  Slide 15 — Резюме
// =====================================================================
{
  const s = pres.addSlide();
  s.background = { color: C.navy };
  // Медные акценты
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 0.18, h: H,
    fill: { color: C.copper }, line: { color: C.copper },
  });
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 4.6, w: W, h: 0.08,
    fill: { color: C.copper }, line: { color: C.copper },
  });

  s.addText("Резюме", {
    x: 0.6, y: 0.4, w: 9, h: 0.6,
    fontSize: 36, bold: true, color: C.white, fontFace: FONT_TITLE,
    margin: 0,
  });

  // 3 столбца с ключевыми сообщениями
  const messages = [
    {
      big: "0 ₽",
      title: "Стоимость данных",
      desc: "9 источников, все бесплатные. Никаких подписок Bloomberg / Refinitiv.",
    },
    {
      big: "5 лет",
      title: "История + ансамбль",
      desc: "1 326 дней данных. 4 модели разной природы. Точечный прогноз + калиброванный коридор.",
    },
    {
      big: "30 сек",
      title: "От запроса до прогноза",
      desc: "Одна команда `streamlit run app.py`. Полный прогноз на 5 горизонтов в браузере.",
    },
  ];
  messages.forEach((m, i) => {
    const x = 0.5 + i * 3.05, y = 1.4, w = 2.9, h = 2.0;
    s.addShape(pres.shapes.RECTANGLE, {
      x, y, w, h,
      fill: { color: C.white }, line: { color: C.copper, width: 1 },
    });
    s.addText(m.big, {
      x, y: y + 0.15, w, h: 0.8,
      fontSize: 48, bold: true, color: C.copper, fontFace: FONT_TITLE,
      align: "center", margin: 0,
    });
    s.addText(m.title, {
      x, y: y + 1.0, w, h: 0.35,
      fontSize: 14, bold: true, color: C.navy, fontFace: FONT_TITLE,
      align: "center", margin: 0,
    });
    s.addText(m.desc, {
      x: x + 0.15, y: y + 1.35, w: w - 0.3, h: 0.6,
      fontSize: 10, color: C.charcoal, fontFace: FONT_BODY,
      align: "center", margin: 0,
    });
  });

  // Финальный call to action
  s.addText("Следующий шаг", {
    x: 0.5, y: 3.7, w: 9, h: 0.35,
    fontSize: 16, bold: true, color: C.copperLight, fontFace: FONT_TITLE,
    align: "center", margin: 0,
  });
  s.addText("Запустить пилот на ваших данных закупок · валидация на 6 месяцев · интеграция с ERP", {
    x: 0.5, y: 4.05, w: 9, h: 0.4,
    fontSize: 14, color: C.ice, fontFace: FONT_BODY,
    align: "center", margin: 0,
  });

  s.addText("MVP готов к демонстрации сегодня · streamlit run app.py", {
    x: 0.5, y: 4.85, w: 9, h: 0.3,
    fontSize: 11, italic: true, color: C.copperLight, fontFace: FONT_BODY,
    align: "center", margin: 0,
  });
}

// =====================================================================
//  Save
// =====================================================================
pres.writeFile({ fileName: "Copper_Forecast_Pitch.pptx" }).then((name) => {
  console.log("✅ Сохранено:", name);
});
