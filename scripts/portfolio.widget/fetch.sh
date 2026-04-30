#!/bin/bash
# Portfolio Tracker — Übersicht widget data + HTML generator

TOKEN_FILE="/tmp/.pt_token"
EXP_FILE="/tmp/.pt_expires"
API="https://portfolio-tracker-investments.onrender.com"
EMAIL="sebastianaguilar9723@gmail.com"
PASSWORD="Molly2013."

NOW=$(date +%s)
TOKEN=""

if [ -f "$TOKEN_FILE" ] && [ -f "$EXP_FILE" ]; then
  EXP=$(cat "$EXP_FILE")
  if [ "$NOW" -lt "$EXP" ]; then TOKEN=$(cat "$TOKEN_FILE"); fi
fi

if [ -z "$TOKEN" ]; then
  RESP=$(curl -s --max-time 30 -X POST "$API/api/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}")
  TOKEN=$(python3 -c "import sys,json; print(json.loads('$RESP').get('access_token',''))" 2>/dev/null || echo "")
  if [ -n "$TOKEN" ]; then
    echo "$TOKEN" > "$TOKEN_FILE"
    echo $((NOW + 82800)) > "$EXP_FILE"
  fi
fi

if [ -z "$TOKEN" ]; then
  echo '<div style="color:#f87171;font-family:system-ui;padding:16px">⚠️ Login failed</div>'
  exit 0
fi

START=$(date -v-30d +%Y-%m-%d 2>/dev/null || date -d "30 days ago" +%Y-%m-%d 2>/dev/null)
PORT=$(curl -s --max-time 30 "$API/api/portfolio" -H "Authorization: Bearer $TOKEN")
HIST=$(curl -s --max-time 30 "$API/api/portfolio/history?start=$START" -H "Authorization: Bearer $TOKEN")

python3 << PYEOF
import json, sys, math

try:
    port = json.loads('''$PORT''')
    rows = port.get("rows", [])
    value    = port.get("total_value_base") or 0
    day_chg  = port.get("total_day_change_base")
    invested = port.get("total_invested_base") or 0
    pnl      = (value - invested) if invested > 0 else None
    pnl_pct  = ((value - invested) / invested * 100) if invested > 0 else None
    day_pct  = (day_chg / (value - day_chg) * 100) if (day_chg is not None and value > 0) else None
except Exception as e:
    print(f'<div style="color:#f87171;padding:16px">⚠️ {e}</div>')
    sys.exit()

try:
    hist = json.loads('''$HIST''')
    if not isinstance(hist, list): hist = []
except:
    hist = []

GREEN = "#4ade80"
RED   = "#f87171"

def fmt(v, compact=False):
    if v is None: return "—"
    neg = "-" if v < 0 else ""
    ab  = abs(v)
    if compact and ab >= 1000:
        return f"{neg}\${ab/1000:.1f}k"
    return f"{neg}\${ab:,.2f}"

def pct(v):
    if v is None: return "—"
    s = "+" if v >= 0 else ""
    return f"{s}{v:.2f}%"

def sgn(v): return "+" if v >= 0 else ""

# Sparkline SVG
def sparkline(points, color, W=24, H=18):
    if len(points) < 2: return ""
    vals = [p["value"] for p in points]
    mn, mx = min(vals), max(vals)
    rng = mx - mn or 1
    pad = 2
    coords = " ".join(
        f"{pad + (i/(len(vals)-1))*(W-pad*2):.1f},{pad + (1-(v-mn)/rng)*(H-pad*2):.1f}"
        for i, v in enumerate(vals)
    )
    return f'<svg width="{W}" height="{H}" style="display:block"><polyline points="{coords}" fill="none" stroke="{color}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>'

is_up  = day_chg is None or day_chg >= 0
pnl_up = pnl is None or pnl >= 0
dc     = GREEN if is_up  else RED
pc     = GREEN if pnl_up else RED

chart = sparkline(hist, pc)

# Pills
def pill(label, main_val, sub_val, color):
    return f'''
    <div style="flex:1;background:rgba(255,255,255,.07);border-radius:8px;padding:6px 9px">
      <div style="font-size:8px;font-weight:600;letter-spacing:.08em;color:rgba(255,255,255,.35);margin-bottom:2px">{label}</div>
      <div style="font-size:12px;font-weight:600;color:{color};line-height:1.3">{main_val}</div>
      <div style="font-size:10px;font-weight:500;color:{color}">{sub_val}</div>
    </div>'''

