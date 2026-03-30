import json
from datetime import datetime

import gspread
import numpy as np
import pandas as pd
import plotly.graph_objects as go

from app_core import _get_spreadsheet


SNAPSHOT_HEADERS = [
    "timestamp",
    "snapshot_date",
    "mode",
    "base_currency",
    "total_portfolio_value",
    "holdings_value",
    "cash_total_value",
    "invested_capital",
    "unrealized_pnl",
    "realized_pnl",
    "total_return",
    "volatility",
    "sharpe",
    "max_drawdown",
    "benchmark_cum_return",
    "excess_vs_benchmark",
    "weights_json",
    "values_json",
    "notes",
]


def connect_snapshots_worksheet():
    spreadsheet = _get_spreadsheet()

    try:
        ws = spreadsheet.worksheet("portfolio_snapshots")
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title="portfolio_snapshots", rows=3000, cols=30)

    try:
        current_header = ws.row_values(1)
    except Exception:
        current_header = []

    if current_header != SNAPSHOT_HEADERS:
        ws.clear()
        ws.update(range_name="A1", values=[SNAPSHOT_HEADERS])

    return ws


def _safe_json_dict(raw):
    if raw is None or raw == "":
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    return {}


def save_portfolio_snapshot(ctx, notes=""):
    ws = connect_snapshots_worksheet()

    df = ctx.get("df", pd.DataFrame()).copy()
    weights_map = {}
    values_map = {}

    if not df.empty:
        for _, row in df.iterrows():
            ticker = str(row["Ticker"])
            weights_map[ticker] = float(row["Weight"])
            values_map[ticker] = float(row["Value"])

    row = [
        datetime.now().isoformat(timespec="seconds"),
        str(datetime.now().date()),
        str(ctx.get("mode", "")),
        str(ctx.get("base_currency", "")),
        float(ctx.get("total_portfolio_value", 0.0)),
        float(ctx.get("holdings_value", 0.0)),
        float(ctx.get("cash_total_value", 0.0)),
        float(ctx.get("invested_capital", 0.0)),
        float(ctx.get("unrealized_pnl", 0.0)),
        float(ctx.get("realized_pnl", 0.0)),
        float(ctx.get("total_return", 0.0)),
        float(ctx.get("volatility", 0.0)),
        float(ctx.get("sharpe", 0.0)),
        float(ctx.get("max_drawdown", 0.0)),
        float(ctx.get("benchmark_cum_return", 0.0) if ctx.get("benchmark_cum_return") is not None else 0.0),
        float(ctx.get("excess_vs_benchmark", 0.0) if ctx.get("excess_vs_benchmark") is not None else 0.0),
        json.dumps(weights_map),
        json.dumps(values_map),
        str(notes).strip(),
    ]

    ws.append_row(row, value_input_option="RAW")


def load_portfolio_snapshots():
    ws = connect_snapshots_worksheet()
    records = ws.get_all_records(value_render_option="UNFORMATTED_VALUE")

    if not records:
        return pd.DataFrame(columns=SNAPSHOT_HEADERS)

    df = pd.DataFrame(records)
    df.columns = [str(c).strip() for c in df.columns]

    for col in SNAPSHOT_HEADERS:
        if col not in df.columns:
            df[col] = None

    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df["snapshot_date"] = pd.to_datetime(df["snapshot_date"], errors="coerce")

    numeric_cols = [
        "total_portfolio_value",
        "holdings_value",
        "cash_total_value",
        "invested_capital",
        "unrealized_pnl",
        "realized_pnl",
        "total_return",
        "volatility",
        "sharpe",
        "max_drawdown",
        "benchmark_cum_return",
        "excess_vs_benchmark",
    ]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    df["mode"] = df["mode"].astype(str)
    df["base_currency"] = df["base_currency"].astype(str)
    df["notes"] = df["notes"].fillna("").astype(str)
    df["weights_json"] = df["weights_json"].fillna("").astype(str)
    df["values_json"] = df["values_json"].fillna("").astype(str)

    df = df.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    return df


def filter_snapshots_for_context(snapshots_df, mode, base_currency):
    if snapshots_df is None or snapshots_df.empty:
        return pd.DataFrame(columns=SNAPSHOT_HEADERS)

    work = snapshots_df.copy()
    work = work[work["base_currency"].astype(str) == str(base_currency)].copy()

    if mode:
        work = work[work["mode"].astype(str) == str(mode)].copy()

    work = work.sort_values("timestamp").reset_index(drop=True)
    return work


def build_snapshot_timeline_figure(snapshots_df, base_currency):
    if snapshots_df is None or snapshots_df.empty:
        return None

    y_max = float(snapshots_df["total_portfolio_value"].max()) * 1.15
    y_max = max(y_max, 1.0)

    fig = go.Figure()
    fig.add_scatter(
        x=snapshots_df["timestamp"],
        y=snapshots_df["total_portfolio_value"],
        mode="lines+markers",
        name="Total Portfolio",
        hovertemplate="%{x|%Y-%m-%d %H:%M}<br>Total: %{y:,.2f}<extra></extra>",
    )
    fig.add_scatter(
        x=snapshots_df["timestamp"],
        y=snapshots_df["holdings_value"],
        mode="lines+markers",
        name="Holdings",
        hovertemplate="%{x|%Y-%m-%d %H:%M}<br>Holdings: %{y:,.2f}<extra></extra>",
    )
    fig.add_scatter(
        x=snapshots_df["timestamp"],
        y=snapshots_df["cash_total_value"],
        mode="lines+markers",
        name="Cash",
        hovertemplate="%{x|%Y-%m-%d %H:%M}<br>Cash: %{y:,.2f}<extra></extra>",
    )

    fig.update_layout(
        paper_bgcolor="#0b0f14",
        plot_bgcolor="#0b0f14",
        font=dict(color="#e6e6e6"),
        height=390,
        margin=dict(t=20, b=20, l=20, r=20),
        xaxis_title="Snapshot Time",
        yaxis=dict(title=f"Value ({base_currency})", range=[0, y_max]),
        legend=dict(orientation="h", y=1.08, x=0.0),
    )
    return fig


