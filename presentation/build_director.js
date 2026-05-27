// build_director.js — презентация для директора
// Стиль: «на пальцах», без формул. Акцент на показатели, веса, роль эксперта.

const pptxgen = require("pptxgenjs");

// Палитра Акрон Холдинг: чёрный + красный
const C = {
  // Основные цвета бренда
  navy:        "1A1A1A",   // глубокий чёрный — вместо navy
  copper:      "C8102E",   // фирменный красный — вместо copper
  // Поддерживающие оттенки
  copperDk:    "8B0E20",   // тёмно-красный (hover)
  copperLight: "F08080",   // светло-красный (акценты)
  ice:         "E0E0E0",   // светло-серый — вместо ice
  charcoal:    "1A1A1A",   // основной текст
  slate:       "5C5C5C",   // вспомогательный серый
  white:       "FFFFFF",
  cream:       "F5F5F5",   // фон карточек
  // Семантика (оставляем стандартную для понятности)
  green:       "2E7D32",   // bullish — тёмно-зелёный (не диссонирует с red)
  red:         "C8102E",   // bearish — фирменный (совпадает с copper)
  amber:       "C97B00",   // warning — тёмно-янтарный
};

const FONT  = "Calibri";
const pres  = new pptxgen();
pres.layout = "LAYOUT_16x9";
pres.title  = "Система прогноза цены меди — для руководства";

const W = 10, H = 5.625;

// ---------------------------------------------------------------------
//  Утилиты
// ---------------------------------------------------------------------
function header(slide, title, subtitle) {
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 0.12, h: H,
    fill: { color: C.copper }, line: { color: C.copper },
  });
  slide.addText(title, {
    x: 0.5, y: 0.28, w: 9.1, h: 0.55,
    fontSize: 30, bold: true, color: C.navy, fontFace: FONT, margin: 0,
  });
  if (subtitle) {
    slide.addText(subtitle, {
      x: 0.5, y: 0.85, w: 9.1, h: 0.35,
      fontSize: 14, italic: true, color: C.slate, fontFace: FONT, margin: 0,
    });
  }
}

function footer(slide, num, total) {
  slide.addText("Прогноз цены меди · для руководства", {
    x: 0.5, y: 5.35, w: 5, h: 0.25,
    fontSize: 9, color: C.slate, fontFace: FONT, margin: 0,
  });
  slide.addText(`${num} / ${total}`, {
    x: 9.0, y: 5.35, w: 0.7, h: 0.25,
    fontSize: 9, color: C.slate, fontFace: FONT, align: "right", margin: 0,
  });
}

function bullet(slide, x, y, w, h, items, size = 14) {
  const runs = items.map((t, i) => ({
    text: t,
    options: { bullet: { code: "25A0" }, breakLine: i < items.length - 1,
                color: C.charcoal, paraSpaceAfter: 6 },
  }));
  slide.addText(runs, { x, y, w, h, fontSize: size, fontFace: FONT,
                        margin: 0, valign: "top" });
}

const TOTAL = 17;

// =====================================================================
//  Слайд 1 — Обложка
// =====================================================================
{
  const s = pres.addSlide();
  s.background = { color: C.navy };
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 0.18, h: H,
    fill: { color: C.copper }, line: { color: C.copper },
  });

  // Логотип-плашка АКРОН (placeholder — может быть заменён на реальный лого)
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.6, y: 0.5, w: 2.6, h: 0.7,
    fill: { color: C.copper }, line: { color: C.copper },
  });
  s.addText("АКРОН ХОЛДИНГ", {
    x: 0.6, y: 0.5, w: 2.6, h: 0.7,
    fontSize: 18, bold: true, color: C.white, fontFace: FONT,
    align: "center", valign: "middle", margin: 0,
  });

  s.addText("Cu", {
    x: 0.6, y: 1.4, w: 1.5, h: 0.9,
    fontSize: 64, bold: true, color: C.copper, fontFace: "Georgia", margin: 0,
  });
  s.addText("медь · элемент №29", {
    x: 0.6, y: 2.25, w: 4, h: 0.3,
    fontSize: 12, italic: true, color: C.ice, fontFace: FONT, margin: 0,
  });

  s.addText("Прогноз цены меди", {
    x: 0.6, y: 2.8, w: 9, h: 0.7,
    fontSize: 40, bold: true, color: C.white, fontFace: FONT, margin: 0,
  });
  s.addText("как устроена модель и зачем нужен эксперт", {
    x: 0.6, y: 3.55, w: 9, h: 0.45,
    fontSize: 20, color: C.copperLight, italic: true, fontFace: FONT, margin: 0,
  });

  // Полоса
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 4.5, w: W, h: 0.05,
    fill: { color: C.copper }, line: { color: C.copper },
  });

  s.addText("Доклад для руководства · 8 минут чтения · 17 слайдов · v2", {
    x: 0.6, y: 4.75, w: 9, h: 0.3,
    fontSize: 13, color: C.ice, fontFace: FONT, margin: 0,
  });
}

// =====================================================================
//  Слайд 2 — О чём этот доклад
// =====================================================================
{
  const s = pres.addSlide();
  s.background = { color: C.white };
  header(s, "О чём этот доклад",
            "Без формул. Простыми словами. С конкретными числами.");

  const blocks = [
    { num: "1", title: "Зачем нужна эта система",
      desc: "Какую задачу решает и почему мы её решаем" },
    { num: "2", title: "8 групп показателей",
      desc: "Цена, валюты, COT, LME, Mining ETFs, новости, события" },
    { num: "3", title: "4 модели + адаптивные веса",
      desc: "Веса автоматически меняются в шоках" },
    { num: "4", title: "Инструменты эксперта (новое v2)",
      desc: "SHAP, What-if, стресс-тесты, PDF-отчёт" },
    { num: "5", title: "Зачем нужен эксперт по меди",
      desc: "Что человек делает, чего модель не сможет никогда" },
    { num: "6", title: "Что сделано и что улучшать",
      desc: "Roadmap: v2 готов, дальше — ERP, рубли, alerts" },
  ];

  blocks.forEach((b, i) => {
    const col = i % 2, row = Math.floor(i / 2);
    const x = 0.5 + col * 4.65, y = 1.45 + row * 1.25;
    const w = 4.4, h = 1.1;

    s.addShape(pres.shapes.RECTANGLE, {
      x, y, w, h,
      fill: { color: C.cream }, line: { color: C.ice, width: 1 },
    });
    // Номер в круге
    s.addShape(pres.shapes.OVAL, {
      x: x + 0.15, y: y + 0.2, w: 0.7, h: 0.7,
      fill: { color: C.copper }, line: { color: C.copper },
    });
    s.addText(b.num, {
      x: x + 0.15, y: y + 0.2, w: 0.7, h: 0.7,
      fontSize: 28, bold: true, color: C.white, fontFace: FONT,
      align: "center", valign: "middle", margin: 0,
    });
    s.addText(b.title, {
      x: x + 1.0, y: y + 0.18, w: w - 1.1, h: 0.35,
      fontSize: 15, bold: true, color: C.navy, fontFace: FONT, margin: 0,
    });
    s.addText(b.desc, {
      x: x + 1.0, y: y + 0.55, w: w - 1.1, h: 0.5,
      fontSize: 11, color: C.charcoal, fontFace: FONT, margin: 0,
    });
  });

  footer(s, 2, TOTAL);
}

