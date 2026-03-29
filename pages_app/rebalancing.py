import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app_core import (
    build_contribution_suggestion,
    build_rebalancing_table,
    info_metric,
    info_section,
    render_page_title,
)


def _status_from_deviation(deviation_pct: float, tolerance_pct: float) -> str:
    if deviation_pct > tolerance_pct:
        return "Trim / Sell"
    if deviation_pct < -tolerance_pct:
        return "Buy / Add"
    return "Within Band"


def _build_monitor_table(df: pd.DataFrame, tolerance_pct: float, base_currency: str) -> pd.DataFrame:
    work = df.copy()

    holdings_total = float(work["Value"].sum()) if not work.empty else 0.0

    work["Lower Band %"] = work["Target %"] - tolerance_pct
    work["Upper Band %"] = work["Target %"] + tolerance_pct
    work["Status"] = work["Deviation %"].apply(lambda x: _status_from_deviation(float(x), tolerance_pct))

    if holdings_total > 0:
        work[f"Trade To Target ({base_currency})"] = (
            (work["Target %"] - work["Weight %"]) / 100.0 * holdings_total
        )
    else:
        work[f"Trade To Target ({base_currency})"] = 0.0

    out = work[
        [
            "Ticker",
            "Name",
            "Weight %",
            "Target %",
            "Deviation %",
            "Lower Band %",
            "Upper Band %",
            f"Trade To Target ({base_currency})",
            "Status",
        ]
    ].copy()

    for col in [
        "Weight %",
        "Target %",
        "Deviation %",
        "Lower Band %",
        "Upper Band %",
        f"Trade To Target ({base_currency})",
    ]:
        out[col] = pd.to_numeric(out[col], errors="coerce").round(2)

    out = out.sort_values("Deviation %", key=lambda s: s.abs(), ascending=False).reset_index(drop=True)
    return out


def _build_alerts(ctx, tolerance_pct: float, concentration_pct: float, cash_alert_pct: float) -> list[dict]:
    alerts = []
    df = ctx["df"].copy()

    if df.empty:
        return alerts

    for _, row in df.iterrows():
        ticker = str(row["Ticker"])
        name = str(row["Name"])
        deviation = float(row["Deviation %"])
        weight_pct = float(row["Weight %"])
        target_pct = float(row["Target %"])

        if abs(deviation) > tolerance_pct:
            if deviation > 0:
                alerts.append(
                    {
                        "level": "warning",
                        "title": f"{ticker} overweight",
                        "detail": f"{name} está en {weight_pct:.2f}% vs target {target_pct:.2f}%. Desviación: +{deviation:.2f}%.",
                    }
                )
            else:
                alerts.append(
                    {
                        "level": "warning",
                        "title": f"{ticker} underweight",
                        "detail": f"{name} está en {weight_pct:.2f}% vs target {target_pct:.2f}%. Desviación: {deviation:.2f}%.",
                    }
                )

        if weight_pct > concentration_pct:
            alerts.append(
                {
                    "level": "critical",
                    "title": f"{ticker} concentración alta",
                    "detail": f"{name} pesa {weight_pct:.2f}% del portafolio invertido, por encima del umbral de {concentration_pct:.2f}%.",
                }
            )

    total_portfolio_value = float(ctx["total_portfolio_value"])
    cash_total_value = float(ctx["cash_total_value"])
    cash_pct = (cash_total_value / total_portfolio_value * 100.0) if total_portfolio_value > 0 else 0.0

    if cash_pct > cash_alert_pct:
        alerts.append(
            {
                "level": "info",
                "title": "Cash elevado",
                "detail": f"El cash representa {cash_pct:.2f}% del portafolio total.",
            }
        )

    if float(ctx["max_drawdown"]) < -0.15:
        alerts.append(
            {
                "level": "info",
                "title": "Drawdown relevante",
                "detail": f"El máximo drawdown observado es {ctx['max_drawdown']:.2%}.",
            }
        )

    level_rank = {"critical": 0, "warning": 1, "info": 2}
    alerts = sorted(alerts, key=lambda x: (level_rank.get(x["level"], 9), x["title"]))
    return alerts