def build_allocation_history_figure(snapshots_df, top_n=5):
    if snapshots_df is None or snapshots_df.empty:
        return None

    latest_row = snapshots_df.iloc[-1]
    latest_weights = _safe_json_dict(latest_row.get("weights_json", ""))

    if not latest_weights:
        return None

    top_tickers = sorted(latest_weights.keys(), key=lambda x: latest_weights.get(x, 0.0), reverse=True)[:top_n]

    fig = go.Figure()

    for ticker in top_tickers:
        series_x = []
        series_y = []

        for _, row in snapshots_df.iterrows():
            weights_map = _safe_json_dict(row.get("weights_json", ""))
            value = float(weights_map.get(ticker, 0.0)) * 100.0
            series_x.append(row["timestamp"])
            series_y.append(value)

        fig.add_scatter(
            x=series_x,
            y=series_y,
            mode="lines+markers",
            name=ticker,
            hovertemplate="%{x|%Y-%m-%d %H:%M}<br>" + ticker + ": %{y:.2f}%<extra></extra>",
        )

    fig.update_layout(
        paper_bgcolor="#0b0f14",
        plot_bgcolor="#0b0f14",
        font=dict(color="#e6e6e6"),
        height=390,
        margin=dict(t=20, b=20, l=20, r=20),
        xaxis_title="Snapshot Time",
        yaxis=dict(title="Weight %", range=[0, 100]),
        legend=dict(orientation="h", y=1.08, x=0.0),
    )
    return fig


def build_snapshot_report_table(snapshots_df):
    if snapshots_df is None or snapshots_df.empty:
        return pd.DataFrame()

    work = snapshots_df.copy().sort_values("timestamp").reset_index(drop=True)

    work["Portfolio Change"] = work["total_portfolio_value"].diff().fillna(0.0)
    work["Holdings Change"] = work["holdings_value"].diff().fillna(0.0)
    work["Cash Change"] = work["cash_total_value"].diff().fillna(0.0)

    for col in ["total_return", "volatility", "max_drawdown", "benchmark_cum_return", "excess_vs_benchmark"]:
        if col in work.columns:
            work[col] = pd.to_numeric(work[col], errors="coerce").mul(100).round(2)

    out = work.rename(
        columns={
            "timestamp": "Timestamp",
            "total_portfolio_value": "Total Portfolio",
            "holdings_value": "Holdings",
            "cash_total_value": "Cash",
            "unrealized_pnl": "Unrealized PnL",
            "total_return": "Total Return %",
            "volatility": "Volatility %",
            "sharpe": "Sharpe",
            "max_drawdown": "Max Drawdown %",
            "benchmark_cum_return": "Benchmark Return %",
            "excess_vs_benchmark": "Excess vs Benchmark %",
            "notes": "Notes",
        }
    ).copy()

    out["Timestamp"] = pd.to_datetime(out["Timestamp"], errors="coerce")
    out = out[
        [
            "Timestamp",
            "Total Portfolio",
            "Portfolio Change",
            "Holdings",
            "Holdings Change",
            "Cash",
            "Cash Change",
            "Unrealized PnL",
            "Total Return %",
            "Volatility %",
            "Sharpe",
            "Max Drawdown %",
            "Benchmark Return %",
            "Excess vs Benchmark %",
            "Notes",
        ]
    ].copy()

    out = out.sort_values("Timestamp", ascending=False).reset_index(drop=True)
    return out


def build_monthly_snapshot_summary(snapshots_df):
    if snapshots_df is None or snapshots_df.empty:
        return pd.DataFrame()

    work = snapshots_df.copy().sort_values("timestamp").reset_index(drop=True)
    work["Month"] = pd.to_datetime(work["timestamp"], errors="coerce").dt.to_period("M").astype(str)
    monthly = work.groupby("Month", as_index=False).tail(1).copy()
    monthly = monthly.sort_values("timestamp").reset_index(drop=True)

    monthly["MoM Change"] = monthly["total_portfolio_value"].diff().fillna(0.0)
    monthly["MoM Change %"] = np.where(
        monthly["total_portfolio_value"].shift(1).fillna(0.0) > 0,
        (monthly["MoM Change"] / monthly["total_portfolio_value"].shift(1) * 100).round(2),
        0.0,
    )

    for col in ["total_return", "volatility", "max_drawdown"]:
        if col in monthly.columns:
            monthly[col] = pd.to_numeric(monthly[col], errors="coerce").mul(100).round(2)

    out = monthly.rename(
        columns={
            "total_portfolio_value": "Total Portfolio",
            "holdings_value": "Holdings",
            "cash_total_value": "Cash",
            "total_return": "Total Return %",
            "volatility": "Volatility %",
            "sharpe": "Sharpe",
            "max_drawdown": "Max Drawdown %",
        }
    ).copy()

    out = out[
        [
            "Month",
            "Total Portfolio",
            "MoM Change",
            "MoM Change %",
            "Holdings",
            "Cash",
            "Total Return %",
            "Volatility %",
            "Sharpe",
            "Max Drawdown %",
        ]
    ].copy()

    out = out.sort_values("Month", ascending=False).reset_index(drop=True)
    return out