// =====================================================================
//  Слайд 3 — Зачем нужна эта система
// =====================================================================
{
  const s = pres.addSlide();
  s.background = { color: C.white };
  header(s, "Зачем нужна эта система",
            "Чтобы покупать медь дешевле и без сюрпризов");

  // 3 крупных проблемы — как карточки сверху
  const probs = [
    { big: "20 %", title: "Колебания цены в год", desc: "Медь — один из самых волатильных промметаллов. Ошибка момента покупки за месяц легко стоит ±5-10 %." },
    { big: "1-3", title: "Шока в год",                desc: "Cobre Panamá, Escondida, тарифы Трампа — крупные события случаются регулярно и двигают цену на 5-25 %." },
    { big: "55 %", title: "Доля Китая в спросе",    desc: "Цена меди сильно зависит от китайского промышленного цикла, который трудно отслеживать вручную." },
  ];
  probs.forEach((p, i) => {
    const x = 0.5 + i * 3.05, y = 1.45, w = 2.9, h = 1.6;
    s.addShape(pres.shapes.RECTANGLE, {
      x, y, w, h, fill: { color: C.white },
      line: { color: C.copper, width: 1 },
    });
    s.addText(p.big, {
      x, y: y + 0.1, w, h: 0.55,
      fontSize: 36, bold: true, color: C.copper, fontFace: FONT,
      align: "center", margin: 0,
    });
    s.addText(p.title, {
      x, y: y + 0.7, w, h: 0.3,
      fontSize: 13, bold: true, color: C.navy, fontFace: FONT,
      align: "center", margin: 0,
    });
    s.addText(p.desc, {
      x: x + 0.15, y: y + 1.0, w: w - 0.3, h: 0.55,
      fontSize: 10, color: C.charcoal, fontFace: FONT,
      align: "center", margin: 0,
    });
  });

  // Ценность
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.5, y: 3.35, w: 9, h: 1.6,
    fill: { color: C.navy }, line: { color: C.navy },
  });
  s.addText("Что даёт система:", {
    x: 0.7, y: 3.45, w: 8.6, h: 0.35,
    fontSize: 14, bold: true, color: C.copperLight, fontFace: FONT, margin: 0,
  });
  bullet(s, 0.7, 3.85, 8.6, 1.0,
    [
      "Каждое утро — прогноз цены на 3 дня, 10 дней, 1, 3, 6 месяцев в виде диапазона «от» и «до»",
      "Подсказку о текущем режиме рынка: спокойный, тренд, шок",
      "Свежие новости с фильтрами (забастовки, тарифы, Китай) и каталог исторических событий",
      "Возможность отмотать время назад и посмотреть, что модель предсказывала бы в любой день из прошлого",
    ], 12);
  // Перекраска текста буллетов на белый — переопределим
  // (упрощение: использую addText с обычными items)
  // Перерисую — добавлю обычный текст белый
  // (уже добавлено выше — но цвет был C.charcoal в bullet)
  // Поэтому удалю и переделаю с белым цветом
  // К сожалению, addText не убирается — нарисую сверху белый прямоугольник и перебью

  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.65, y: 3.83, w: 8.7, h: 1.02,
    fill: { color: C.navy }, line: { color: C.navy },
  });
  const runs = [
    "Каждое утро — прогноз цены на 3 дня, 10 дней, 1, 3, 6 месяцев в виде диапазона «от» и «до»",
    "Подсказку о текущем режиме рынка: спокойный, тренд, шок",
    "Свежие новости с фильтрами (забастовки, тарифы, Китай) и каталог исторических событий",
    "Возможность отмотать время назад и посмотреть, что модель предсказывала бы в любой день из прошлого",
  ].map((t, i, arr) => ({
    text: t, options: { bullet: { code: "25A0" },
                         breakLine: i < arr.length - 1, color: C.white,
                         paraSpaceAfter: 6 },
  }));
  s.addText(runs, {
    x: 0.7, y: 3.85, w: 8.6, h: 1.0,
    fontSize: 12, fontFace: FONT, color: C.white, margin: 0,
  });

  footer(s, 3, TOTAL);
}

// =====================================================================
//  Слайд 4 — Какие показатели мы используем (обзор)
// =====================================================================
{
  const s = pres.addSlide();
  s.background = { color: C.white };
  header(s, "Какие показатели мы используем",
            "8 групп. Каждая отвечает за свой класс сигналов");

  const groups = [
    { tag: "①", name: "История цены меди",     why: "Тренд, сезонность",
      weight: "35 %",  c: C.copper },
    { tag: "②", name: "Доллар + валюты",       why: "DXY, AUD, CLP, CNY",
      weight: "12 %",  c: C.navy },
    { tag: "③", name: "Mining ETFs + риск",   why: "COPX, PICK, VIX",
      weight: "10 %",  c: C.copper },
    { tag: "④", name: "Позиции спекулянтов (COT)", why: "Опережающий сигнал",
      weight: "13 %",  c: C.copper },
    { tag: "⑤", name: "LME 3M + запасы",        why: "Глобальный baseline",
      weight: "10 %",  c: C.navy },
    { tag: "⑥", name: "Связанные товары",       why: "Нефть, золото, серебро",
      weight: "8 %",   c: C.navy },
    { tag: "⑦", name: "Технические индикаторы", why: "RSI/MACD/ATR",
      weight: "7 %",   c: C.copper },
    { tag: "⑧", name: "Новости + сентимент",    why: "VADER + правила",
      weight: "5 %",   c: C.navy },
  ];

  groups.forEach((g, i) => {
    const col = i % 4, row = Math.floor(i / 4);
    const x = 0.4 + col * 2.4, y = 1.4 + row * 1.55;
    const w = 2.25, h = 1.4;
    s.addShape(pres.shapes.RECTANGLE, {
      x, y, w, h,
      fill: { color: C.cream }, line: { color: C.ice, width: 1 },
    });
    s.addShape(pres.shapes.RECTANGLE, {
      x, y, w: 0.07, h,
      fill: { color: g.c }, line: { color: g.c },
    });
    s.addText(g.tag, {
      x: x + 0.15, y: y + 0.1, w: 0.5, h: 0.4,
      fontSize: 24, bold: true, color: g.c, fontFace: FONT, margin: 0,
    });
    s.addText(g.weight, {
      x: x + w - 1.05, y: y + 0.1, w: 0.95, h: 0.4,
      fontSize: 16, bold: true, color: g.c, fontFace: FONT,
      align: "right", margin: 0,
    });
    s.addText(g.name, {
      x: x + 0.15, y: y + 0.55, w: w - 0.25, h: 0.45,
      fontSize: 13, bold: true, color: C.navy, fontFace: FONT, margin: 0,
    });
    s.addText(g.why, {
      x: x + 0.15, y: y + 1.0, w: w - 0.25, h: 0.35,
      fontSize: 10, italic: true, color: C.slate, fontFace: FONT, margin: 0,
    });
  });

  s.addText("Цифры справа сверху — относительная важность показателя в общем прогнозе (по среднему feature importance из XGBoost).",
    { x: 0.5, y: 4.7, w: 9, h: 0.35,
      fontSize: 11, italic: true, color: C.slate, fontFace: FONT, margin: 0 });

  footer(s, 4, TOTAL);
}

