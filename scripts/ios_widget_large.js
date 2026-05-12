// ─────────────────────────────────────────────────────────────
// Portfolio Tracker — iOS Widget (Scriptable) · Large
// ─────────────────────────────────────────────────────────────

const EMAIL    = "sebastianaguilar9723@gmail.com";
const PASSWORD = "Molly2013.";
const API      = "https://portfolio-tracker-investments.onrender.com";
const KEY_TOKEN   = "pt_token";
const KEY_EXPIRES = "pt_token_exp";

// ── Palette ───────────────────────────────────────────────────
const BG    = new Color("#0b0f14");
const GOLD  = new Color("#f3a712");
const TEXT  = new Color("#e8edf5");
const MUTED = new Color("#4e6070");
const GREEN = new Color("#22c55e");
const RED   = new Color("#ef4444");
const DIM   = new Color("#e8edf5", 0.45);

// ── Auth & fetch ──────────────────────────────────────────────
async function loadJSONSafe(req) {
  const raw = await req.loadString();
  if (raw.trimStart().startsWith("<"))
    throw new Error("Servidor iniciando…");
  try { return JSON.parse(raw); }
  catch { throw new Error("Error de respuesta"); }
}

async function getToken() {
  const now = Date.now();
  if (Keychain.contains(KEY_TOKEN) && Keychain.contains(KEY_EXPIRES)) {
    if (parseInt(Keychain.get(KEY_EXPIRES), 10) > now + 60_000)
      return Keychain.get(KEY_TOKEN);
  }
  const req = new Request(`${API}/api/auth/login`);
  req.method = "POST";
  req.headers = { "Content-Type": "application/json" };
  req.body = JSON.stringify({ email: EMAIL, password: PASSWORD });
  req.timeoutInterval = 20;
  const res = await loadJSONSafe(req);
  if (!res.access_token) throw new Error("Login fallido");
  Keychain.set(KEY_TOKEN, res.access_token);
  Keychain.set(KEY_EXPIRES, String(now + 23 * 3600 * 1000));
  return res.access_token;
}

async function fetchPortfolio(token) {
  const req = new Request(`${API}/api/portfolio`);
  req.headers = { Authorization: `Bearer ${token}` };
  req.timeoutInterval = 20;
  return loadJSONSafe(req);
}

