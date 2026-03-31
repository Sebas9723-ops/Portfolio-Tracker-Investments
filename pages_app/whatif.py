import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app_core import info_metric, info_section, render_page_title


# ── Metric computation ────────────────────────────────────────────────────────

def _compute_metrics(
    asset_returns: pd.DataFrame,
    weights: dict[str, float],
    risk_free_rate: float,
) -> dict:
    """
    Compute annualised portfolio metrics from a weight dict.
    Returns: ann_return, volatility, sharpe, max_drawdown, cum_returns (pd.Series).
    """
    usable = [t for t in weights if t in asset_returns.columns and weights[t] > 0]
    if not usable:
        return {}

    total = sum(weights[t] for t in usable)
    w = pd.Series({t: weights[t] / total for t in usable})

    port_ret = asset_returns[usable].mul(w, axis=1).sum(axis=1).dropna()
    if port_ret.empty:
        return {}

    cum = (1 + port_ret).cumprod()
    ann_ret = float(port_ret.mean() * 252)
    vol = float(port_ret.std() * np.sqrt(252))
    sharpe = (ann_ret - risk_free_rate) / vol if vol > 0 else 0.0
    rolling_max = cum.cummax()
    max_dd = float((cum / rolling_max - 1).min())

    return {
        "ann_return": ann_ret,
        "volatility": vol,
        "sharpe": sharpe,
        "max_drawdown": max_dd,
        "cum_returns": cum,
    }


# ── Charts ────────────────────────────────────────────────────────────────────

def _build_pie(weights: dict[str, float], title: str) -> go.Figure:
    labels = list(weights.keys())
    values = [weights[t] * 100 for t in labels]
    fig = go.Figure(go.Pie(
        labels=labels, values=values,
        hole=0.45,
        textinfo="label+percent",
        textfont=dict(size=11),
        marker=dict(line=dict(color="#0b0f14", width=2)),
    ))
    fig.update_layout(
        title=dict(text=title, font=dict(size=13, color="#e6e6e6")),
        paper_bgcolor="#0b0f14",
        font=dict(color="#e6e6e6"),
        height=320,
        margin=dict(t=40, b=20, l=20, r=20),
        showlegend=False,
    )
    return fig


def _build_cumreturn_chart(
    current_cum: pd.Series,
    whatif_cum: pd.Series,
) -> go.Figure:
    # Align on common dates
    df = pd.DataFrame({"Current": current_cum, "What-If": whatif_cum}).dropna()
    fig = go.Figure()
    fig.add_scatter(
        x=df.index, y=(df["Current"] - 1) * 100,
        mode="lines", name="Current",
        line=dict(color="#4db8ff", width=2),
        hovertemplate="%{x|%Y-%m-%d}<br>%{y:.2f}%<extra>Current</extra>",
    )
    fig.add_scatter(
        x=df.index, y=(df["What-If"] - 1) * 100,
        mode="lines", name="What-If",
        line=dict(color="#f3a712", width=2),
        hovertemplate="%{x|%Y-%m-%d}<br>%{y:.2f}%<extra>What-If</extra>",
    )
    fig.update_layout(
        paper_bgcolor="#0b0f14", plot_bgcolor="#0b0f14",
        font=dict(color="#e6e6e6"), height=380,
        margin=dict(t=20, b=20, l=20, r=20),
        xaxis_title="Date",
        yaxis_title="Cumulative Return (%)",
        yaxis=dict(ticksuffix="%"),
        legend=dict(orientation="h", y=1.08, x=0.0),
    )
    return fig


# ── Metric delta helper ───────────────────────────────────────────────────────

def _delta_label(current: float, whatif: float, higher_is_better: bool = True) -> str:
    delta = whatif - current
    if abs(delta) < 1e-6:
        return "No change"
    arrow = "▲" if delta > 0 else "▼"
    color = "#00e676" if (delta > 0) == higher_is_better else "#f44336"
    return (
        f'<span style="color:{color};font-size:12px;">'
        f"{arrow} {abs(delta):.2%}</span>"
    )


# ── Page renderer ─────────────────────────────────────────────────────────────

