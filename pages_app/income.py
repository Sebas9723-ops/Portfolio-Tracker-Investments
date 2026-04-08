import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from app_core import render_page_title, info_section, info_metric, get_live_dividend_yield


def render_income_page(ctx):
    render_page_title("Income")

    df = ctx["df"].copy()
    ccy = ctx["base_currency"]

    if df.empty:
        st.info("No portfolio data available.")
        return

    # ── Estimated income from yield metadata ─────────────────────────────────
    income_df = df[["Ticker", "Name", "Value"]].copy()
    income_df["Estimated Yield"] = income_df["Ticker"].map(
        lambda x: get_live_dividend_yield(str(x))
    )
    income_df["Estimated Annual Income"] = income_df["Value"] * income_df["Estimated Yield"]
    income_df["Estimated Monthly Income"] = income_df["Estimated Annual Income"] / 12

    annual_income = float(income_df["Estimated Annual Income"].sum())
    monthly_income = float(income_df["Estimated Monthly Income"].sum())
    portfolio_value = float(ctx["total_portfolio_value"])
    portfolio_yield = annual_income / portfolio_value if portfolio_value > 0 else 0.0

    dividends_ytd = float(ctx.get("dividends_ytd", 0.0))
    dividends_total = float(ctx.get("dividends_total", 0.0))

    # ── Top metrics ───────────────────────────────────────────────────────────
    c1, c2, c3, c4, c5 = st.columns(5)
    info_metric(c1, "Est. Annual Income", f"{ccy} {annual_income:,.2f}", "Estimated based on approximate trailing yields.")
    info_metric(c2, "Est. Monthly Income", f"{ccy} {monthly_income:,.2f}", "Estimated monthly income.")
    info_metric(c3, "Portfolio Yield", f"{portfolio_yield:.2%}", "Estimated annual income divided by total portfolio value.")
    info_metric(c4, "Collected YTD", f"{ccy} {dividends_ytd:,.2f}", "Actual dividends collected this calendar year.")
    info_metric(c5, "All-Time Collected", f"{ccy} {dividends_total:,.2f}", "Total dividends recorded across all years.")

    # ── Dividend Calendar ─────────────────────────────────────────────────────
    calendar_df = ctx.get("dividend_calendar_df", pd.DataFrame())
    amount_col = f"Estimated Amount ({ccy})"

    if not calendar_df.empty and amount_col in calendar_df.columns:
        info_section(
            "Dividend Calendar",
            "Projected dividend payments over the next 12 months. "
            "Amounts are estimates based on current position values and trailing yields.",
        )

        cal = calendar_df.copy()
        cal["Pay Date"] = pd.to_datetime(cal["Pay Date"])
        cal["Month_dt"] = cal["Pay Date"].dt.to_period("M").dt.to_timestamp()
        cal["Month"] = cal["Pay Date"].dt.strftime("%b %Y")

        cal_grouped = (
            cal.groupby(["Month_dt", "Month", "Ticker"])[amount_col]
            .sum()
            .reset_index()
            .sort_values("Month_dt")
        )

        # Maintain chronological order on x-axis
        month_order = cal_grouped.sort_values("Month_dt")["Month"].unique().tolist()

        fig = px.bar(
            cal_grouped,
            x="Month",
            y=amount_col,
            color="Ticker",
            barmode="stack",
            category_orders={"Month": month_order},
        )
        fig.update_layout(
            paper_bgcolor="#0b0f14",
            plot_bgcolor="#0b0f14",
            font=dict(color="#e6e6e6"),
            height=380,
            margin=dict(t=20, b=60, l=20, r=20),
            xaxis_title="",
            yaxis_title=f"Income ({ccy})",
            legend=dict(orientation="h", y=1.08, x=0.0),
        )
        st.plotly_chart(fig, use_container_width=True, key="income_calendar_bar")

        cal_display = calendar_df.copy()
        cal_display["Pay Date"] = pd.to_datetime(cal_display["Pay Date"]).dt.strftime("%Y-%m-%d")
        st.dataframe(cal_display[["Pay Date", "Ticker", "Name", amount_col]], use_container_width=True, height=280)
    else:
        portfolio_tickers = sorted(df["Ticker"].astype(str).unique())
        calendar_tickers = set(calendar_df["Ticker"].astype(str).unique()) if not calendar_df.empty else set()
        missing = [t for t in portfolio_tickers if t not in calendar_tickers]
        info_section("Dividend Calendar", "No dividend calendar data found for current holdings.")
        if missing:
            st.info(
                f"The following tickers are not in DIVIDEND_META: **{', '.join(missing)}**. "
                "Add them to `DIVIDEND_META` in `app_core.py` to see projected payments."
            )
        else:
            st.info("Add tickers to `DIVIDEND_META` in `app_core.py` to see projected payments.")

    # ── Income Breakdown by position ─────────────────────────────────────────
    info_section("Income Breakdown", "Estimated income contribution by position using approximate trailing yields.")

    display_df = income_df.copy()
    display_df["Estimated Yield %"] = (display_df["Estimated Yield"] * 100).round(2)
    display_df["Estimated Annual Income"] = display_df["Estimated Annual Income"].round(2)
    display_df["Estimated Monthly Income"] = display_df["Estimated Monthly Income"].round(2)
    display_df["Value"] = display_df["Value"].round(2)

    st.dataframe(
        display_df[["Ticker", "Name", "Value", "Estimated Yield %", "Estimated Annual Income", "Estimated Monthly Income"]],
        use_container_width=True,
        height=280,
    )

    chart_df = display_df[display_df["Estimated Annual Income"] > 0].copy()
    if not chart_df.empty:
        fig = px.bar(
            chart_df.sort_values("Estimated Annual Income", ascending=False),
            x="Ticker",
            y="Estimated Annual Income",
        )
        fig.update_layout(
            paper_bgcolor="#0b0f14",
            plot_bgcolor="#0b0f14",
            font=dict(color="#e6e6e6"),
            height=320,
            margin=dict(t=20, b=20, l=20, r=20),
            showlegend=False,
            xaxis_title="Ticker",
            yaxis_title=f"Est. Annual Income ({ccy})",
        )
        st.plotly_chart(fig, use_container_width=True, key="income_breakdown_bar")

    # ── Collected Dividends ───────────────────────────────────────────────────
    collected_df = ctx.get("collected_dividends_df", pd.DataFrame())

    if not collected_df.empty:
        info_section(
            "Collected Dividends",
            "Actual dividends recorded in your dividend log, sorted newest first.",
        )

        # Monthly income bar chart from collected data
        amount_base_col = f"Amount ({ccy})"
        if amount_base_col in collected_df.columns:
            hist = collected_df.copy()
            hist["Date"] = pd.to_datetime(hist["Date"])
            hist["Month_dt"] = hist["Date"].dt.to_period("M").dt.to_timestamp()
            hist["Month"] = hist["Date"].dt.strftime("%b %Y")
            hist_grouped = (
                hist.groupby(["Month_dt", "Month", "Ticker"])[amount_base_col]
                .sum()
                .reset_index()
                .sort_values("Month_dt")
            )
            if not hist_grouped.empty:
                month_order = hist_grouped["Month"].tolist()
                fig2 = px.bar(
                    hist_grouped,
                    x="Month",
                    y=amount_base_col,
                    color="Ticker",
                    barmode="stack",
                    category_orders={"Month": month_order},
                    title="Monthly Collected Dividends",
                )
                fig2.update_layout(
                    paper_bgcolor="#0b0f14",
                    plot_bgcolor="#0b0f14",
                    font=dict(color="#e6e6e6"),
                    height=320,
                    margin=dict(t=40, b=60, l=20, r=20),
                    xaxis_title="",
                    yaxis_title=f"Collected ({ccy})",
                    legend=dict(orientation="h", y=1.12, x=0.0),
                )
                st.plotly_chart(fig2, use_container_width=True, key="income_collected_bar")

        st.dataframe(collected_df, use_container_width=True, height=320)
    else:
        info_section("Collected Dividends", "No dividends recorded yet.")
        st.info("Record received dividends via the Income section of Private Manager.")
