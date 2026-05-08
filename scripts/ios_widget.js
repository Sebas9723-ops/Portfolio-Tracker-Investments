// ─────────────────────────────────────────────────────────────
// Portfolio Tracker — iOS Widget (Scriptable)
// Bloomberg dark · institutional layout
//
// INSTRUCCIONES:
//   1. Instala "Scriptable" desde el App Store
//   2. Abre Scriptable → "+" → pega este script
//   3. Guarda como "Portfolio"
//   4. Pantalla inicio → pulsación larga → "+" → Scriptable → Medium
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
const MUTED = new Color("#8a9bb5");
const GREEN = new Color("#22c55e");
const RED   = new Color("#ef4444");
const LINE  = new Color("#1e2a3a");

// ── Safe JSON fetch (maneja cold start de Render) ─────────────
async function loadJSONSafe(req) {
  const raw = await req.loadString();
  if (raw.trimStart().startsWith("<"))
    throw new Error("Servidor iniciando… reintenta en 30s");
  try { return JSON.parse(raw); }
  catch { throw new Error("Respuesta inválida del servidor"); }
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
  return "$" + abs.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtDelta(v) {
  if (v == null) return "—";
  const abs = Math.abs(v);
  const s = v >= 0 ? "+" : "-";
  if (abs >= 1000) return s + "$" + (abs / 1000).toFixed(2) + "k";
  return s + "$" + abs.toFixed(2);
}

function fmtPct(v) {
  if (v == null) return "—";
  return (v >= 0 ? "+" : "") + v.toFixed(2) + "%";
}

// ── Thin divider line ─────────────────────────────────────────
function addDivider(parent) {
  const ctx = new DrawContext();
  ctx.size = new Size(300, 1);
  ctx.opaque = false;
  ctx.setFillColor(LINE);
  ctx.fillRect(new Rect(0, 0, 300, 1));
  const img = parent.addImage(ctx.getImage());
  img.imageSize = new Size(300, 1);
}

// ── Metric row ────────────────────────────────────────────────
function addMetricRow(parent, label, amount, pct, isPositive, hasData) {
  const color = hasData ? (isPositive ? GREEN : RED) : MUTED;

  const row = parent.addStack();
  row.layoutHorizontally();
  row.centerAlignContent();
  row.setPadding(6, 0, 6, 0);

  // Colored dot
  const dot = row.addText("●");
  dot.font = Font.systemFont(7);
  dot.textColor = color;

  row.addSpacer(7);

  // Label
  const lbl = row.addText(label);
  lbl.font = Font.mediumRoundedSystemFont(11);
  lbl.textColor = MUTED;

  row.addSpacer(); // push right

  // Amount
  const amtEl = row.addText(amount);
  amtEl.font = Font.mediumMonospacedSystemFont(11);
  amtEl.textColor = color;

  row.addSpacer(6);

  // Percentage
  const pctEl = row.addText(pct);
  pctEl.font = Font.boldMonospacedSystemFont(11);
  pctEl.textColor = color;
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
  w.setPadding(12, 14, 10, 14);

  // Header: PORTFOLIO + chart icon
  const hRow = w.addStack();
  hRow.layoutHorizontally();
  hRow.centerAlignContent();

  const titleTxt = hRow.addText("PORTFOLIO");
  titleTxt.font = Font.boldMonospacedSystemFont(9);
  titleTxt.textColor = GOLD;
  titleTxt.textOpacity = 0.9;

  hRow.addSpacer();

  const sym = SFSymbol.named("chart.line.uptrend.xyaxis");
  sym.applyMediumWeight();
  const symImg = hRow.addImage(sym.image);
  symImg.imageSize = new Size(13, 13);
  symImg.tintColor = GOLD;
  symImg.imageOpacity = 0.55;

  w.addSpacer(4);

  // Error state
  if (error || !data) {
    const errTxt = w.addText(error || "No data");
    errTxt.font = Font.systemFont(11);
    errTxt.textColor = RED;
    errTxt.minimumScaleFactor = 0.7;
    const cold = (error || "").includes("iniciando");
    w.refreshAfterDate = new Date(Date.now() + (cold ? 30_000 : 5 * 60_000));
    return w;
  }

  const value   = data.total_value_base ?? 0;
  const dayChg  = data.total_day_change_base ?? null;
  const invested = data.total_invested_base ?? 0;
  const pnl     = invested > 0 ? value - invested : (data.total_unrealized_pnl ?? null);
  const pnlPct  = invested > 0
    ? ((value - invested) / invested * 100)
    : (data.total_unrealized_pnl_pct ?? null);
  const dayPct  = (dayChg != null && value > 0)
    ? (dayChg / (value - dayChg) * 100)
    : null;

  // Main value
  const valTxt = w.addText(fmtValue(value));
  valTxt.font = Font.boldSystemFont(22);
  valTxt.textColor = TEXT;
  valTxt.minimumScaleFactor = 0.55;

  w.addSpacer(4);
  addDivider(w);

  addMetricRow(w, "Today",
    fmtDelta(dayChg), fmtPct(dayPct),
    (dayChg ?? 0) >= 0, dayChg != null);

  addDivider(w);

  addMetricRow(w, "Return",
    fmtDelta(pnl), fmtPct(pnlPct),
    (pnl ?? 0) >= 0, pnl != null);

  addDivider(w);
  w.addSpacer(4);

  // Timestamp
  const tsRow = w.addStack();
  tsRow.layoutHorizontally();
  tsRow.centerAlignContent();

  const clk = SFSymbol.named("clock");
  clk.applyUltraLightWeight();
  const clkImg = tsRow.addImage(clk.image);
  clkImg.imageSize = new Size(9, 9);
  clkImg.tintColor = MUTED;
  clkImg.imageOpacity = 0.5;
  tsRow.addSpacer(4);

  const hhmm = new Date().toLocaleTimeString("es-CO", { hour: "2-digit", minute: "2-digit" });
  const tsTxt = tsRow.addText(`Updated ${hhmm}`);
  tsTxt.font = Font.systemFont(8);
  tsTxt.textColor = MUTED;
  tsTxt.textOpacity = 0.55;

  w.refreshAfterDate = new Date(Date.now() + 15 * 60 * 1000);
  return w;
}

// ── Run ───────────────────────────────────────────────────────
const widget = await buildWidget();
if (config.runsInWidget) {
  Script.setWidget(widget);
} else {
  widget.presentSmall();
}
Script.complete();