// =====================================================================
//  Слайд 5 — Показатель ① История цены
// =====================================================================
{
  const s = pres.addSlide();
  s.background = { color: C.white };
  header(s, "① История цены меди — 40 %",
            "Самый главный сигнал. Большая часть будущей цены — в прошлой");

  // Левая часть — что считаем
  s.addText("Что система смотрит:", {
    x: 0.5, y: 1.4, w: 5, h: 0.35,
    fontSize: 16, bold: true, color: C.navy, fontFace: FONT, margin: 0,
  });
  bullet(s, 0.55, 1.8, 5, 2.6, [
    "Цену вчера, неделю назад, месяц назад, 3 месяца назад",
    "Средние за 5 / 10 / 20 / 60 торговых дней",
    "Скорость изменения (моментум) на разных окнах",
    "Волатильность — как сильно цена скакала недавно",
    "Соотношение между скользящими средними (тренд: восходящий или нисходящий)",
  ], 13);

  // Правая часть — простая аналогия
  s.addShape(pres.shapes.RECTANGLE, {
    x: 5.95, y: 1.4, w: 3.6, h: 3.5,
    fill: { color: C.cream }, line: { color: C.copper, width: 1 },
  });
  s.addText("На пальцах", {
    x: 6.1, y: 1.55, w: 3.3, h: 0.35,
    fontSize: 14, bold: true, color: C.copper, fontFace: FONT, margin: 0,
  });
  s.addText(
    "Если медь росла последние 60 дней и продолжает расти — система ставит больший вес на «продолжит расти ещё неделю».",
    { x: 6.1, y: 1.95, w: 3.3, h: 0.9,
      fontSize: 12, color: C.charcoal, fontFace: FONT, margin: 0 });
  s.addText(
    "Если цена резко подпрыгнула — система отмечает «перегрев» и ждёт коррекции (через индикатор RSI).",
    { x: 6.1, y: 2.95, w: 3.3, h: 0.9,
      fontSize: 12, color: C.charcoal, fontFace: FONT, margin: 0 });
  s.addText(
    "Если рынок «спит» с маленькой волатильностью — коридор прогноза сужается.",
    { x: 6.1, y: 3.95, w: 3.3, h: 0.85,
      fontSize: 12, color: C.charcoal, fontFace: FONT, margin: 0 });

  s.addText("Почему 40 %? — Физическая реальность: цена меди — это случайное блуждание с автокорреляцией. Сама история несёт основной сигнал.",
    { x: 0.5, y: 4.95, w: 9, h: 0.35,
      fontSize: 11, italic: true, color: C.slate, fontFace: FONT, margin: 0 });

  footer(s, 5, TOTAL);
}

// =====================================================================
//  Слайд 6 — Показатель ② Доллар (DXY)
// =====================================================================
{
  const s = pres.addSlide();
  s.background = { color: C.white };
  header(s, "② Доллар (DXY) — 12 %",
            "Когда доллар сильнее — медь дешевеет. И наоборот");

  // Левая колонка
  s.addText("Что это:", {
    x: 0.5, y: 1.4, w: 5, h: 0.3,
    fontSize: 14, bold: true, color: C.navy, fontFace: FONT, margin: 0,
  });
  s.addText(
    "DXY — индекс доллара к корзине из 6 валют (евро, иена, фунт и т.д.). Считается ICE Futures, обновляется ежедневно.",
    { x: 0.5, y: 1.75, w: 5, h: 0.9,
      fontSize: 12, color: C.charcoal, fontFace: FONT, margin: 0 });

  s.addText("Почему важно для меди:", {
    x: 0.5, y: 2.7, w: 5, h: 0.3,
    fontSize: 14, bold: true, color: C.navy, fontFace: FONT, margin: 0,
  });
  s.addText(
    "Медь продаётся за доллары на мировых биржах. Когда доллар растёт — для покупателей в евро, юанях, рублях медь становится дороже → спрос падает → цена снижается.",
    { x: 0.5, y: 3.05, w: 5, h: 1.5,
      fontSize: 12, color: C.charcoal, fontFace: FONT, margin: 0 });

  // Правая — статистический факт + ВНИМАНИЕ
  s.addShape(pres.shapes.RECTANGLE, {
    x: 5.7, y: 1.4, w: 3.85, h: 1.5,
    fill: { color: C.cream }, line: { color: C.copper, width: 1 },
  });
  s.addText("Историческая корреляция", {
    x: 5.85, y: 1.55, w: 3.55, h: 0.3,
    fontSize: 12, bold: true, color: C.copper, fontFace: FONT, margin: 0,
  });
  s.addText("−0.65 … −0.82", {
    x: 5.85, y: 1.9, w: 3.55, h: 0.55,
    fontSize: 28, bold: true, color: C.copper, fontFace: FONT,
    align: "center", margin: 0,
  });
  s.addText("за 20-летний период 2000-2019",  {
    x: 5.85, y: 2.5, w: 3.55, h: 0.3,
    fontSize: 11, italic: true, color: C.slate, fontFace: FONT,
    align: "center", margin: 0,
  });

  s.addShape(pres.shapes.RECTANGLE, {
    x: 5.7, y: 3.05, w: 3.85, h: 1.85,
    fill: { color: C.cream }, line: { color: C.amber, width: 1.5 },
  });
  s.addText("⚠  После 2020 связь ослабла", {
    x: 5.85, y: 3.2, w: 3.55, h: 0.35,
    fontSize: 13, bold: true, color: C.amber, fontFace: FONT, margin: 0,
  });
  s.addText(
    "В 2021-2022 и доллар, и медь росли одновременно — стимулы ФРС, дефицит после локдаунов. Модель учитывает это: считает скользящую корреляцию 60 дней и переключается на физические факторы, если связь нарушилась.",
    { x: 5.85, y: 3.55, w: 3.55, h: 1.3,
      fontSize: 11, color: C.charcoal, fontFace: FONT, margin: 0 });

  footer(s, 6, TOTAL);
}