def _render_alerts(alerts: list[dict]):
    if not alerts:
        st.success("No hay alertas activas. El portafolio está dentro de los parámetros definidos.")
        return

    color_map = {
        "critical": ("#ef4444", "#2a1113"),
        "warning": ("#f3a712", "#21180d"),
        "info": ("#60a5fa", "#0e1a29"),
    }

    for alert in alerts:
        border, bg = color_map.get(alert["level"], ("#60a5fa", "#0e1a29"))
        st.markdown(
            f"""
            <div style="
                border:1px solid {border};
                border-left:4px solid {border};
                background:{bg};
                border-radius:6px;
                padding:10px 12px;
                margin-bottom:10px;
            ">
                <div style="font-weight:800; color:{border}; text-transform:uppercase; font-size:13px; letter-spacing:0.4px;">
                    {alert["title"]}
                </div>
                <div style="color:#d7dee7; font-size:13px; margin-top:4px; line-height:1.35;">
                    {alert["detail"]}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def _build_compare_figure(df_current: pd.DataFrame, proposed_weight_map: dict[str, float]) -> go.Figure:
    tickers = df_current["Ticker"].tolist()
    current_weights = df_current["Weight %"].tolist()
    target_weights = df_current["Target %"].tolist()
    proposed_weights = [float(proposed_weight_map.get(t, 0.0)) for t in tickers]

    fig = go.Figure()
    fig.add_bar(x=tickers, y=current_weights, name="Current %")
    fig.add_bar(x=tickers, y=target_weights, name="Target %")
    fig.add_bar(x=tickers, y=proposed_weights, name="Proposed %")

    fig.update_layout(
        barmode="group",
        paper_bgcolor="#0b0f14",
        plot_bgcolor="#0b0f14",
        font=dict(color="#e6e6e6"),
        height=380,
        margin=dict(t=20, b=20, l=20, r=20),
        xaxis_title="Ticker",
        yaxis_title="Weight %",
    )
    return fig


def _build_simple_summary(ctx, monitor_df: pd.DataFrame):
    out_of_band = int((monitor_df["Status"] != "Within Band").sum()) if not monitor_df.empty else 0
    max_dev = float(monitor_df["Deviation %"].abs().max()) if not monitor_df.empty else 0.0

    biggest_over = None
    biggest_under = None

    if not monitor_df.empty:
        over_df = monitor_df[monitor_df["Deviation %"] > 0]
        under_df = monitor_df[monitor_df["Deviation %"] < 0]

        if not over_df.empty:
            biggest_over = over_df.iloc[0]
        if not under_df.empty:
            biggest_under = under_df.iloc[0]

    cash_pct = (
        float(ctx["cash_total_value"]) / float(ctx["total_portfolio_value"]) * 100.0
        if float(ctx["total_portfolio_value"]) > 0
        else 0.0
    )

    c1, c2, c3, c4 = st.columns(4)
    info_metric(c1, "Out Of Band", str(out_of_band), "Posiciones fuera de banda.")
    info_metric(c2, "Max Deviation", f"{max_dev:.2f}%", "Mayor desviación absoluta vs target.")
    info_metric(c3, "Cash Ratio", f"{cash_pct:.2f}%", "Cash como porcentaje del portafolio total.")
    info_metric(c4, "Sharpe", f"{ctx['sharpe']:.2f}", "Sharpe ratio actual.")

    c5, c6 = st.columns(2)
    if biggest_over is not None:
        info_metric(
            c5,
            "Largest Overweight",
            f"{biggest_over['Ticker']} ({biggest_over['Deviation %']:.2f}%)",
            "Activo más sobreponderado frente al objetivo.",
        )
    else:
        info_metric(c5, "Largest Overweight", "-", "Activo más sobreponderado frente al objetivo.")

    if biggest_under is not None:
        info_metric(
            c6,
            "Largest Underweight",
            f"{biggest_under['Ticker']} ({biggest_under['Deviation %']:.2f}%)",
            "Activo más infraponderado frente al objetivo.",
        )
    else:
        info_metric(c6, "Largest Underweight", "-", "Activo más infraponderado frente al objetivo.")


def _build_institutional_proposal(
    ctx,
    tolerance_pct: float,
    min_trade_value: float,
    max_cost_pct: float,
    allow_sells: bool,
):
    df = ctx["df"].copy()
    target_weight_map = df.set_index("Ticker")["Target Weight"].to_dict()

    proposal = build_rebalancing_table(
        df_current=df,
        target_weight_map=target_weight_map,
        base_currency=ctx["base_currency"],
        tc_model=ctx["tc_model"],
        tc_params=ctx["tc_params"],
    ).copy()

    if proposal.empty:
        return proposal, {}, 0.0, 0.0, 0.0, 0

    current_dev_map = df.set_index("Ticker")["Deviation %"].to_dict()
    current_value_map = df.set_index("Ticker")["Value"].to_dict()
    target_pct_map = df.set_index("Ticker")["Target %"].to_dict()

    proposal["Current Deviation %"] = proposal["Ticker"].map(current_dev_map).fillna(0.0)
    proposal["Abs Trade Value"] = proposal["Value Delta"].abs()
    proposal["Estimated Cost %"] = np.where(
        proposal["Abs Trade Value"] > 0,
        proposal["Estimated Cost"] / proposal["Abs Trade Value"] * 100.0,
        0.0,
    )

    decisions = []
    reasons = []

    for _, row in proposal.iterrows():
        deviation = abs(float(row["Current Deviation %"]))
        trade_value = abs(float(row["Value Delta"]))
        cost_pct = float(row["Estimated Cost %"])
        action = str(row["Action"])

        if action == "Hold":
            decisions.append("Hold")
            reasons.append("Already near target")
        elif deviation <= tolerance_pct:
            decisions.append("Hold")
            reasons.append("Inside tolerance band")
        elif trade_value < min_trade_value:
            decisions.append("Hold")
            reasons.append("Below minimum trade value")
        elif action == "Sell" and not allow_sells:
            decisions.append("Skip")
            reasons.append("Sell trades disabled")
        elif cost_pct > max_cost_pct:
            decisions.append("Skip")
            reasons.append("Estimated cost too high")
        else:
            decisions.append("Execute")
            reasons.append("Approved by rules")

    proposal["Decision"] = decisions
    proposal["Reason"] = reasons

    proposed_value_map = {}
    for _, row in proposal.iterrows():
        ticker = str(row["Ticker"])
        current_value = float(current_value_map.get(ticker, 0.0))
        value_delta = float(row["Value Delta"])

        if row["Decision"] == "Execute":
            proposed_value_map[ticker] = max(current_value + value_delta, 0.0)
        else:
            proposed_value_map[ticker] = current_value

    proposed_total = float(sum(proposed_value_map.values()))
    proposed_weight_map = {}

    if proposed_total > 0:
        for ticker, value in proposed_value_map.items():
            proposed_weight_map[ticker] = value / proposed_total * 100.0
    else:
        for ticker in current_value_map:
            proposed_weight_map[ticker] = 0.0

    proposal["Proposed Weight %"] = proposal["Ticker"].map(proposed_weight_map).fillna(0.0)
    proposal["Target Weight %"] = proposal["Ticker"].map(target_pct_map).fillna(0.0)
    proposal["Post-Trade Deviation %"] = proposal["Proposed Weight %"] - proposal["Target Weight %"]

    execute_df = proposal[proposal["Decision"] == "Execute"].copy()
    turnover = (
        float(execute_df["Abs Trade Value"].sum()) / float(df["Value"].sum()) * 100.0
        if float(df["Value"].sum()) > 0
        else 0.0
    )
    total_cost = float(execute_df["Estimated Cost"].sum())
    net_cash_flow = float(execute_df["Net Cash Flow"].sum())
    n_trades = int(len(execute_df))

    proposal = proposal[
        [
            "Ticker",
            "Action",
            "Decision",
            "Reason",
            "Current Weight %",
            "Target Weight %",
            "Current Deviation %",
            "Proposed Weight %",
            "Post-Trade Deviation %",
            "Current Value",
            "Target Value",
            "Value Delta",
            "Estimated Cost",
            "Estimated Cost %",
            "Net Cash Flow",
            "Current Shares",
            "Target Shares",
            "Shares Delta",
        ]
    ].copy()

    for col in [
        "Current Weight %",
        "Target Weight %",
        "Current Deviation %",
        "Proposed Weight %",
        "Post-Trade Deviation %",
        "Current Value",
        "Target Value",
        "Value Delta",
        "Estimated Cost",
        "Estimated Cost %",
        "Net Cash Flow",
    ]:
        proposal[col] = pd.to_numeric(proposal[col], errors="coerce").round(2)

    for col in ["Current Shares", "Target Shares", "Shares Delta"]:
        proposal[col] = pd.to_numeric(proposal[col], errors="coerce").round(4)

    return proposal, proposed_weight_map, turnover, total_cost, net_cash_flow, n_trades


def _build_contribution_plan(ctx, contribution_amount: float, min_trade_value: float):
    suggestion = build_contribution_suggestion(ctx["df"], contribution_amount).copy()

    if suggestion.empty:
        return suggestion, {}, 0.0, 0.0, "-", pd.DataFrame()

    suggestion["Decision"] = np.where(
        suggestion["Suggested Buy Value"] >= min_trade_value,
        "Execute",
        "Hold",
    )
    suggestion["Executed Buy Value"] = np.where(
        suggestion["Decision"] == "Execute",
        suggestion["Suggested Buy Value"],
        0.0,
    )
    suggestion["Executed Shares"] = np.where(
        suggestion["Decision"] == "Execute",
        suggestion["Suggested Shares"],
        0.0,
    )

    current_value_map = ctx["df"].set_index("Ticker")["Value"].to_dict()
    target_pct_map = ctx["df"].set_index("Ticker")["Target %"].to_dict()

    proposed_value_map = {}
    for _, row in suggestion.iterrows():
        ticker = str(row["Ticker"])
        proposed_value_map[ticker] = float(current_value_map.get(ticker, 0.0)) + float(row["Executed Buy Value"])

    proposed_total = float(sum(proposed_value_map.values()))
    proposed_weight_map = {}

    if proposed_total > 0:
        for ticker, value in proposed_value_map.items():
            proposed_weight_map[ticker] = value / proposed_total * 100.0
    else:
        for ticker in current_value_map:
            proposed_weight_map[ticker] = 0.0

    compare_rows = []
    for ticker, current_value in current_value_map.items():
        current_weight = float(ctx["df"].set_index("Ticker").loc[ticker, "Weight %"])
        target_weight = float(target_pct_map.get(ticker, 0.0))
        proposed_weight = float(proposed_weight_map.get(ticker, 0.0))

        compare_rows.append(
            {
                "Ticker": ticker,
                "Current Weight %": round(current_weight, 2),
                "Target Weight %": round(target_weight, 2),
                "Proposed Weight %": round(proposed_weight, 2),
                "Gap After Contribution %": round(proposed_weight - target_weight, 2),
            }
        )

    compare_df = pd.DataFrame(compare_rows).sort_values(
        "Gap After Contribution %",
        key=lambda s: s.abs(),
        ascending=False,
    ).reset_index(drop=True)

    executed_total = float(suggestion["Executed Buy Value"].sum())
    residual_cash = float(contribution_amount - executed_total)

    top_priority = "-"
    execute_only = suggestion[suggestion["Decision"] == "Execute"].copy()
    if not execute_only.empty:
        top_priority = str(execute_only.sort_values("Executed Buy Value", ascending=False).iloc[0]["Ticker"])

    return suggestion, proposed_weight_map, executed_total, residual_cash, top_priority, compare_df


def render_rebalancing_page(ctx):
    render_page_title("Rebalancing")

    if ctx["df"].empty:
        st.info("No portfolio data available.")
        return

    info_section(
        "Phase 3",
        "Esta fase combina tres enfoques: una vista simple y limpia, una vista institucional de propuesta y una vista práctica de qué comprar hoy."
    )

    c1, c2, c3, c4 = st.columns(4)
    tolerance_pct = c1.number_input("Tolerance Band (%)", min_value=0.5, max_value=15.0, value=3.0, step=0.5)
    min_trade_value = c2.number_input(
        f"Minimum Trade Value ({ctx['base_currency']})",
        min_value=0.0,
        value=250.0,
        step=50.0,
    )
    concentration_pct = c3.number_input("Concentration Alert (%)", min_value=5.0, max_value=100.0, value=35.0, step=1.0)
    cash_alert_pct = c4.number_input("Cash Alert (%)", min_value=1.0, max_value=50.0, value=8.0, step=1.0)

    alerts = _build_alerts(
        ctx=ctx,
        tolerance_pct=float(tolerance_pct),
        concentration_pct=float(concentration_pct),
        cash_alert_pct=float(cash_alert_pct),
    )

    info_section(
        "Alerts",
        "Alertas automáticas sobre desviaciones, concentración y cash elevado."
    )
    _render_alerts(alerts)

    tab_simple, tab_institutional, tab_practical = st.tabs(
        ["Simple & Elegant", "Institutional Proposal", "What Should I Buy Today?"]
    )

    with tab_simple:
        info_section(
            "Simple View",
            "Vista limpia para ver rápido qué está fuera de rango y cuánto habría que mover para volver al target."
        )

        monitor_df = _build_monitor_table(
            df=ctx["df"],
            tolerance_pct=float(tolerance_pct),
            base_currency=ctx["base_currency"],
        )

        _build_simple_summary(ctx, monitor_df)

        st.dataframe(monitor_df, use_container_width=True, height=360)

        fig_simple = go.Figure()
        fig_simple.add_bar(x=ctx["df"]["Ticker"], y=ctx["df"]["Weight %"], name="Current %")
        fig_simple.add_bar(x=ctx["df"]["Ticker"], y=ctx["df"]["Target %"], name="Target %")
        fig_simple.update_layout(
            barmode="group",
            paper_bgcolor="#0b0f14",
            plot_bgcolor="#0b0f14",
            font=dict(color="#e6e6e6"),
            height=360,
            margin=dict(t=20, b=20, l=20, r=20),
            xaxis_title="Ticker",
            yaxis_title="Weight %",
        )
        st.plotly_chart(fig_simple, use_container_width=True)

    with tab_institutional:
        info_section(
            "Institutional Proposal",
            "Vista tipo proposal / compare: current vs target vs proposed, con filtros de rebalanceo y costos estimados."
        )

        r1, r2 = st.columns(2)
        allow_sells = r1.checkbox("Allow Sell Trades", value=True)
        max_cost_pct = r2.number_input("Max Cost / Trade (%)", min_value=0.1, max_value=10.0, value=2.0, step=0.1)

        proposal_df, proposed_weight_map, turnover, total_cost, net_cash_flow, n_trades = _build_institutional_proposal(
            ctx=ctx,
            tolerance_pct=float(tolerance_pct),
            min_trade_value=float(min_trade_value),
            max_cost_pct=float(max_cost_pct),
            allow_sells=bool(allow_sells),
        )

        m1, m2, m3, m4 = st.columns(4)
        info_metric(m1, "Trades To Execute", str(n_trades), "Número de operaciones sugeridas.")
        info_metric(m2, "Turnover", f"{turnover:.2f}%", "Trade value / invested holdings.")
        info_metric(m3, "Estimated Cost", f"{ctx['base_currency']} {total_cost:,.2f}", "Costo estimado total.")
        info_metric(m4, "Net Cash Flow", f"{ctx['base_currency']} {net_cash_flow:,.2f}", "Positivo libera cash; negativo consume cash.")

        fig_compare = _build_compare_figure(ctx["df"], proposed_weight_map)
        st.plotly_chart(fig_compare, use_container_width=True)

        st.dataframe(proposal_df, use_container_width=True, height=360)

        execute_df = proposal_df[proposal_df["Decision"] == "Execute"].copy()
        info_section(
            "Manual Orders",
            "Checklist manual para montar las órdenes en tu broker."
        )

        if execute_df.empty:
            st.info("No hay órdenes para ejecutar bajo las reglas actuales.")
        else:
            order_rows = []
            for _, row in execute_df.iterrows():
                order_rows.append(
                    {
                        "Ticker": row["Ticker"],
                        "Side": "BUY" if str(row["Action"]) == "Buy" else "SELL",
                        "Suggested Shares": round(abs(float(row["Shares Delta"])), 4),
                        f"Estimated Value ({ctx['base_currency']})": round(abs(float(row["Value Delta"])), 2),
                        f"Estimated Cost ({ctx['base_currency']})": round(float(row["Estimated Cost"]), 2),
                    }
                )

            st.dataframe(pd.DataFrame(order_rows), use_container_width=True, height=240)

    with tab_practical:
        info_section(
            "Practical View",
            "Enfoque accionable: ingresas cuánto dinero tienes para invertir hoy y la app te dice qué comprar."
        )

        contribution_amount = st.number_input(
            f"Contribution Amount ({ctx['base_currency']})",
            min_value=0.0,
            value=0.0,
            step=100.0,
        )

        contribution_df, contribution_weight_map, executed_total, residual_cash, top_priority, compare_df = _build_contribution_plan(
            ctx=ctx,
            contribution_amount=float(contribution_amount),
            min_trade_value=float(min_trade_value),
        )

        if contribution_amount <= 0:
            st.info("Ingresa un monto positivo para construir el plan de compra.")
        else:
            k1, k2, k3 = st.columns(3)
            info_metric(k1, "Allocated", f"{ctx['base_currency']} {executed_total:,.2f}", "Monto que sí cumple el mínimo operativo.")
            info_metric(k2, "Residual Cash", f"{ctx['base_currency']} {residual_cash:,.2f}", "Cash que quedaría sin asignar.")
            info_metric(k3, "Top Priority", top_priority, "Ticker con mayor monto sugerido de compra.")

            if not contribution_df.empty:
                contribution_df["Current Value"] = pd.to_numeric(contribution_df["Current Value"], errors="coerce").round(2)
                contribution_df["Target Value After Contribution"] = pd.to_numeric(
                    contribution_df["Target Value After Contribution"], errors="coerce"
                ).round(2)
                contribution_df["Suggested Buy Value"] = pd.to_numeric(contribution_df["Suggested Buy Value"], errors="coerce").round(2)
                contribution_df["Executed Buy Value"] = pd.to_numeric(contribution_df["Executed Buy Value"], errors="coerce").round(2)
                contribution_df["Price"] = pd.to_numeric(contribution_df["Price"], errors="coerce").round(2)
                contribution_df["Suggested Shares"] = pd.to_numeric(contribution_df["Suggested Shares"], errors="coerce").round(4)
                contribution_df["Executed Shares"] = pd.to_numeric(contribution_df["Executed Shares"], errors="coerce").round(4)

                st.dataframe(
                    contribution_df[
                        [
                            "Ticker",
                            "Name",
                            "Current Value",
                            "Target Value After Contribution",
                            "Suggested Buy Value",
                            "Executed Buy Value",
                            "Price",
                            "Suggested Shares",
                            "Executed Shares",
                            "Decision",
                        ]
                    ],
                    use_container_width=True,
                    height=340,
                )

                fig_buy_today = _build_compare_figure(ctx["df"], contribution_weight_map)
                st.plotly_chart(fig_buy_today, use_container_width=True)

                st.dataframe(compare_df, use_container_width=True, height=260)