// ── Formatters ────────────────────────────────────────────────
function fmtValue(v) {
  if (v == null) return "—";
  const abs = Math.abs(v);
  if (abs >= 1_000_000) return "$" + (abs / 1_000_000).toFixed(2) + "M";
  if (abs >= 10_000)    return "$" + (abs / 1_000).toFixed(1) + "k";
  return "$" + abs.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtDelta(v) {
  if (v == null) return "—";
  const abs = Math.abs(v);
  const s = v >= 0 ? "+" : "−";
  if (abs >= 10_000) return s + "$" + (abs / 1_000).toFixed(1) + "k";
  if (abs >= 1_000)  return s + "$" + (abs / 1_000).toFixed(2) + "k";
  return s + "$" + abs.toFixed(2);
}

function fmtPct(v) {
  if (v == null) return "—";
  return (v >= 0 ? "+" : "") + v.toFixed(2) + "%";
}

// ── Summary stat column ───────────────────────────────────────
function addStatCol(parent, label, amount, pct, positive, hasData) {
  const color = hasData ? (positive ? GREEN : RED) : MUTED;
  const col = parent.addStack();
  col.layoutVertically();

  const lbl = col.addText(label);
  lbl.font = Font.boldMonospacedSystemFont(8);
  lbl.textColor = GOLD;
  lbl.textOpacity = 0.55;

  col.addSpacer(3);

  const amt = col.addText(amount);
  amt.font = Font.boldMonospacedSystemFont(13);
  amt.textColor = color;
  amt.minimumScaleFactor = 0.75;

  col.addSpacer(2);

  const p = col.addText(pct);
  p.font = Font.mediumMonospacedSystemFont(10);
  p.textColor = color;
  p.textOpacity = 0.85;
}

// ── Column widths (shared by header + data rows) ─────────────
const COL_VAL    = 72;
const COL_DAY    = 64;
const COL_RET    = 64;
const COL_GAP    = 6;

function _colStack(parent, width) {
  const s = parent.addStack();
  s.layoutHorizontally();
  s.size = new Size(width, 0);
  s.addSpacer(); // right-align content
  return s;
}

// ── Positions column headers ──────────────────────────────────
function addPosHeaders(parent) {
  const row = parent.addStack();
  row.layoutHorizontally();
  row.centerAlignContent();

  const hTkr = row.addText("TICKER");
  hTkr.font = Font.boldMonospacedSystemFont(7);
  hTkr.textColor = GOLD;
  hTkr.textOpacity = 0.45;

  row.addSpacer();

  const cVal = _colStack(row, COL_VAL);
  const hVal = cVal.addText("VALUE");
  hVal.font = Font.boldMonospacedSystemFont(7);
  hVal.textColor = GOLD;
  hVal.textOpacity = 0.45;

  row.addSpacer(COL_GAP);

  const cDay = _colStack(row, COL_DAY);
  const hDay = cDay.addText("TODAY");
  hDay.font = Font.boldMonospacedSystemFont(7);
  hDay.textColor = GOLD;
  hDay.textOpacity = 0.45;

  row.addSpacer(COL_GAP);

  const cRet = _colStack(row, COL_RET);
  const hRet = cRet.addText("RETURN");
  hRet.font = Font.boldMonospacedSystemFont(7);
  hRet.textColor = GOLD;
  hRet.textOpacity = 0.45;
}

// ── Position row ──────────────────────────────────────────────
function addPositionRow(parent, ticker, value, dayPct, totalPct, positive, hasDay) {
  const row = parent.addStack();
  row.layoutHorizontally();
  row.centerAlignContent();

  const tkr = row.addText(ticker);
  tkr.font = Font.boldMonospacedSystemFont(11);
  tkr.textColor = TEXT;
  tkr.lineLimit = 1;

  row.addSpacer();

  const cVal = _colStack(row, COL_VAL);
  const val = cVal.addText(fmtValue(value));
  val.font = Font.mediumMonospacedSystemFont(10);
  val.textColor = DIM;
  val.lineLimit = 1;

  row.addSpacer(COL_GAP);

  const dayColor = !hasDay ? MUTED : (positive ? GREEN : RED);
  const cDay = _colStack(row, COL_DAY);
  const day = cDay.addText(fmtPct(dayPct));
  day.font = Font.boldMonospacedSystemFont(10);
  day.textColor = dayColor;
  day.lineLimit = 1;

  row.addSpacer(COL_GAP);

  const totalColor = totalPct == null ? MUTED : (totalPct >= 0 ? GREEN : RED);
  const cRet = _colStack(row, COL_RET);
  const tot = cRet.addText(fmtPct(totalPct));
  tot.font = Font.mediumMonospacedSystemFont(10);
  tot.textColor = totalColor;
  tot.textOpacity = 0.75;
  tot.lineLimit = 1;
}

// ── Divider ───────────────────────────────────────────────────
function addDivider(parent) {
  const d = parent.addStack();
  d.layoutHorizontally();
  d.backgroundColor = new Color("#4e6070", 0.3);
  d.size = new Size(0, 0.7);
}

// ── Widget ────────────────────────────────────────────────────
async function buildWidget() {
  let data = null, error = null;
  try {
    data = await fetchPortfolio(await getToken());
  } catch (e) {
    error = e.message;
  }

  const w = new ListWidget();
  w.backgroundColor = BG;
  w.setPadding(14, 14, 12, 14);

  // ── Header ──
  const hRow = w.addStack();
  hRow.layoutHorizontally();
  hRow.centerAlignContent();

  const title = hRow.addText("PORTFOLIO");
  title.font = Font.boldMonospacedSystemFont(8);
  title.textColor = GOLD;
  title.textOpacity = 0.7;

  hRow.addSpacer();

  const sym = SFSymbol.named("chart.line.uptrend.xyaxis");
  sym.applyMediumWeight();
  const icon = hRow.addImage(sym.image);
  icon.imageSize = new Size(11, 11);
  icon.tintColor = GOLD;
  icon.imageOpacity = 0.45;

  w.addSpacer(5);

  // ── Error state ──
  if (error || !data) {
    const errTxt = w.addText(error || "No data");
    errTxt.font = Font.systemFont(11);
    errTxt.textColor = RED;
    errTxt.minimumScaleFactor = 0.7;
    const cold = (error || "").includes("iniciando");
    w.refreshAfterDate = new Date(Date.now() + (cold ? 30_000 : 5 * 60_000));
    return w;
  }

  // ── Compute summary values ──
  const value    = data.total_value_base ?? 0;
  const dayChg   = data.total_day_change_base ?? null;
  const invested = data.total_invested_base ?? 0;
  const pnl      = invested > 0 ? value - invested : (data.total_unrealized_pnl ?? null);
  const pnlPct   = invested > 0
    ? ((value - invested) / invested * 100)
    : (data.total_unrealized_pnl_pct ?? null);
  const dayPct   = (dayChg != null && value > 0)
    ? (dayChg / (value - dayChg) * 100)
    : null;

  // ── Main value ──
  const valTxt = w.addText(fmtValue(value));
  valTxt.font = Font.boldSystemFont(28);
  valTxt.textColor = TEXT;
  valTxt.minimumScaleFactor = 0.55;

  w.addSpacer(4);

  // ── Summary stats ──
  const summaryRow = w.addStack();
  summaryRow.layoutHorizontally();
  summaryRow.bottomAlignContent();

  addStatCol(summaryRow, "TODAY",
    fmtDelta(dayChg), fmtPct(dayPct),
    (dayChg ?? 0) >= 0, dayChg != null);

  summaryRow.addSpacer();

  addStatCol(summaryRow, "TOTAL",
    fmtDelta(pnl), fmtPct(pnlPct),
    (pnl ?? 0) >= 0, pnl != null);

  w.addSpacer(7);
  addDivider(w);
  w.addSpacer(6);

  // ── Positions header ──
  addPosHeaders(w);
  w.addSpacer(4);

  // ── Position rows ──
  const rows = (data.rows || [])
    .filter(r => r.value_base > 0)
    .sort((a, b) => b.value_base - a.value_base)
    .slice(0, 11);

  for (const pos of rows) {
    addPositionRow(
      w,
      pos.ticker,
      pos.value_base,
      pos.change_pct_1d ?? null,
      pos.unrealized_pnl_pct ?? null,
      (pos.change_pct_1d ?? 0) >= 0,
      pos.change_pct_1d != null
    );
    w.addSpacer(3);
  }

  w.addSpacer();

  // ── Timestamp ──
  const hhmm = new Date().toLocaleTimeString("es-CO", { hour: "2-digit", minute: "2-digit" });
  const ts = w.addText("↻  " + hhmm);
  ts.font = Font.systemFont(7);
  ts.textColor = MUTED;
  ts.textOpacity = 0.6;

  w.refreshAfterDate = new Date(Date.now() + 15 * 60 * 1000);
  return w;
}

// ── Run ───────────────────────────────────────────────────────
const widget = await buildWidget();
if (config.runsInWidget) {
  Script.setWidget(widget);
} else {
  widget.presentLarge();
}
Script.complete();
