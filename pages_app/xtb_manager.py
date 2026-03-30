"""
XTB Integration Manager page.

Allows syncing positions from XTB, importing transaction history,
and executing rebalancing orders directly through XTB.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app_core import info_metric, info_section, render_page_title


# ── helpers ───────────────────────────────────────────────────────────────────

def _fmt(v, fmt=".4f", fallback="—") -> str:
    try:
        return format(float(v), fmt)
    except Exception:
        return fallback


def _badge(ok: bool) -> str:
    return "✅" if ok else "❌"


# ── Connection test ────────────────────────────────────────────────────────────

def _render_connection_status(ctx):
    from xtb_client import xtb_configured, load_xtb_account

    ccy = ctx.get("base_currency", "USD")

    if not xtb_configured():
        st.warning("XTB no configurado. Agrega `[xtb]` a `.streamlit/secrets.toml`.")
        return False

    col1, col2 = st.columns([3, 1])
    with col2:
        force_refresh = st.button("🔄 Reconectar", key="xtb_refresh_conn")

    if force_refresh:
        st.cache_data.clear()

    with st.spinner("Conectando a XTB..."):
        info, err = load_xtb_account()

    if err:
        st.error(f"Error de conexión XTB: {err}")
        return False

    equity     = float(info.get("equity",  info.get("balance", 0.0)))
    balance    = float(info.get("balance", 0.0))
    margin     = float(info.get("margin",  0.0))
    free_margin = float(info.get("margin_free", info.get("marginFree", 0.0)))

    st.success("Conectado a XTB ✅")
    c1, c2, c3, c4 = st.columns(4)
    info_metric(c1, "Equity",       f"{ccy} {equity:,.2f}",      "Valor total de la cuenta.")
    info_metric(c2, "Balance",      f"{ccy} {balance:,.2f}",     "Balance disponible.")
    info_metric(c3, "Margen usado", f"{ccy} {margin:,.2f}",      "Margen comprometido.")
    info_metric(c4, "Margen libre", f"{ccy} {free_margin:,.2f}", "Margen disponible para operar.")
    return True


# ── Live positions ─────────────────────────────────────────────────────────────

def _render_positions(ctx):
    from xtb_client import load_xtb_positions, trades_to_shares, build_positions_comparison, resolve_ticker

    xtb_source = ctx.get("xtb_source_tickers", [])
    if xtb_source:
        st.success(
            f"Shares de **{', '.join(xtb_source)}** sincronizadas automáticamente desde XTB "
            f"(actualiza cada 60 s) ✅"
        )

    info_section(
        "Posiciones en XTB",
        "Posiciones abiertas leídas directamente de XTB (actualiza cada 60 s).",
    )

    trades, err = load_xtb_positions()
    if err:
        st.error(f"No se pudieron cargar posiciones: {err}")
        return

    if not trades:
        st.info("No hay posiciones abiertas en XTB.")
        return

    ccy = ctx.get("base_currency", "USD")
    rows = []
    total_profit = 0.0
    for t in trades:
        profit = float(t.get("profit", 0.0))
        total_profit += profit
        sym = str(t.get("symbol", ""))
        rows.append({
            "Símbolo XTB":      sym,
            "App Ticker":       resolve_ticker(sym) or "—",
            "Shares":           round(float(t.get("volume", 0.0)), 4),
            "Precio apertura":  round(float(t.get("open_price", 0.0)), 4),
            "P&L no realizado": round(profit, 2),
            "Posición ID":      t.get("position", ""),
        })

    df_pos = pd.DataFrame(rows)
    st.dataframe(df_pos, use_container_width=True, hide_index=True)
    st.caption(f"P&L total no realizado: **{ccy} {total_profit:,.2f}**")

    info_section(
        "Comparación XTB vs App",
        "Las shares se sincronizan automáticamente — esta tabla confirma el estado.",
    )
    xtb_shares = trades_to_shares(trades)
    app_df = ctx.get("df", pd.DataFrame())
    comp = build_positions_comparison(xtb_shares, app_df)
    st.dataframe(comp, use_container_width=True, hide_index=True)


# ── Transaction history import ─────────────────────────────────────────────────

def _render_history_import(ctx):
    from xtb_client import load_xtb_history, history_to_transactions

    info_section(
        "Importar historial de transacciones",
        "Lee el historial de trades cerrados de XTB y permite importarlos a Google Sheets.",
    )

    col1, col2 = st.columns([2, 1])
    with col1:
        start_year = st.number_input("Desde el año", 2020, 2026, 2024, 1, key="xtb_hist_year")
    with col2:
        st.write("")
        st.write("")
        load_btn = st.button("Cargar historial XTB", key="xtb_load_hist")

    if not load_btn and "xtb_history_df" not in st.session_state:
        return

    if load_btn:
        with st.spinner("Cargando historial de XTB..."):
            history, err = load_xtb_history(int(start_year))
        if err:
            st.error(f"Error: {err}")
            return
        df_hist = history_to_transactions(history)
        st.session_state["xtb_history_df"] = df_hist

    df_hist = st.session_state.get("xtb_history_df", pd.DataFrame())

    if df_hist.empty:
        st.info("No hay historial de transacciones en XTB para ese período.")
        return

    st.markdown(f"**{len(df_hist)} transacciones** encontradas en XTB:")
    display = df_hist.copy()
    display["date"] = display["date"].dt.strftime("%Y-%m-%d")
    st.dataframe(display, use_container_width=True, hide_index=True)

    # Check which ones already exist in Sheets
    existing_tx = ctx.get("transactions_df", pd.DataFrame())
    if not existing_tx.empty and "notes" in existing_tx.columns:
        existing_xtb = set(existing_tx[existing_tx["notes"].astype(str).str.startswith("XTB #")]["notes"].tolist())
        new_tx = df_hist[~df_hist["notes"].isin(existing_xtb)]
    else:
        new_tx = df_hist

    if new_tx.empty:
        st.success("Todas las transacciones de XTB ya están importadas en la app ✅")
        return

    st.warning(f"**{len(new_tx)} transacciones nuevas** aún no están en Google Sheets.")
    display_new = new_tx.copy()
    display_new["date"] = display_new["date"].dt.strftime("%Y-%m-%d")
    st.dataframe(display_new, use_container_width=True, hide_index=True)

    if st.button(f"⬇️ Importar {len(new_tx)} transacciones a Google Sheets", type="primary", key="xtb_import_tx"):
        _import_transactions_to_sheets(new_tx)


def _import_transactions_to_sheets(df: pd.DataFrame):
    try:
        from app_core import _connect_named_worksheet, _clear_google_sheets_cache, TRANSACTIONS_HEADERS
        ws = _connect_named_worksheet("transactions", TRANSACTIONS_HEADERS)

        count = 0
        for _, row in df.iterrows():
            date_str = row["date"].strftime("%Y-%m-%d") if hasattr(row["date"], "strftime") else str(row["date"])
            ws.append_row(
                [date_str, row["ticker"], row["type"],
                 row["shares"], row["price"], row["notes"]],
                value_input_option="RAW",
            )
            count += 1

        _clear_google_sheets_cache()
        st.cache_data.clear()
        del st.session_state["xtb_history_df"]
        st.success(f"✅ {count} transacciones importadas. Recarga la app para verlas.")
    except Exception as e:
        st.error(f"Error al importar: {e}")


# ── Rebalancing execution ──────────────────────────────────────────────────────

def _render_execution(ctx):
    from xtb_client import xtb_configured, XTBClient, _get_xtb_cfg, preferred_xtb_symbol

    info_section(
        "Ejecutar Rebalanceo via XTB",
        "Coloca las órdenes de rebalanceo directamente en XTB. "
        "Revisa bien antes de confirmar — las órdenes se ejecutan a precio de mercado.",
    )

    rebalancing_df = ctx.get("rebalancing_df") or ctx.get("rebalancing_table")
    if rebalancing_df is None or rebalancing_df.empty:
        # Build it from ctx if not pre-computed
        try:
            from app_core import build_rebalancing_table
            rebalancing_df, _ = build_rebalancing_table(
                df=ctx["df"],
                frontier=ctx["frontier"],
                max_sharpe_row=ctx["max_sharpe_row"],
                usable=ctx["usable"],
                total_portfolio_value=ctx["total_portfolio_value"],
                tc_model=ctx.get("tc_model", "Simple Bps"),
                tc_params=ctx.get("tc_params", {}),
                base_currency=ctx.get("base_currency", "USD"),
            )
        except Exception:
            pass

    if rebalancing_df is None or rebalancing_df.empty:
        st.info("No hay sugerencias de rebalanceo disponibles. Ve a la página de Rebalance Center primero.")
        return

    # Build order list from rebalancing table
    trade_col = next((c for c in rebalancing_df.columns if "trade" in c.lower() or "shares" in c.lower()), None)
    if trade_col is None:
        st.info("No se pudo determinar las órdenes desde la tabla de rebalanceo.")
        return

    orders = []
    for _, row in rebalancing_df.iterrows():
        ticker = str(row.get("Ticker", ""))
        shares_delta = float(row.get(trade_col, 0.0))
        if abs(shares_delta) < 0.0001:
            continue
        action = "BUY" if shares_delta > 0 else "SELL"
        xtb_sym = preferred_xtb_symbol(ticker)
        orders.append({
            "Ticker": ticker,
            "XTB Symbol": xtb_sym,
            "Acción": action,
            "Shares": abs(round(shares_delta, 4)),
        })

    if not orders:
        st.info("El portafolio ya está balanceado — no hay órdenes que ejecutar.")
        return

    orders_df = pd.DataFrame(orders)
    st.markdown("**Órdenes a ejecutar:**")
    st.dataframe(orders_df, use_container_width=True, hide_index=True)

    st.warning(
        "⚠️ Estas órdenes se ejecutarán a **precio de mercado** en tu cuenta real de XTB. "
        "Verifica que los mercados estén abiertos antes de confirmar."
    )

    # Two-step confirmation
    confirm1 = st.checkbox("Confirmo que revisé las órdenes y quiero ejecutarlas", key="xtb_confirm1")
    if not confirm1:
        return

    confirm2 = st.checkbox("Confirmo que los mercados están abiertos y acepto el riesgo", key="xtb_confirm2")
    if not confirm2:
        return

    if st.button("🚀 Ejecutar órdenes en XTB", type="primary", key="xtb_execute"):
        _execute_orders(orders, ctx)


def _execute_orders(orders: list[dict], ctx):
    from xtb_client import XTBClient, _get_xtb_cfg

    account_id, password, mode = _get_xtb_cfg()
    results = []

    progress = st.progress(0, text="Ejecutando órdenes...")
    total = len(orders)

    try:
        with XTBClient(account_id, password, mode) as client:
            for i, order in enumerate(orders):
                progress.progress((i + 1) / total, text=f"Ejecutando {order['Ticker']}...")
                result = client.place_order(
                    symbol=order["XTB Symbol"],
                    action=order["Acción"],
                    volume=order["Shares"],
                )
                if "order" in result:
                    # Check status
                    import time
                    time.sleep(0.5)
                    status = client.get_order_status(result["order"])
                    results.append({
                        "Ticker": order["Ticker"],
                        "Acción": order["Acción"],
                        "Shares": order["Shares"],
                        "Estado": status.get("requestStatus", "Desconocido"),
                        "Mensaje": status.get("message", ""),
                        "Order ID": result["order"],
                    })
                else:
                    results.append({
                        "Ticker": order["Ticker"],
                        "Acción": order["Acción"],
                        "Shares": order["Shares"],
                        "Estado": "ERROR",
                        "Mensaje": result.get("error", "Error desconocido"),
                        "Order ID": 0,
                    })

    except Exception as e:
        st.error(f"Error durante la ejecución: {e}")
        return

    progress.empty()

    results_df = pd.DataFrame(results)
    errors = results_df[results_df["Estado"] == "ERROR"]
    ok = results_df[results_df["Estado"] != "ERROR"]

    if not ok.empty:
        st.success(f"✅ {len(ok)} órdenes enviadas correctamente.")
    if not errors.empty:
        st.error(f"❌ {len(errors)} órdenes fallaron.")

    st.dataframe(results_df, use_container_width=True, hide_index=True)

    # Clear caches so positions refresh
    st.cache_data.clear()


# ── Main render ────────────────────────────────────────────────────────────────

def render_xtb_manager_page(ctx):
    render_page_title("XTB Manager")

    connected = _render_connection_status(ctx)
    if not connected:
        return

    st.markdown("---")
    tab1, tab2, tab3 = st.tabs(["📊 Posiciones", "📥 Importar historial", "🚀 Ejecutar rebalanceo"])

    with tab1:
        _render_positions(ctx)

    with tab2:
        _render_history_import(ctx)

    with tab3:
        _render_execution(ctx)
