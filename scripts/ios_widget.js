// ─────────────────────────────────────────────────────────────
// Portfolio Tracker — iOS Widget (Scriptable) · Small
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

// ── Stat column ───────────────────────────────────────────────
function addStatCol(parent, label, amount, pct, positive, hasData) {
  const color = hasData ? (positive ? GREEN : RED) : new Color("#4e6070");

  const col = parent.addStack();
  col.layoutVertically();

  // Label
  const lbl = col.addText(label);
  lbl.font = Font.boldMonospacedSystemFont(8);
  lbl.textColor = GOLD;
  lbl.textOpacity = 0.55;

  col.addSpacer(4);

  // Amount
  const amt = col.addText(amount);
  amt.font = Font.boldMonospacedSystemFont(13);
  amt.textColor = color;
  amt.minimumScaleFactor = 0.75;

  col.addSpacer(2);

  // Percentage
  const p = col.addText(pct);
  p.font = Font.mediumMonospacedSystemFont(10);
  p.textColor = color;
  p.textOpacity = 0.8;
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
  w.setPadding(13, 14, 11, 14);

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

  w.addSpacer(6);

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

  // ── Compute values ──
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
  valTxt.font = Font.boldSystemFont(26);
  valTxt.textColor = TEXT;
  valTxt.minimumScaleFactor = 0.55;

  w.addSpacer(8);

  // ── 2-column stats ──
  const colRow = w.addStack();
  colRow.layoutHorizontally();
  colRow.bottomAlignContent();

  addStatCol(
    colRow, "TODAY",
    fmtDelta(dayChg), fmtPct(dayPct),
    (dayChg ?? 0) >= 0, dayChg != null
  );

  colRow.addSpacer();

  addStatCol(
    colRow, "TOTAL",
    fmtDelta(pnl), fmtPct(pnlPct),
    (pnl ?? 0) >= 0, pnl != null
  );

  w.addSpacer(6);

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
  widget.presentSmall();
}
Script.complete();