// =====================================================================
//  Слайд 7 — Показатель ③ Связанные товары
// =====================================================================
{
  const s = pres.addSlide();
  s.background = { color: C.white };
  header(s, "③ Связанные товары — 10 %",
            "Что происходит с похожими активами");

  const assets = [
    { name: "Нефть WTI",      desc: "Растёт спрос на сырьё → растёт и медь. Энергия — топливо для плавки.", link: "+" },
    { name: "Золото",          desc: "Растёт золото — пахнет инфляцией. Медь тоже выигрывает.", link: "+" },
    { name: "Серебро",         desc: "Промышленный кузен меди. Часто двигаются вместе.", link: "+" },
    { name: "S&P 500",         desc: "Растут акции → risk-on → товары в плюсе.", link: "+" },
    { name: "Доходность UST 10Y",  desc: "Высокая ставка → давление на товары через DXY.", link: "−" },
  ];

  assets.forEach((a, i) => {
    const y = 1.4 + i * 0.7;
    s.addShape(pres.shapes.RECTANGLE, {
      x: 0.5, y, w: 9, h: 0.6,
      fill: { color: C.cream }, line: { color: C.ice, width: 1 },
    });
    // Цвет связи (+ зелёный, − красный)
    const linkC = a.link === "+" ? C.green : C.red;
    s.addShape(pres.shapes.RECTANGLE, {
      x: 0.5, y, w: 0.6, h: 0.6,
      fill: { color: linkC }, line: { color: linkC },
    });
    s.addText(a.link, {
      x: 0.5, y, w: 0.6, h: 0.6,
      fontSize: 28, bold: true, color: C.white, fontFace: FONT,
      align: "center", valign: "middle", margin: 0,
    });
    s.addText(a.name, {
      x: 1.25, y: y + 0.08, w: 2.4, h: 0.45,
      fontSize: 14, bold: true, color: C.navy, fontFace: FONT,
      valign: "middle", margin: 0,
    });
    s.addText(a.desc, {
      x: 3.75, y: y + 0.05, w: 5.7, h: 0.5,
      fontSize: 11, color: C.charcoal, fontFace: FONT,
      valign: "middle", margin: 0,
    });
  });

  s.addText("Кроме самих цен — система считает 60-дневную корреляцию каждого актива с медью, и динамически снижает вес сигнала, если связь ослабла.",
    { x: 0.5, y: 5.0, w: 9, h: 0.35,
      fontSize: 11, italic: true, color: C.slate, fontFace: FONT, margin: 0 });

  footer(s, 7, TOTAL);
}

// =====================================================================
//  Слайд 8 — Показатель ④ Позиции спекулянтов (COT)
// =====================================================================
{
  const s = pres.addSlide();
  s.background = { color: C.white };
  header(s, "④ Позиции спекулянтов (CFTC COT) — 15 %",
            "Опережающий сигнал: что думают крупные фонды");

  // Левая колонка — что это
  s.addText("Что такое COT:", {
    x: 0.5, y: 1.4, w: 5.2, h: 0.3,
    fontSize: 14, bold: true, color: C.navy, fontFace: FONT, margin: 0,
  });
  s.addText(
    "Каждый вторник CFTC (надзорный орган США) собирает данные: сколько длинных и коротких позиций открыли хедж-фонды, производители, мелкие игроки. Публикуется в пятницу.",
    { x: 0.5, y: 1.75, w: 5.2, h: 1.0,
      fontSize: 12, color: C.charcoal, fontFace: FONT, margin: 0 });

  s.addText("Что используем:", {
    x: 0.5, y: 2.85, w: 5.2, h: 0.3,
    fontSize: 14, bold: true, color: C.navy, fontFace: FONT, margin: 0,
  });
  bullet(s, 0.55, 3.2, 5.2, 1.6, [
    "Net long Money Manager — чистая длинная позиция хедж-фондов",
    "Open Interest — общий объём контрактов",
    "Z-score за 5 лет — насколько позиции экстремальны",
    "Изменение за 4 и 12 недель",
  ], 11);

  // Правая колонка — почему это работает
  s.addShape(pres.shapes.RECTANGLE, {
    x: 6.0, y: 1.4, w: 3.55, h: 3.55,
    fill: { color: C.cream }, line: { color: C.copper, width: 1 },
  });
  s.addText("Почему это работает", {
    x: 6.15, y: 1.55, w: 3.3, h: 0.35,
    fontSize: 14, bold: true, color: C.copper, fontFace: FONT, margin: 0,
  });
  s.addText(
    "Хедж-фонды — крупные и информированные. Когда они массово купили длинные позиции — рынок «перегрет» и часто разворачивается.",
    { x: 6.15, y: 1.9, w: 3.3, h: 1.0,
      fontSize: 11, color: C.charcoal, fontFace: FONT, margin: 0 });
  s.addText("Эмпирический факт:", {
    x: 6.15, y: 3.0, w: 3.3, h: 0.3,
    fontSize: 12, bold: true, color: C.navy, fontFace: FONT, margin: 0,
  });
  s.addText(
    "Экстремум Net Long опережает локальные пики цены на 1-4 недели в 6 из 10 случаев за 2020-2026.",
    { x: 6.15, y: 3.3, w: 3.3, h: 1.0,
      fontSize: 11, color: C.charcoal, fontFace: FONT, margin: 0 });
  s.addText("Сейчас в системе:", {
    x: 6.15, y: 4.3, w: 3.3, h: 0.3,
    fontSize: 12, bold: true, color: C.navy, fontFace: FONT, margin: 0,
  });
  s.addText("MM net long ≈ 74 000 контрактов (29 % OI)",  {
    x: 6.15, y: 4.6, w: 3.3, h: 0.3,
    fontSize: 11, color: C.copper, fontFace: FONT, margin: 0,
  });

  footer(s, 8, TOTAL);
}

