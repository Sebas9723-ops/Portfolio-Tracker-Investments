// Portfolio Tracker — iOS Widget (Scriptable)
// Shows: sparkline · total value · today · return
//
// SETUP:
//   1. Install "Scriptable" from the App Store (free)
//   2. Open Scriptable → "+" → paste this entire script
//   3. Save as "Portfolio"
//   4. Add Scriptable widget to Home Screen → Small size

const EMAIL    = "sebastianaguilar9723@gmail.com";
const PASSWORD = "Molly2013.";
const API      = "https://portfolio-tracker-investments.onrender.com";

const KEY_TOKEN   = "pt_token";
const KEY_EXPIRES = "pt_token_exp";
const TIMEOUT_MS  = 55000;

// ── Colors (dark, matches Mac widget) ────────────────────────

const C = {
  bg:      new Color("#1c1c1e"),
  text:    new Color("#ffffff"),
  muted:   new Color("#8e8e93"),
  pill:    new Color("#2c2c2e"),
  green:   new Color("#4ade80"),
  red:     new Color("#f87171"),
  chart:   new Color("#3a3a3c"),
};

// ── Auth ─────────────────────────────────────────────────────

async function getToken() {
  const now = Date.now();
  if (Keychain.contains(KEY_TOKEN) && Keychain.contains(KEY_EXPIRES)) {
    const exp = parseInt(Keychain.get(KEY_EXPIRES), 10);
    if (exp > now + 60_000) return Keychain.get(KEY_TOKEN);
  }
  const req = new Request(`${API}/api/auth/login`);
  req.method = "POST";
  req.headers = { "Content-Type": "application/json" };
  req.body = JSON.stringify({ email: EMAIL, password: PASSWORD });
  req.timeoutInterval = TIMEOUT_MS / 1000;
  const raw = await req.loadString();
  const res = JSON.parse(raw);
  if (!res || !res.access_token) throw new Error(res?.detail || "Login failed");
  const exp = now + 23 * 3600 * 1000;
  Keychain.set(KEY_TOKEN, res.access_token);
  Keychain.set(KEY_EXPIRES, String(exp));
  return res.access_token;
}

// ── Fetch ─────────────────────────────────────────────────────

async function fetchPortfolio(token) {
  const req = new Request(`${API}/api/portfolio`);
  req.headers = { Authorization: `Bearer ${token}` };
  req.timeoutInterval = TIMEOUT_MS / 1000;
  const raw = await req.loadString();
  return JSON.parse(raw);
}

async function fetchHistory(token) {
  const start = new Date();
  start.setDate(start.getDate() - 30);
  const startStr = start.toISOString().split("T")[0];
  const req = new Request(`${API}/api/portfolio/history?start=${startStr}`);
  req.headers = { Authorization: `Bearer ${token}` };
  req.timeoutInterval = TIMEOUT_MS / 1000;
  try {
    const raw = await req.loadString();
    const res = JSON.parse(raw);
    return Array.isArray(res) ? res : [];
  } catch (_) { return []; }
}

// ── Format ────────────────────────────────────────────────────

