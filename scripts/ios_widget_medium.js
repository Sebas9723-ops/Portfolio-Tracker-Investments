// ─────────────────────────────────────────────────────────────
// Portfolio Tracker — iOS Widget (Scriptable) · Medium
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

// ── Compact stat block (label · amount · pct in one line) ─────
function addCompactStat(parent, label, amount, pct, positive, hasData) {
  const color = hasData ? (positive ? GREEN : RED) : MUTED;

  const col = parent.addStack();
  col.layoutVertically();

  const lbl = col.addText(label);
  lbl.font = Font.boldMonospacedSystemFont(7);
  lbl.textColor = GOLD;
  lbl.textOpacity = 0.5;

  col.addSpacer(2);

  const amt = col.addText(amount);
  amt.font = Font.boldMonospacedSystemFont(11);
  amt.textColor = color;
  amt.minimumScaleFactor = 0.8;

  col.addSpacer(1);

  const p = col.addText(pct);
  p.font = Font.mediumMonospacedSystemFont(9);
  p.textColor = color;
  p.textOpacity = 0.85;
}

// ── Position row ──────────────────────────────────────────────
function addPositionRow(parent, ticker, value, dayPct, totalPct, positive, hasDay) {
  const row = parent.addStack();
  row.layoutHorizontally();
  row.centerAlignContent();

  const tkr = row.addText(ticker);
  tkr.font = Font.boldMonospacedSystemFont(10);
  tkr.textColor = TEXT;
  tkr.lineLimit = 1;

  row.addSpacer();

  const val = row.addText(fmtValue(value));
  val.font = Font.mediumMonospacedSystemFont(9);
  val.textColor = DIM;
  val.lineLimit = 1;

  row.addSpacer(8);

  const dayColor = !hasDay ? MUTED : (positive ? GREEN : RED);
  const day = row.addText(fmtPct(dayPct));
  day.font = Font.boldMonospacedSystemFont(10);
  day.textColor = dayColor;
  day.lineLimit = 1;
  day.minimumScaleFactor = 0.8;

  row.addSpacer(8);

  const totalColor = totalPct == null ? MUTED : (totalPct >= 0 ? GREEN : RED);
  const tot = row.addText(fmtPct(totalPct));
  tot.font = Font.mediumMonospacedSystemFont(9);
  tot.textColor = totalColor;
  tot.textOpacity = 0.75;
  tot.lineLimit = 1;
  tot.minimumScaleFactor = 0.8;
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
  w.setPadding(11, 13, 10, 13);

  // ── Header ──
  const hRow = w.addStack();
  hRow.layoutHorizontally();
  hRow.centerAlignContent();

  const title = hRow.addText("PORTFOLIO");
  title.font = Font.boldMonospacedSystemFont(7);
  title.textColor = GOLD;
  title.textOpacity = 0.7;

  hRow.addSpacer();

  const sym = SFSymbol.named("chart.line.uptrend.xyaxis");
  sym.applyMediumWeight();
  const icon = hRow.addImage(sym.image);
  icon.imageSize = new Size(10, 10);
  icon.tintColor = GOLD;
  icon.imageOpacity = 0.45;

  w.addSpacer(3);

  // ── Error state ──
  if (error || !data) {
    const errTxt = w.addText(error || "No data");
    errTxt.font = Font.systemFont(10);
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
  valTxt.font = Font.boldSystemFont(22);
  valTxt.textColor = TEXT;
  valTxt.minimumScaleFactor = 0.6;

  w.addSpacer(4);

  // ── Summary stats (side by side) ──
  const statsRow = w.addStack();
  statsRow.layoutHorizontally();
  statsRow.bottomAlignContent();

  addCompactStat(statsRow, "TODAY",
    fmtDelta(dayChg), fmtPct(dayPct),
    (dayChg ?? 0) >= 0, dayChg != null);

  statsRow.addSpacer();

  addCompactStat(statsRow, "TOTAL",
    fmtDelta(pnl), fmtPct(pnlPct),
    (pnl ?? 0) >= 0, pnl != null);

  w.addSpacer(7);
  addDivider(w);
  w.addSpacer(5);

  // ── Column headers ──
  const posHeader = w.addStack();
  posHeader.layoutHorizontally();

  const hTicker = posHeader.addText("TICKER");
  hTicker.font = Font.boldMonospacedSystemFont(6);
  hTicker.textColor = GOLD;
  hTicker.textOpacity = 0.4;

  posHeader.addSpacer();

  const hValue = posHeader.addText("VALUE");
  hValue.font = Font.boldMonospacedSystemFont(6);
  hValue.textColor = GOLD;
  hValue.textOpacity = 0.4;

  posHeader.addSpacer(8);

  const hDay = posHeader.addText("TODAY");
  hDay.font = Font.boldMonospacedSystemFont(6);
  hDay.textColor = GOLD;
  hDay.textOpacity = 0.4;

  posHeader.addSpacer(8);

  const hTotal = posHeader.addText("RETURN");
  hTotal.font = Font.boldMonospacedSystemFont(6);
  hTotal.textColor = GOLD;
  hTotal.textOpacity = 0.4;

  w.addSpacer(4);

  // ── Position rows (top 4) ──
  const rows = (data.rows || [])
    .filter(r => r.value_base > 0)
    .sort((a, b) => b.value_base - a.value_base)
    .slice(0, 4);

  for (let i = 0; i < rows.length; i++) {
    const pos = rows[i];
    addPositionRow(
      w,
      pos.ticker,
      pos.value_base,
      pos.change_pct_1d ?? null,
      pos.unrealized_pnl_pct ?? null,
      (pos.change_pct_1d ?? 0) >= 0,
      pos.change_pct_1d != null
    );
    if (i < rows.length - 1) w.addSpacer(4);
  }

  w.addSpacer();

  // ── Timestamp ──
  const hhmm = new Date().toLocaleTimeString("es-CO", { hour: "2-digit", minute: "2-digit" });
  const ts = w.addText("↻  " + hhmm);
  ts.font = Font.systemFont(6);
  ts.textColor = MUTED;
  ts.textOpacity = 0.55;

  w.refreshAfterDate = new Date(Date.now() + 15 * 60 * 1000);
  return w;
}

// ── Run ───────────────────────────────────────────────────────
const widget = await buildWidget();
if (config.runsInWidget) {
  Script.setWidget(widget);
} else {
  widget.presentMedium();
}
Script.complete();