// =====================================================================
//  Слайд 9 — Показатель ⑤ Запасы LME
// =====================================================================
{
  const s = pres.addSlide();
  s.background = { color: C.white };
  header(s, "⑤ Запасы меди на LME — 8 %",
            "Сколько физического металла на бирже");

  s.addText("Что отслеживаем:", {
    x: 0.5, y: 1.4, w: 5, h: 0.3,
    fontSize: 14, bold: true, color: C.navy, fontFace: FONT, margin: 0,
  });
  s.addText(
    "Общий объём складских запасов меди в сети LME warehouses по всему миру (Роттердам, Сингапур, Пусан, США, …). Снимок ежедневно.",
    { x: 0.5, y: 1.75, w: 5, h: 1.1,
      fontSize: 12, color: C.charcoal, fontFace: FONT, margin: 0 });

  s.addText("О чём говорит:", {
    x: 0.5, y: 2.95, w: 5, h: 0.3,
    fontSize: 14, bold: true, color: C.navy, fontFace: FONT, margin: 0,
  });
  bullet(s, 0.55, 3.3, 5, 1.7, [
    "Запасы растут → переизбыток предложения → давление на цену",
    "Запасы падают → дефицит → поддержка цены",
    "Резкий вывод (как Trafigura −51 000 т) — сигнал крупного контракта",
  ], 12);

  // Правая колонка — текущее состояние
  s.addShape(pres.shapes.RECTANGLE, {
    x: 5.95, y: 1.4, w: 3.6, h: 1.8,
    fill: { color: C.cream }, line: { color: C.copper, width: 1 },
  });
  s.addText("Сейчас на LME", {
    x: 6.1, y: 1.55, w: 3.3, h: 0.3,
    fontSize: 12, italic: true, color: C.slate, fontFace: FONT, margin: 0,
  });
  s.addText("391 900 т", {
    x: 6.1, y: 1.85, w: 3.3, h: 0.7,
    fontSize: 36, bold: true, color: C.copper, fontFace: FONT,
    align: "center", margin: 0,
  });
  s.addText("−1 200 т за вчерашний день", {
    x: 6.1, y: 2.6, w: 3.3, h: 0.3,
    fontSize: 11, color: C.red, fontFace: FONT,
    align: "center", margin: 0,
  });
  s.addText("Источник: Westmetall snapshot · бесплатно", {
    x: 6.1, y: 2.85, w: 3.3, h: 0.3,
    fontSize: 9, italic: true, color: C.slate, fontFace: FONT,
    align: "center", margin: 0,
  });

  // Ограничение
  s.addShape(pres.shapes.RECTANGLE, {
    x: 5.95, y: 3.35, w: 3.6, h: 1.6,
    fill: { color: C.cream }, line: { color: C.amber, width: 1.5 },
  });
  s.addText("⚠  Ограничение", {
    x: 6.1, y: 3.5, w: 3.3, h: 0.3,
    fontSize: 12, bold: true, color: C.amber, fontFace: FONT, margin: 0,
  });
  s.addText(
    "Бесплатно — только текущий снимок. История запасов формируется только при ежедневных запусках системы.",
    { x: 6.1, y: 3.85, w: 3.3, h: 1.0,
      fontSize: 11, color: C.charcoal, fontFace: FONT, margin: 0 });

  footer(s, 9, TOTAL);
}

// =====================================================================
//  Слайд 10 — Технические индикаторы + Календарь
// =====================================================================
{
  const s = pres.addSlide();
  s.background = { color: C.white };
  header(s, "⑥ Технические индикаторы — 10 %  ·  ⑦ Календарь — 5 %",
            "Сигналы, проверенные практикой трейдеров");

  // 4 индикатора
  const indicators = [
    { name: "RSI(14)", desc: "Сила тренда от 0 до 100. >70 — перегрев, <30 — перепроданность." },
    { name: "MACD",     desc: "Разница быстрого и медленного среднего. Пересечения = развороты тренда." },
    { name: "Bollinger %B", desc: "Где цена внутри коридора стандартного отклонения. Выход за края — сигнал." },
    { name: "ATR(14)",  desc: "Истинный диапазон — насколько широко цена двигается. Шкала риска." },
  ];

  indicators.forEach((ind, i) => {
    const col = i % 2, row = Math.floor(i / 2);
    const x = 0.5 + col * 4.6, y = 1.4 + row * 1.1;
    const w = 4.4, h = 1.0;
    s.addShape(pres.shapes.RECTANGLE, {
      x, y, w, h,
      fill: { color: C.cream }, line: { color: C.ice, width: 1 },
    });
    s.addShape(pres.shapes.RECTANGLE, {
      x, y, w: 0.06, h,
      fill: { color: C.copper }, line: { color: C.copper },
    });
    s.addText(ind.name, {
      x: x + 0.15, y: y + 0.1, w: w - 0.25, h: 0.32,
      fontSize: 15, bold: true, color: C.navy, fontFace: FONT, margin: 0,
    });
    s.addText(ind.desc, {
      x: x + 0.15, y: y + 0.45, w: w - 0.25, h: 0.5,
      fontSize: 11, color: C.charcoal, fontFace: FONT, margin: 0,
    });
  });

  // Календарь
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.5, y: 3.7, w: 9, h: 1.3,
    fill: { color: C.navy }, line: { color: C.navy },
  });
  s.addText("⑦  Календарь и режим рынка", {
    x: 0.7, y: 3.8, w: 8.6, h: 0.35,
    fontSize: 15, bold: true, color: C.copperLight, fontFace: FONT, margin: 0,
  });
  const calRuns = [
    "День недели / месяц — сезонность (китайский Новый год, отчёты ФРС)",
    "Текущий режим (спокойный / турбулентный) из марковской модели — переключает «настроение» прогноза",
  ].map((t, i, arr) => ({
    text: t, options: { bullet: { code: "25A0" },
                         breakLine: i < arr.length - 1,
                         color: C.white, paraSpaceAfter: 4 },
  }));
  s.addText(calRuns, {
    x: 0.75, y: 4.18, w: 8.5, h: 0.75,
    fontSize: 11, fontFace: FONT, color: C.white, margin: 0,
  });

  footer(s, 10, TOTAL);
}