function fmtUSD(v) {
  if (v == null) return "—";
  const neg = v < 0 ? "-" : "";
  return `${neg}$${Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function fmtPct(v) {
  if (v == null) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;
}

function sgn(v) { return v >= 0 ? "+" : ""; }

// ── Sparkline ─────────────────────────────────────────────────

function drawSparkline(points, color) {
  const S = 44, pad = 8;
  const ctx = new DrawContext();
  ctx.size = new Size(S, S);
  ctx.opaque = false;
  ctx.respectScreenScale = true;

  // Circle bg
  const bg = new Path();
  bg.addEllipse(new Rect(0, 0, S, S));
  ctx.addPath(bg);
  ctx.setFillColor(C.chart);
  ctx.fillPath();

  if (!points || points.length < 2) return ctx.getImage();

  const vals = points.map(p => p.value);
  const mn = Math.min(...vals), mx = Math.max(...vals), rng = mx - mn || 1;
  const w = S - 2 * pad, h = S - 2 * pad;

  const line = new Path();
  vals.forEach((v, i) => {
    const x = pad + (i / (vals.length - 1)) * w;
    const y = pad + (1 - (v - mn) / rng) * h;
    if (i === 0) line.move(new Point(x, y));
    else         line.addLine(new Point(x, y));
  });
  ctx.addPath(line);
  ctx.setStrokeColor(color);
  ctx.setLineWidth(2);
  ctx.strokePath();

  return ctx.getImage();
}

// ── Widget ────────────────────────────────────────────────────

async function buildWidget() {
  let data = null, history = [], error = null;

  try {
    const token = await getToken();
    data    = await fetchPortfolio(token);
    history = await fetchHistory(token);
    if (!data || (data.total_value_base == null && (!data.rows || !data.rows.length))) {
      error = "No data";
    }
  } catch (e) {
    error = e.message || "Connection error";
  }

  const w = new ListWidget();
  w.backgroundColor = C.bg;
  w.setPadding(14, 14, 14, 14);

  if (error || !data) {
    const e = w.addText("⚠️ " + (error || "No data"));
    e.font = Font.mediumSystemFont(11);
    e.textColor = C.red;
    e.lineLimit = 3;
    return w;
  }

  const value    = data.total_value_base ?? 0;
  const dayChg   = data.total_day_change_base ?? null;
  const invested = data.total_invested_base ?? 0;
  const pnl      = invested > 0 ? value - invested : null;
  const pnlPct   = invested > 0 ? ((value - invested) / invested * 100) : null;
  const dayPct   = (dayChg != null && value > 0) ? (dayChg / (value - dayChg) * 100) : null;
  const isUp     = dayChg == null || dayChg >= 0;
  const pnlUp    = pnl == null || pnl >= 0;
  const lineColor = pnlUp ? C.green : C.red;

  // ── Header: "Portfolio"  time  [chart] ──
  const hdr = w.addStack();
  hdr.layoutHorizontally();
  hdr.centerAlignContent();

  const title = hdr.addText("Portfolio");
  title.font = Font.boldSystemFont(11);
  title.textColor = C.text;
  title.lineLimit = 1;

  hdr.addSpacer(null);

  const now  = new Date();
  const hhmm = now.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" });
  const tsLabel = hdr.addText(hhmm);
  tsLabel.font = Font.systemFont(9);
  tsLabel.textColor = C.muted;
  tsLabel.textOpacity = 0.7;

  hdr.addSpacer(6);

  const sparkImg = drawSparkline(history, lineColor);
  const badge = hdr.addImage(sparkImg);
  badge.imageSize = new Size(26, 26);

  w.addSpacer(6);

  // ── Value ──
  const valTxt = w.addText(fmtUSD(value));
  valTxt.font = Font.boldSystemFont(26);
  valTxt.textColor = C.text;
  valTxt.minimumScaleFactor = 0.6;

  w.addSpacer(8);

  // ── Pills row ──
  const pills = w.addStack();
  pills.layoutHorizontally();
  pills.spacing = 6;

  function addPill(stack, label, usd, pct, color) {
    const pill = stack.addStack();
    pill.layoutVertically();
    pill.backgroundColor = C.pill;
    pill.cornerRadius = 8;
    pill.setPadding(6, 8, 6, 8);

    const lbl = pill.addText(label);
    lbl.font = Font.semiboldSystemFont(7);
    lbl.textColor = C.muted;

    const usdTxt = pill.addText(usd);
    usdTxt.font = Font.semiboldSystemFont(12);
    usdTxt.textColor = color;

    const pctTxt = pill.addText(pct);
    pctTxt.font = Font.mediumSystemFont(10);
    pctTxt.textColor = color;
  }

  addPill(pills, "TODAY",
    dayChg != null ? `${sgn(dayChg)}${fmtUSD(dayChg)}` : "—",
    fmtPct(dayPct),
    isUp ? C.green : C.red
  );

  addPill(pills, "RETURN",
    pnl != null ? `${sgn(pnl)}${fmtUSD(pnl)}` : "—",
    fmtPct(pnlPct),
    pnlUp ? C.green : C.red
  );

  w.refreshAfterDate = new Date(Date.now() + 5 * 60 * 1000);
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
