// ─────────────────────────────────────────────────────────────
// Portfolio Tracker — iOS Widget (Scriptable)
// Muestra: valor total · cambio diario · retorno total
//
// INSTRUCCIONES:
//   1. Instala "Scriptable" desde el App Store (gratis)
//   2. Abre Scriptable → "+" → pega este script completo
//   3. Cambia EMAIL y PASSWORD abajo con tus credenciales
//   4. Guarda con el nombre "Portfolio"
//   5. Agrega el widget de Scriptable a tu pantalla de inicio
//      (pulsación larga → "+" → Scriptable → elige tamaño Small)
//   6. En las opciones del widget, selecciona el script "Portfolio"
// ─────────────────────────────────────────────────────────────

const EMAIL    = "sebastianaguilar9723@gmail.com";  // ← tu email
const PASSWORD = "TU_PASSWORD_AQUI";                 // ← tu contraseña
const API      = "https://portfolio-tracker-investments.onrender.com";

const KEY_TOKEN   = "pt_token";
const KEY_EXPIRES = "pt_token_exp";

// ── Auth ─────────────────────────────────────────────────────

async function getToken() {
  const now = Date.now();
  if (Keychain.contains(KEY_TOKEN) && Keychain.contains(KEY_EXPIRES)) {
    const exp = parseInt(Keychain.get(KEY_EXPIRES), 10);
    if (exp > now + 60_000) {          // válido por al menos 1 min más
      return Keychain.get(KEY_TOKEN);
    }
  }
  // Login
  const req = new Request(`${API}/api/auth/login`);
  req.method = "POST";
  req.headers = { "Content-Type": "application/json" };
  req.body = JSON.stringify({ email: EMAIL, password: PASSWORD });
  const res = await req.loadJSON();
  if (!res.access_token) throw new Error("Login failed");
  const exp = now + 23 * 3600 * 1000; // 23h (token dura 24h)
  Keychain.set(KEY_TOKEN, res.access_token);
  Keychain.set(KEY_EXPIRES, String(exp));
  return res.access_token;
}

// ── Fetch portfolio ───────────────────────────────────────────

async function fetchPortfolio(token) {
  const req = new Request(`${API}/api/portfolio/summary`);
  req.headers = { Authorization: `Bearer ${token}` };
  return req.loadJSON();
}

// ── Format helpers ────────────────────────────────────────────

function fmtUSD(v) {
  if (v == null) return "—";
  const abs = Math.abs(v);
  if (abs >= 1000) return `$${(v / 1000).toFixed(2)}k`;
  return `$${v.toFixed(2)}`;
}

function fmtPct(v) {
  if (v == null) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;
}

function sign(v) { return v >= 0 ? "+" : ""; }

// ── Build widget ──────────────────────────────────────────────

async function buildWidget() {
  let data = null;
  let error = null;

  try {
    const token = await getToken();
    data = await fetchPortfolio(token);
  } catch (e) {
    error = e.message;
  }

  const w = new ListWidget();
  w.backgroundColor = new Color("#0b0f14");
  w.setPadding(12, 14, 12, 14);

  // ── Header ──
  const header = w.addText("PORTFOLIO");
  header.font = Font.boldMonospacedSystemFont(8);
  header.textColor = new Color("#f3a712");
  header.textOpacity = 0.85;

  w.addSpacer(4);

  if (error || !data) {
    const errTxt = w.addText(error || "No data");
    errTxt.font = Font.systemFont(10);
    errTxt.textColor = new Color("#ff4d4d");
    return w;
  }

  const value    = data.total_value_base ?? 0;
  const dayChg   = data.total_day_change_base ?? null;
  const invested = data.total_invested_base ?? 0;
  const pnl      = invested > 0 ? value - invested : (data.total_unrealized_pnl ?? null);
  const pnlPct   = invested > 0 ? ((value - invested) / invested * 100) : (data.total_unrealized_pnl_pct ?? null);
  const dayPct   = (dayChg != null && value > 0) ? (dayChg / (value - dayChg) * 100) : null;

  // ── Total value ──
  const valTxt = w.addText(fmtUSD(value));
  valTxt.font = Font.boldMonospacedSystemFont(22);
  valTxt.textColor = new Color("#e8edf5");
  valTxt.minimumScaleFactor = 0.7;

  w.addSpacer(6);

  // ── Day change ──
  const dayRow = w.addStack();
  dayRow.layoutHorizontally();
  dayRow.centerAlignContent();

  const dotDay = dayRow.addText(dayChg != null && dayChg >= 0 ? "▲" : "▼");
  dotDay.font = Font.boldSystemFont(9);
  dotDay.textColor = dayChg != null && dayChg >= 0 ? new Color("#4dff91") : new Color("#ff4d4d");
  dayRow.addSpacer(4);

  const dayLabel = dayRow.addText("HOY");
  dayLabel.font = Font.boldMonospacedSystemFont(8);
  dayLabel.textColor = new Color("#8a9bb5");
  dayRow.addSpacer(4);

  const dayVal = dayRow.addText(
    dayChg != null
      ? `${sign(dayChg)}${fmtUSD(dayChg)}  ${fmtPct(dayPct)}`
      : "—"
  );
  dayVal.font = Font.mediumMonospacedSystemFont(10);
  dayVal.textColor = dayChg != null && dayChg >= 0 ? new Color("#4dff91") : new Color("#ff4d4d");

  w.addSpacer(5);

  // ── Total return ──
  const retRow = w.addStack();
  retRow.layoutHorizontally();
  retRow.centerAlignContent();

  const dotRet = retRow.addText(pnl != null && pnl >= 0 ? "▲" : "▼");
  dotRet.font = Font.boldSystemFont(9);
  dotRet.textColor = pnl != null && pnl >= 0 ? new Color("#4dff91") : new Color("#ff4d4d");
  retRow.addSpacer(4);

  const retLabel = retRow.addText("TOTAL");
  retLabel.font = Font.boldMonospacedSystemFont(8);
  retLabel.textColor = new Color("#8a9bb5");
  retRow.addSpacer(4);

  const retVal = retRow.addText(
    pnl != null
      ? `${sign(pnl)}${fmtUSD(pnl)}  ${fmtPct(pnlPct)}`
      : "—"
  );
  retVal.font = Font.mediumMonospacedSystemFont(10);
  retVal.textColor = pnl != null && pnl >= 0 ? new Color("#4dff91") : new Color("#ff4d4d");

  w.addSpacer(6);

  // ── Timestamp ──
  const now = new Date();
  const hhmm = now.toLocaleTimeString("es-CO", { hour: "2-digit", minute: "2-digit" });
  const ts = w.addText(`Actualizado ${hhmm}`);
  ts.font = Font.systemFont(7);
  ts.textColor = new Color("#8a9bb5");
  ts.textOpacity = 0.6;

  // Refresh cada 15 min
  w.refreshAfterDate = new Date(Date.now() + 15 * 60 * 1000);

  return w;
}

// ── Run ───────────────────────────────────────────────────────

const widget = await buildWidget();

if (config.runsInWidget) {
  Script.setWidget(widget);
} else {
  widget.presentSmall();   // preview en app
}

Script.complete();