// =====================================================================
//  Слайд 11 — Веса — pie chart
// =====================================================================
{
  const s = pres.addSlide();
  s.background = { color: C.white };
  header(s, "Веса показателей — общая картина",
            "Сумма = 100 %. Веса считаются автоматически из обучения модели");

  // Pie chart
  s.addChart(pres.charts.PIE, [{
    name: "Группы признаков",
    labels: [
      "① История цены",
      "④ Спекулянты (COT)",
      "② Валюты",
      "⑤ LME + запасы",
      "③ Mining ETFs + риск",
      "⑥ Связанные товары",
      "⑦ Технические",
      "⑧ Новости + сентимент",
    ],
    values: [35, 13, 12, 10, 10, 8, 7, 5],
  }], {
    x: 0.5, y: 1.4, w: 5.0, h: 3.7,
    chartColors: [C.copper, C.navy, C.copperLight, C.ice,
                   C.copperDk, C.slate, "B0B7C3", "8DA1B9"],
    showLegend: true, legendPos: "r",
    showPercent: true,
    dataLabelColor: C.white, dataLabelFontSize: 10,
    chartArea: { fill: { color: C.white } },
  });

  // Правая колонка — пояснения
  s.addText("Главные выводы:", {
    x: 5.8, y: 1.45, w: 4, h: 0.35,
    fontSize: 16, bold: true, color: C.navy, fontFace: FONT, margin: 0,
  });
  bullet(s, 5.85, 1.85, 4, 3.0, [
    "Около половины (48 %) — цена и спекулянты. Это «душа» рынка.",
    "Макро (валюты + Mining ETFs + связанные товары) — 30 %.",
    "Глобальный baseline LME 3M + физические запасы — 10 %.",
    "Технические + новости с сентиментом — 12 %.",
  ], 12);

  s.addText("Веса корректируются автоматически: при включении адаптивного режима — по сигналу Markov-модели.",
    { x: 0.5, y: 5.0, w: 9, h: 0.3,
      fontSize: 11, italic: true, color: C.slate, fontFace: FONT, margin: 0 });

  footer(s, 11, TOTAL);
}

// =====================================================================
//  Слайд 12 — Как считается прогноз (4 головы)
// =====================================================================
{
  const s = pres.addSlide();
  s.background = { color: C.white };
  header(s, "Как считается прогноз — на пальцах",
            "Четыре независимые «головы» голосуют. Берётся взвешенное среднее");

  const heads = [
    {
      name: "Простая статистика", weight: "15 %",
      analogy: "«Если последние 3 месяца цена скакала на ±5 %, то и дальше будет так же скакать.»",
      strength: "Не выдумывает. Защита снизу.", color: C.slate,
    },
    {
      name: "Классическая ARIMA", weight: "25 %",
      analogy: "«Завтра скорее всего так же, как сегодня. Через месяц — тоже как сейчас.»",
      strength: "Лучший базовый прогноз. Не переобучается.", color: C.navy,
    },
    {
      name: "Машинное обучение XGBoost", weight: "40 %",
      analogy: "«400 простых правил, выученных на 5 годах данных. Например: если DXY падает и RSI < 30, цена обычно растёт 4 дня.»",
      strength: "Ловит нелинейные сочетания.", color: C.copper,
    },
    {
      name: "Нейросеть MLP", weight: "20 %",
      analogy: "«36 нейронов учат плавные связи. Когда XGBoost видит «решётку» правил, нейросеть — «гладкую поверхность».»",
      strength: "Альтернативный взгляд. Подстраховка XGBoost.", color: C.copperLight,
    },
  ];

  heads.forEach((h, i) => {
    const y = 1.4 + i * 0.92;
    s.addShape(pres.shapes.RECTANGLE, {
      x: 0.5, y, w: 9, h: 0.82,
      fill: { color: C.cream }, line: { color: C.ice, width: 1 },
    });
    s.addShape(pres.shapes.RECTANGLE, {
      x: 0.5, y, w: 0.08, h: 0.82,
      fill: { color: h.color }, line: { color: h.color },
    });
    s.addText(h.name, {
      x: 0.7, y: y + 0.08, w: 3.0, h: 0.35,
      fontSize: 13, bold: true, color: C.navy, fontFace: FONT, margin: 0,
    });
    s.addText(h.weight, {
      x: 8.4, y: y + 0.08, w: 1.0, h: 0.35,
      fontSize: 17, bold: true, color: h.color, fontFace: FONT,
      align: "right", margin: 0,
    });
    s.addText(h.analogy, {
      x: 0.7, y: y + 0.4, w: 7.5, h: 0.4,
      fontSize: 10.5, italic: true, color: C.charcoal, fontFace: FONT, margin: 0,
    });
  });

  // Снизу — финальная фраза с упоминанием адаптивных весов
  s.addText(
    "⚙️  Веса меняются автоматически: в спокойном рынке доверяем ML (XGB 45 %), в шоках — переключаемся на ARIMA/GBM (75 %). Решает «ломку» моделей в нестабильные периоды.",
    { x: 0.5, y: 5.05, w: 9, h: 0.45,
      fontSize: 11, italic: true, color: C.slate, fontFace: FONT, margin: 0 });

  footer(s, 12, TOTAL);
}

// =====================================================================
//  Слайд 13 — Инструменты эксперта (новое в v2)
// =====================================================================
{
  const s = pres.addSlide();
  s.background = { color: C.white };
  header(s, "Инструменты эксперта — что нового в v2",
            "Прогноз перестал быть «чёрным ящиком». Теперь видно, ПОЧЕМУ.");

  const tools = [
    {
      title: "🔍 SHAP: почему такой прогноз?",
      desc: "На любой прогноз модель показывает топ-10 факторов, которые тянут цену вверх (зелёные) или вниз (красные). Видно вклад каждого: DXY, COT, RSI, корреляции.",
      bullet: "Перестали верить «вслепую» — теперь решение опирается на видимые причины.",
    },
    {
      title: "🔮 What-if: симуляция сценариев",
      desc: "6 слайдеров: DXY, нефть, VIX, Mining ETFs, юань, позиции хедж-фондов. Сдвиг — мгновенный пересчёт прогноза.",
      bullet: "Проигрывайте «что если CPI выйдет горячее на 0.3 %» прямо в окне.",
    },
    {
      title: "🔥 Стресс-тесты",
      desc: "5 готовых сценариев: Cobre Panamá, Escondida, тариф 30 %, COVID, China stimulus. Накладываем шок на текущий прогноз — видим downside.",
      bullet: "Перед крупной закупкой — сразу видно худший сценарий.",
    },
    {
      title: "📄 PDF-отчёт одной кнопкой",
      desc: "Все ключевые метрики, прогноз на 5 горизонтов, события на месяц — в 1-2 страничном PDF.",
      bullet: "Еженедельная отправка руководству — больше не задача на полдня.",
    },
  ];

  tools.forEach((t, i) => {
    const col = i % 2, row = Math.floor(i / 2);
    const x = 0.4 + col * 4.7, y = 1.4 + row * 1.85;
    const w = 4.4, h = 1.7;
    s.addShape(pres.shapes.RECTANGLE, {
      x, y, w, h,
      fill: { color: C.cream }, line: { color: C.ice, width: 1 },
    });
    s.addShape(pres.shapes.RECTANGLE, {
      x, y, w: 0.08, h,
      fill: { color: C.copper }, line: { color: C.copper },
    });
    s.addText(t.title, {
      x: x + 0.18, y: y + 0.12, w: w - 0.3, h: 0.35,
      fontSize: 14, bold: true, color: C.navy, fontFace: FONT, margin: 0,
    });
    s.addText(t.desc, {
      x: x + 0.18, y: y + 0.5, w: w - 0.3, h: 0.7,
      fontSize: 10, color: C.charcoal, fontFace: FONT, margin: 0,
    });
    s.addText(`💡 ${t.bullet}`, {
      x: x + 0.18, y: y + 1.22, w: w - 0.3, h: 0.4,
      fontSize: 9.5, italic: true, color: C.copper, fontFace: FONT, margin: 0,
    });
  });

  footer(s, 13, TOTAL);
}