def render_whatif_page(ctx: dict):
    render_page_title("What-If Simulator")

    df = ctx.get("df", pd.DataFrame())
    asset_returns = ctx.get("asset_returns", pd.DataFrame())
    rfr = float(ctx.get("risk_free_rate", 0.02))

    if df.empty or asset_returns is None or asset_returns.empty:
        st.info("No portfolio data available for simulation.")
        return

    # Tickers that have both holdings and return history
    available = [
        t for t in df["Ticker"].tolist()
        if t in asset_returns.columns
    ]
    if not available:
        st.info("No historical return data available for current holdings.")
        return

    current_weights = (
        df[df["Ticker"].isin(available)]
        .set_index("Ticker")["Weight"]
        .to_dict()
    )
    # Normalize current weights to sum=1
    cw_total = sum(current_weights.values())
    if cw_total > 0:
        current_weights = {t: v / cw_total for t, v in current_weights.items()}

    ticker_list = sorted(available)

    # Handle reset BEFORE the form renders so session_state keys are set
    # before the number_input widgets register them.
    if st.session_state.pop("wi_reset_pending", False):
        for ticker in ticker_list:
            st.session_state[f"wi_{ticker}"] = round(current_weights.get(ticker, 0.0) * 100, 1)

    # ── Weight input form ──────────────────────────────────────────────────────
    st.markdown(
        "Adjust hypothetical weights below and press **Run Simulation** to see "
        "how the change affects portfolio metrics."
    )

    with st.form("whatif_form"):
        st.markdown("#### Hypothetical Weights (%)")
        cols_per_row = 4
        rows = [ticker_list[i: i + cols_per_row] for i in range(0, len(ticker_list), cols_per_row)]

        for row_tickers in rows:
            cols = st.columns(len(row_tickers))
            for col, ticker in zip(cols, row_tickers):
                default_pct = round(current_weights.get(ticker, 0.0) * 100, 1)
                col.number_input(
                    ticker,
                    min_value=0.0, max_value=100.0,
                    value=float(st.session_state.get(f"wi_{ticker}", default_pct)),
                    step=0.5, format="%.1f",
                    key=f"wi_{ticker}",
                )

        c_run, c_reset = st.columns([2, 1])
        run = c_run.form_submit_button("Run Simulation", type="primary", use_container_width=True)
        reset = c_reset.form_submit_button("Reset to Current", use_container_width=True)

    if reset:
        # Can't set widget keys after they've been rendered — use a pending flag
        # that is consumed at the top of the next run, before the form renders.
        st.session_state["wi_reset_pending"] = True
        st.rerun()

    # Live weight sum indicator (outside form — reads session state)
    raw_pcts = {t: float(st.session_state.get(f"wi_{t}", current_weights.get(t, 0.0) * 100)) for t in ticker_list}
    total_pct = sum(raw_pcts.values())
    sum_color = "#00e676" if abs(total_pct - 100.0) < 0.1 else "#f44336"
    st.markdown(
        f'<span style="font-family:\'IBM Plex Mono\',monospace;font-size:13px;">'
        f'Weight sum: <b style="color:{sum_color};">{total_pct:.1f}%</b>'
        f'{"" if abs(total_pct - 100.0) < 0.1 else " — will be normalized to 100% on simulation"}'
        f"</span>",
        unsafe_allow_html=True,
    )

    if not run and "whatif_result" not in st.session_state:
        return

    if run:
        if total_pct == 0:
            st.warning("All weights are zero — set at least one weight above 0.")
            return
        # Normalize
        whatif_weights = {t: raw_pcts[t] / total_pct for t in ticker_list}
        st.session_state["whatif_result"] = {
            "whatif_weights": whatif_weights,
            "current_weights": current_weights,
        }

    result = st.session_state.get("whatif_result", {})
    if not result:
        return

    whatif_weights = result["whatif_weights"]
    cur_weights = result["current_weights"]

    current_m = _compute_metrics(asset_returns, cur_weights, rfr)
    whatif_m = _compute_metrics(asset_returns, whatif_weights, rfr)

    if not current_m or not whatif_m:
        st.warning("Could not compute metrics — check that selected tickers have historical data.")
        return

    # ── Metrics comparison ─────────────────────────────────────────────────────
    info_section(
        "Metrics Comparison",
        "Current portfolio vs hypothetical allocation — based on historical returns.",
    )

    metrics = [
        ("Expected Return", "ann_return", True, True),   # (label, key, higher_is_better, pct_format)
        ("Volatility", "volatility", False, True),
        ("Sharpe Ratio", "sharpe", True, False),
        ("Max Drawdown", "max_drawdown", False, True),
    ]

    header_cols = st.columns([2, 2, 2, 2])
    for col, (label, key, hib, _) in zip(header_cols, metrics):
        cur_val = current_m[key]
        wi_val = whatif_m[key]
        fmt_cur = f"{cur_val:.2%}" if key != "sharpe" else f"{cur_val:.3f}"
        fmt_wi = f"{wi_val:.2%}" if key != "sharpe" else f"{wi_val:.3f}"
        delta_html = _delta_label(cur_val, wi_val, hib)

        col.markdown(
            f"<div style='background:#121922;border:1px solid #2e3744;border-radius:6px;"
            f"padding:12px 14px;'>"
            f"<div style='color:#888;font-size:11px;text-transform:uppercase;letter-spacing:0.5px;'>{label}</div>"
            f"<div style='color:#e6e6e6;font-size:14px;margin:4px 0;'>"
            f"<span style='color:#4db8ff;'>Current:</span> {fmt_cur}</div>"
            f"<div style='color:#e6e6e6;font-size:14px;margin:4px 0;'>"
            f"<span style='color:#f3a712;'>What-If:</span> {fmt_wi}</div>"
            f"<div style='margin-top:6px;'>{delta_html}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Allocation pies ────────────────────────────────────────────────────────
    info_section("Allocation Comparison", "Current vs hypothetical portfolio weights.")
    left, right = st.columns(2)
    with left:
        st.plotly_chart(
            _build_pie(cur_weights, "Current Allocation"),
            use_container_width=True,
            key="wi_pie_current",
        )
    with right:
        st.plotly_chart(
            _build_pie(whatif_weights, "What-If Allocation"),
            use_container_width=True,
            key="wi_pie_whatif",
        )

    # ── Cumulative return chart ────────────────────────────────────────────────
    info_section(
        "Cumulative Return",
        "Historical performance of current vs hypothetical weights (same time period).",
    )
    st.plotly_chart(
        _build_cumreturn_chart(current_m["cum_returns"], whatif_m["cum_returns"]),
        use_container_width=True,
        key="wi_cumreturn_chart",
    )

    st.caption(
        "Simulation uses historical daily returns — past performance does not guarantee future results. "
        "Weights are normalized to 100% before computation."
    )