# Positions rows
active = [r for r in rows if r.get("shares", 0) > 0]
active.sort(key=lambda r: -(r.get("value_base") or 0))

pos_rows = ""
for r in active:
    chg = r.get("change_pct_1d")
    cc  = GREEN if (chg or 0) >= 0 else RED
    if chg is None: cc = "rgba(255,255,255,.4)"
    sh = r.get("shares", 0)
    sh_str = f"{sh:.0f}" if sh == int(sh) else (f"{sh:.3f}" if sh < 10 else f"{sh:.1f}")
    pos_rows += f'''
    <div style="display:grid;grid-template-columns:1fr 50px 60px 50px;padding:5px 16px;align-items:center;border-bottom:1px solid rgba(255,255,255,.04)">
      <div>
        <div style="font-size:12px;font-weight:700;color:rgba(255,255,255,.9)">{r.get("ticker","")}</div>
        <div style="font-size:8px;color:rgba(255,255,255,.28);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:88px">{r.get("name","")}</div>
      </div>
      <div style="font-size:11px;text-align:right;color:rgba(255,255,255,.42);font-variant-numeric:tabular-nums">{sh_str}</div>
      <div style="font-size:11px;text-align:right;font-weight:600;color:rgba(255,255,255,.85);font-variant-numeric:tabular-nums">{fmt(r.get("value_base"), compact=True)}</div>
      <div style="font-size:11px;text-align:right;font-weight:600;color:{cc};font-variant-numeric:tabular-nums">{pct(chg)}</div>
    </div>'''

from datetime import datetime
now = datetime.now().strftime("%I:%M %p")

html = f'''
<div style="background:rgba(28,28,30,.85);backdrop-filter:blur(24px);-webkit-backdrop-filter:blur(24px);border-radius:16px;width:300px;border:1px solid rgba(255,255,255,.1);overflow:hidden;font-family:-apple-system,BlinkMacSystemFont,'SF Pro Text',sans-serif;-webkit-font-smoothing:antialiased;color:white">

  <div style="padding:14px 16px 10px">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
      <span style="font-size:15px;font-weight:700;color:rgba(255,255,255,.95)">Portfolio</span>
      <div style="background:rgba(255,255,255,.1);border-radius:50%;width:32px;height:32px;display:flex;align-items:center;justify-content:center">{chart}</div>
    </div>
    <div style="font-size:28px;font-weight:700;letter-spacing:-.03em;line-height:1;margin-bottom:10px">{fmt(value)}</div>
    <div style="display:flex;gap:8px">
      {pill("TODAY", f"{sgn(day_chg)}{fmt(day_chg, True)}" if day_chg is not None else "—", pct(day_pct), dc)}
      {pill("RETURN", f"{sgn(pnl)}{fmt(pnl, True)}" if pnl is not None else "—", pct(pnl_pct), pc)}
    </div>
  </div>

  <div style="height:1px;background:rgba(255,255,255,.07);margin:0 16px"></div>

  <div style="display:grid;grid-template-columns:1fr 50px 60px 50px;padding:5px 16px;background:rgba(255,255,255,.04)">
    <div style="font-size:8px;font-weight:600;letter-spacing:.07em;color:rgba(255,255,255,.3)">ASSET</div>
    <div style="font-size:8px;font-weight:600;letter-spacing:.07em;color:rgba(255,255,255,.3);text-align:right">SHARES</div>
    <div style="font-size:8px;font-weight:600;letter-spacing:.07em;color:rgba(255,255,255,.3);text-align:right">VALUE</div>
    <div style="font-size:8px;font-weight:600;letter-spacing:.07em;color:rgba(255,255,255,.3);text-align:right">DAY</div>
  </div>

  <div>{pos_rows}</div>

  <div style="padding:6px 16px 9px;border-top:1px solid rgba(255,255,255,.06)">
    <span style="font-size:9px;color:rgba(255,255,255,.22)">Updated {now}</span>
  </div>

</div>
'''
print(html)
PYEOF