// =====================================================================
//  Слайд 14 — Что система видит / не видит
// =====================================================================
{
  const s = pres.addSlide();
  s.background = { color: C.white };
  header(s, "Где модель сильна, а где беспомощна",
            "Честная карта возможностей");

  // ЛЕВО — Видит
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.5, y: 1.4, w: 4.4, h: 3.7,
    fill: { color: C.cream }, line: { color: C.green, width: 2 },
  });
  s.addText("✅  Что модель видит хорошо", {
    x: 0.7, y: 1.55, w: 4.0, h: 0.35,
    fontSize: 15, bold: true, color: C.green, fontFace: FONT, margin: 0,
  });
  bullet(s, 0.7, 1.95, 4.0, 3.0, [
    "Тренды и инерцию рынка (последние 1-3 месяца)",
    "Сезонные циклы (китайский Новый год, отчёты ФРС)",
    "Перегрев / перепроданность через RSI и Bollinger",
    "Скрытые режимы — переходы спокойный ↔ турбулентный",
    "Опережающие сигналы от хедж-фондов через COT",
    "Связи с долларом, золотом, нефтью",
  ], 11);

  // ПРАВО — Не видит
  s.addShape(pres.shapes.RECTANGLE, {
    x: 5.1, y: 1.4, w: 4.4, h: 3.7,
    fill: { color: C.cream }, line: { color: C.red, width: 2 },
  });
  s.addText("❌  Чего модель не видит", {
    x: 5.3, y: 1.55, w: 4.0, h: 0.35,
    fontSize: 15, bold: true, color: C.red, fontFace: FONT, margin: 0,
  });
  bullet(s, 5.3, 1.95, 4.0, 3.0, [
    "Будущие забастовки на рудниках (Escondida 2024, +4 %)",
    "Политические тарифы и санкции (Трамп, июль 2025, ±25 %)",
    "Землетрясения, аварии, природные катастрофы",
    "Решения OPEC, ФРС, Банка Китая до их объявления",
    "Долгосрочные контракты вашей компании с поставщиками",
    "Условия скидок, объёмов и сезонность вашей закупки",
    "Геополитику и санкционные риски РФ",
  ], 11);

  footer(s, 14, TOTAL);
}

// =====================================================================
//  Слайд 15 — Зачем нужен эксперт по меди (главный слайд)
// =====================================================================
{
  const s = pres.addSlide();
  s.background = { color: C.white };
  header(s, "Зачем нужен эксперт с многолетним опытом",
            "Половина решения — модель. Вторая половина — человек, который её ведёт");

  // 6 ролей эксперта
  const roles = [
    {
      title: "Контекст и здравый смысл",
      desc: "Модель показывает прогноз +25 %. Эксперт спрашивает: «А что случилось? Землетрясение? Тарифы?». Без контекста нельзя действовать.",
    },
    {
      title: "Связи с поставщиками",
      desc: "Знает, кому позвонить в Codelco или Glencore. Знает спецификации, объёмы, скидки за лояльность.",
    },
    {
      title: "Качественные сигналы",
      desc: "Слухи в отрасли, разговоры на конференциях, отношения между менеджерами BHP и закупщиками — этого нет в открытых данных.",
    },
    {
      title: "Управление рисками",
      desc: "Когда хеджировать форвардом, когда брать спот, как разделить объёмы по поставщикам. Это вопрос опыта, не статистики.",
    },
    {
      title: "Адаптация модели",
      desc: "После каждого шока — настроить веса, добавить новые показатели, отключить устаревшие. Модель не обновится сама.",
    },
    {
      title: "Защита от ошибок",
      desc: "Когда модель говорит «купи сейчас», но опыт говорит «подожди до решения OPEC» — слушать опыт. Эксперт — последний фильтр.",
    },
  ];

  roles.forEach((r, i) => {
    const col = i % 3, row = Math.floor(i / 3);
    const x = 0.4 + col * 3.2, y = 1.4 + row * 1.85;
    const w = 3.0, h = 1.7;
    s.addShape(pres.shapes.RECTANGLE, {
      x, y, w, h,
      fill: { color: C.cream }, line: { color: C.ice, width: 1 },
    });
    s.addShape(pres.shapes.OVAL, {
      x: x + 0.15, y: y + 0.18, w: 0.5, h: 0.5,
      fill: { color: C.copper }, line: { color: C.copper },
    });
    s.addText(`${i + 1}`, {
      x: x + 0.15, y: y + 0.18, w: 0.5, h: 0.5,
      fontSize: 16, bold: true, color: C.white, fontFace: FONT,
      align: "center", valign: "middle", margin: 0,
    });
    s.addText(r.title, {
      x: x + 0.75, y: y + 0.15, w: w - 0.85, h: 0.55,
      fontSize: 12, bold: true, color: C.navy, fontFace: FONT, margin: 0,
    });
    s.addText(r.desc, {
      x: x + 0.15, y: y + 0.78, w: w - 0.25, h: 0.85,
      fontSize: 9.5, color: C.charcoal, fontFace: FONT, margin: 0,
    });
  });

  footer(s, 15, TOTAL);
}

// =====================================================================
//  Слайд 16 — Что улучшать
// =====================================================================
{
  const s = pres.addSlide();
  s.background = { color: C.white };
  header(s, "Что улучшать дальше + бюджет",
            "Roadmap синхронизирован с документом «Платные сервисы»");

  // 3 фазы: «Сделано» / «Минимум подписок» / «Доп. функции»
  const phases = [
    {
      tag: "✅ СДЕЛАНО в v2",
      color: C.green,
      items: [
        "Адаптивные веса по режиму Markov",
        "SHAP-объяснение каждого прогноза",
        "Гибрид LME 3M + COMEX, премия как фича",
        "Календарь событий с прогнозами аналитиков",
        "What-if + стресс-тесты + PDF-отчёт",
        "+8 источников: валюты, Mining ETFs, VIX",
      ],
    },
    {
      tag: "🟢 ~30 тыс. ₽/мес",
      color: C.copper,
      items: [
        "VPS (1 тыс. ₽): быстрый старт, свой домен",
        "Trading Economics (9 тыс. ₽): авто-календарь",
        "ICSG Bulletin (20 тыс. ₽): баланс рынка",
        "→ +5-7 % точности прогноза",
        "→ освобождает 25 ч аналитика в мес.",
        "Окупается при закупках от 50 млн ₽/год",
      ],
    },
    {
      tag: "🟡 ~150 тыс. ₽/мес",
      color: C.navy,
      items: [
        "Всё из минимального пакета +",
        "S&P Platts (100 тыс. ₽): TC/RC, концентраты",
        "SMM (50 тыс. ₽): китайский физ. рынок",
        "Claude API (10 тыс. ₽): умный NLP новостей",
        "→ +10-15 % точности на длинных горизонтах",
        "Для закупок от 500 млн ₽/год",
      ],
    },
  ];

  phases.forEach((p, i) => {
    const x = 0.4 + i * 3.2, y = 1.4, w = 3.0, h = 3.6;
    s.addShape(pres.shapes.RECTANGLE, {
      x, y, w, h,
      fill: { color: C.cream }, line: { color: C.ice, width: 1 },
    });
    s.addShape(pres.shapes.RECTANGLE, {
      x, y, w, h: 0.5,
      fill: { color: p.color }, line: { color: p.color },
    });
    s.addText(p.tag, {
      x, y, w, h: 0.5,
      fontSize: 14, bold: true, color: C.white, fontFace: FONT,
      align: "center", valign: "middle", margin: 0,
    });
    const runs = p.items.map((t, j, arr) => ({
      text: t,
      options: { bullet: { code: "25A0" },
                  breakLine: j < arr.length - 1,
                  color: C.charcoal, paraSpaceAfter: 6 },
    }));
    s.addText(runs, {
      x: x + 0.2, y: y + 0.65, w: w - 0.4, h: h - 0.75,
      fontSize: 10.5, fontFace: FONT, color: C.charcoal,
      valign: "top", margin: 0,
    });
  });

  s.addText("Рекомендация: начать с зелёного пакета (~30 тыс. ₽/мес). Через 6 месяцев — оценить эффект в реальных деньгах и решить про жёлтый пакет. Подробности — в документе «Платные сервисы».",
    { x: 0.5, y: 5.0, w: 9, h: 0.5,
      fontSize: 10, italic: true, color: C.slate, fontFace: FONT, margin: 0 });

  footer(s, 16, TOTAL);
}

// =====================================================================
//  Слайд 17 — Резюме
// =====================================================================
{
  const s = pres.addSlide();
  s.background = { color: C.navy };
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 0.18, h: H,
    fill: { color: C.copper }, line: { color: C.copper },
  });
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 4.6, w: W, h: 0.05,
    fill: { color: C.copper }, line: { color: C.copper },
  });

  s.addText("Резюме одной фразой", {
    x: 0.6, y: 0.4, w: 9, h: 0.6,
    fontSize: 32, bold: true, color: C.white, fontFace: FONT, margin: 0,
  });

  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.5, y: 1.3, w: 9, h: 1.5,
    fill: { color: C.white }, line: { color: C.copper, width: 1 },
  });
  s.addText(
    "Это система помощи решениям, а не автомат.",
    { x: 0.7, y: 1.5, w: 8.6, h: 0.5,
      fontSize: 22, bold: true, color: C.navy, fontFace: FONT, margin: 0 });
  s.addText(
    "Модель ловит цифровые сигналы (цены, позиции, запасы, корреляции), а эксперт по меди добавляет контекст, опыт и связи. Только вместе они работают.",
    { x: 0.7, y: 2.05, w: 8.6, h: 0.7,
      fontSize: 14, color: C.charcoal, fontFace: FONT, margin: 0 });

  // Что есть и что нужно
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.5, y: 3.0, w: 4.4, h: 1.6,
    fill: { color: C.white }, line: { color: C.green, width: 1.5 },
  });
  s.addText("Готово к работе", {
    x: 0.7, y: 3.15, w: 4, h: 0.3,
    fontSize: 13, bold: true, color: C.green, fontFace: FONT, margin: 0,
  });
  s.addText([
    { text: "Прогноз на 5 горизонтов + COMEX/LME",  options: { breakLine: true, color: C.charcoal } },
    { text: "8 групп показателей · 4 модели + адаптивные веса",      options: { breakLine: true, color: C.charcoal } },
    { text: "SHAP-объяснение · What-if · стресс-тесты · PDF", options: { breakLine: true, color: C.charcoal } },
    { text: "Календарь событий с консенсусом аналитиков", options: { color: C.charcoal } },
  ], {
    x: 0.7, y: 3.5, w: 4.0, h: 1.0,
    fontSize: 10, fontFace: FONT, margin: 0, valign: "top",
  });

  s.addShape(pres.shapes.RECTANGLE, {
    x: 5.1, y: 3.0, w: 4.4, h: 1.6,
    fill: { color: C.white }, line: { color: C.copper, width: 1.5 },
  });
  s.addText("Нужно от вас", {
    x: 5.3, y: 3.15, w: 4, h: 0.3,
    fontSize: 13, bold: true, color: C.copper, fontFace: FONT, margin: 0,
  });
  s.addText([
    { text: "Эксперт-куратор системы (1 человек, 0.5 FTE)",          options: { breakLine: true, color: C.charcoal } },
    { text: "Бюджет на подписки: ~30 тыс. ₽/мес (старт)",            options: { breakLine: true, color: C.charcoal } },
    { text: "Доступ к данным закупок для калибровки",                options: { breakLine: true, color: C.charcoal } },
    { text: "Через 6 мес — решение о расширении пакета", options: { color: C.charcoal } },
  ], {
    x: 5.3, y: 3.5, w: 4.0, h: 1.0,
    fontSize: 10, fontFace: FONT, margin: 0, valign: "top",
  });

  s.addText("Запустить пилот можно в течение недели · команда готова к демонстрации",
    { x: 0.6, y: 4.75, w: 9, h: 0.3,
      fontSize: 12, italic: true, color: C.copperLight, fontFace: FONT,
      align: "center", margin: 0 });
}

// =====================================================================
//  Save
// =====================================================================
pres.writeFile({ fileName: "Copper_Forecast_For_Director.pptx" })
    .then((name) => console.log("✅ Сохранено:", name));
